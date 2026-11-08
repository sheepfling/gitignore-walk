"""Opt-in Git-native policy, without a second implementation of Git config."""

from __future__ import annotations

# Internal implementation modules share private policy hooks, not public APIs.
# pyright: reportPrivateUsage=false
import math
import os
import subprocess
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from itertools import islice
from pathlib import Path
from typing import Final

from ._environment import EnvVar
from ._policy import IgnoreDecision
from ._portable import (
    _DEFAULT_INITIAL_EXCLUDES,
    _decision_from_match,
    _GitIgnorePolicyBase,
    _IgnoreSnapshot,
    _match_loaded_ignore,
)
from .errors import GitIgnoreError

# Repository selection must come from root, not an unrelated invoking Git process.
_REPOSITORY_ENVIRONMENT: Final = (
    EnvVar.GIT_DIR,
    EnvVar.GIT_WORK_TREE,
    EnvVar.GIT_COMMON_DIR,
    EnvVar.GIT_INDEX_FILE,
    EnvVar.GIT_PREFIX,
)


def _decode_git_output(data: bytes) -> str:
    # Windows' os.fsdecode uses surrogatepass; Git may return arbitrary ignore-file
    # bytes. Preserve those bytes in provenance without failing unrelated decisions.
    return data.decode(sys.getfilesystemencoding(), errors="surrogateescape")


def _scope_from_git_source(source: str, root: Path) -> str:
    """Return the effective Git-ignore scope relative to the worktree root."""
    source_path = Path(source)
    if source_path.name != ".gitignore":
        return "."
    source_path = source_path if source_path.is_absolute() else root / source_path
    try:
        scope = source_path.parent.relative_to(root).as_posix()
    except ValueError:
        # Git's global ignore file can itself be named .gitignore; its rules apply from the root.
        return "."
    return scope or "."


class GitStandardPolicy(_GitIgnorePolicyBase):
    """Use Git's configured excludes and matching implementation explicitly.

    Requires Git and the root of a non-bare worktree. Global/system/local/worktree
    configuration, includes, XDG defaults, .git/info/exclude and repository ignore
    files are resolved by Git itself. Uses ``--no-index``: rules are evaluated even
    for tracked files. This is an ignore-policy query, not a prediction of what
    Git will commit.

    ``environment`` is a complete subprocess environment, not an overlay. Omit it
    to copy the current environment at construction. Repository-selection variables
    are removed; Git configuration and HOME/XDG variables remain effective.
    Nonempty Git diagnostics raise instead of silently returning partial results. The hard
    ``initial_excludes`` baseline defaults to ``(".git",)`` and is evaluated before invoking Git.

    Attributes:
        git_executable: Executable name or path used to invoke Git.
        timeout: Maximum duration in seconds for each Git subprocess.
    """

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        initial_excludes: Sequence[str] = _DEFAULT_INITIAL_EXCLUDES,
        git_executable: str = "git",
        environment: Mapping[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Create a Git-backed policy with explicit subprocess and timeout settings."""
        super().__init__(root, initial_excludes=initial_excludes)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        self.git_executable = git_executable
        self.timeout = timeout
        self._environment = dict(os.environ if environment is None else environment)
        for name in _REPOSITORY_ENVIRONMENT:
            self._environment.pop(name, None)
        result = self._run(("rev-parse", "--show-toplevel"), accepted=(0,))
        worktree = Path(_decode_git_output(result.stdout.removesuffix(b"\n"))).resolve()
        if worktree != self.root:
            raise ValueError("GitStandardPolicy root must be the Git worktree root")

    def resolve_target(self, target: str | os.PathLike[str]) -> Path:
        """Keep Git's pathname identity; never traverse an intermediate symlink."""

        target_path = Path(target).expanduser()
        if not target_path.is_absolute():
            target_path = self.root / target_path
        target_path = Path(os.path.abspath(target_path))
        if not target_path.is_relative_to(self.root):
            raise ValueError(f"target must be inside repository root: {target_path}")
        parent = target_path.parent
        while parent != self.root and parent.is_relative_to(self.root):
            if parent.is_symlink():
                raise ValueError(f"target crosses a symlink: {parent}")
            parent = parent.parent
        return target_path

    def _walk_top(self, target: str | os.PathLike[str]) -> Path:
        path = self.resolve_target(target)
        if path.is_symlink():
            raise ValueError("GitStandardPolicy walks cannot start at a symlink")
        return path

    def explain(self, target: str | os.PathLike[str]) -> IgnoreDecision:
        """Explain one path using a fresh Git process."""

        return self.explain_many((target,))[0]

    def explain_many(
        self,
        targets: Iterable[str | os.PathLike[str]],
    ) -> list[IgnoreDecision]:
        """Explain an ordered batch in one Git process using NUL-safe input/output.

        This does not freeze the filesystem. A later batch sees changed ignore files.
        Caller baseline exclusions remain authoritative.
        """

        resolved = tuple(self.resolve_target(target) for target in targets)
        if not resolved:
            return []
        decisions: dict[int, IgnoreDecision] = {}
        pending: list[tuple[int, Path]] = []
        for index, path in enumerate(resolved):
            baseline = _match_loaded_ignore(
                self._initial_excludes,
                path.relative_to(self.root).as_posix(),
                is_directory=not path.is_symlink() and path.is_dir(),
                scope=".",
            )
            if baseline is not None and baseline.ignored:
                decisions[index] = _decision_from_match(path=path, match=baseline)
            else:
                pending.append((index, path))
        if not pending:
            return [decisions[index] for index in range(len(resolved))]
        arguments = ["check-ignore", "--verbose", "--non-matching", "-z", "--stdin", "--no-index"]
        relative = tuple(os.fsencode(path.relative_to(self.root).as_posix()) for _, path in pending)
        if any(b"\0" in path for path in relative):
            raise ValueError("Git-ignore paths cannot contain NUL")
        result = self._run(arguments, data=b"\0".join(relative) + b"\0", accepted=(0, 1))
        fields = result.stdout.split(b"\0")
        if fields[-1] != b"" or len(fields) != 4 * len(pending) + 1:
            raise GitIgnoreError("Git returned an incomplete check-ignore response")
        for batch_index, (original_index, path) in enumerate(pending):
            source, line, pattern, echoed = fields[batch_index * 4 : batch_index * 4 + 4]
            if echoed != relative[batch_index]:
                raise GitIgnoreError("Git returned an unexpected check-ignore path")
            if source:
                try:
                    line_number = int(line)
                except ValueError as error:
                    raise GitIgnoreError("Git returned an invalid ignore line number") from error
                if line_number < 1 or not pattern:
                    raise GitIgnoreError("Git returned invalid ignore provenance")
                decision = IgnoreDecision(
                    path=path,
                    ignored=not pattern.startswith(b"!"),
                    scheme=self.scheme,
                    source=_decode_git_output(source),
                    pattern=_decode_git_output(pattern),
                    line=line_number,
                    scope=_scope_from_git_source(_decode_git_output(source), self.root),
                    reason="matched-rule",
                    discovery_complete=True,
                )
            elif line or pattern:
                raise GitIgnoreError("Git returned incomplete ignore provenance")
            else:
                decision = IgnoreDecision(
                    path=path,
                    ignored=False,
                    scheme=self.scheme,
                    reason="no-matching-rule",
                    discovery_complete=True,
                )
            decisions[original_index] = decision
        return [decisions[index] for index in range(len(resolved))]

    def iter_explain(
        self, targets: Iterable[str | os.PathLike[str]], *, batch_size: int = 256
    ) -> Iterator[IgnoreDecision]:
        """Query bounded batches lazily; each batch observes Git's current rules."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        iterator = iter(targets)
        while batch := list(islice(iterator, batch_size)):
            yield from self.explain_many(batch)

    def is_ignored_many(
        self,
        targets: Iterable[str | os.PathLike[str]],
    ) -> list[bool]:
        """Return rule decisions in input order using one Git process."""
        return [decision.ignored for decision in self.explain_many(targets)]

    def _decisions(
        self, targets: Sequence[Path], snapshot: _IgnoreSnapshot
    ) -> list[IgnoreDecision]:
        return self.explain_many(targets)

    def decision(self, *, target: Path, snapshot: _IgnoreSnapshot) -> IgnoreDecision:
        """Implement the policy hook; Git loads its own ignore state per query."""
        # The portable walker supplies a per-operation snapshot. Native Git loads its
        # own rules per process; never pretend this is the portable snapshot contract.
        return self.explain(target)

    def _run(
        self,
        arguments: Sequence[str],
        *,
        accepted: tuple[int, ...],
        data: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        try:
            result = subprocess.run(
                [self.git_executable, "-C", os.fspath(self.root), *arguments],
                input=data,
                capture_output=True,
                env=self._environment,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise GitIgnoreError(f"unable to execute Git ignore policy: {error}") from error
        if result.returncode not in accepted or result.stderr:
            detail = _decode_git_output(result.stderr).strip() or f"exit status {result.returncode}"
            raise GitIgnoreError(f"Git ignore policy failed: {detail}")
        return result
