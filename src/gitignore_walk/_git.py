"""Opt-in Git-native policy, without a second implementation of Git config."""

from __future__ import annotations

# Internal implementation modules share private policy hooks, not public APIs.
# pyright: reportPrivateUsage=false
import math
import os
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from ._portable import (
    GitIgnoreDecision,
    GitIgnoreError,
    GitIgnorePolicy,
    _decision_from_match,
    _IgnoreSnapshot,
    _match_loaded_ignore,
)

# Repository selection must come from root, not an unrelated invoking Git process.
_REPOSITORY_ENVIRONMENT = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_PREFIX",
)


def _decode_git_output(data: bytes) -> str:
    # Windows' os.fsdecode uses surrogatepass; Git may return arbitrary ignore-file
    # bytes. Preserve those bytes in provenance without failing unrelated decisions.
    return data.decode(sys.getfilesystemencoding(), errors="surrogateescape")


class GitStandardPolicy(GitIgnorePolicy):
    """Use Git's configured excludes and matching implementation explicitly.

    Requires Git and the root of a non-bare worktree. Global/system/local/worktree
    configuration, includes, XDG defaults, .git/info/exclude and repository ignore
    files are resolved by Git itself. Uses ``--no-index``: rules are evaluated even
    for tracked files. This is an ignore-policy query, not a prediction of what
    Git will commit.

    ``environment`` is a complete subprocess environment, not an overlay. Omit it
    to copy the current environment at construction. Repository-selection variables
    are removed; Git configuration and HOME/XDG variables remain effective.
    Nonempty Git diagnostics raise instead of silently returning partial results.
    """

    def __init__(
        self,
        root: str | os.PathLike[str] | Path,
        *,
        initial_excludes: Sequence[str] = (),
        git_executable: str = "git",
        environment: Mapping[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
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

    def resolve_target(self, target: str | os.PathLike[str] | Path) -> Path:
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

    def _walk_top(self, target: str | os.PathLike[str] | Path) -> Path:
        path = self.resolve_target(target)
        if path.is_symlink():
            raise ValueError("GitStandardPolicy walks cannot start at a symlink")
        return path

    def explain(self, target: str | os.PathLike[str] | Path) -> GitIgnoreDecision:
        """Explain one path using a fresh Git process."""

        return self.explain_many((target,))[0]

    def explain_many(
        self,
        targets: Iterable[str | os.PathLike[str] | Path],
    ) -> tuple[GitIgnoreDecision, ...]:
        """Explain an ordered batch in one Git process using NUL-safe input/output.

        This does not freeze the filesystem. A later batch sees changed ignore files.
        Caller baseline exclusions remain authoritative.
        """

        resolved = tuple(self.resolve_target(target) for target in targets)
        if not resolved:
            return ()
        arguments = ["check-ignore", "--verbose", "--non-matching", "-z", "--stdin"]
        arguments.append("--no-index")
        relative = tuple(os.fsencode(path.relative_to(self.root).as_posix()) for path in resolved)
        if any(b"\0" in path for path in relative):
            raise ValueError("Git-ignore paths cannot contain NUL")
        result = self._run(arguments, data=b"\0".join(relative) + b"\0", accepted=(0, 1))
        fields = result.stdout.split(b"\0")
        if fields[-1] != b"" or len(fields) != 4 * len(resolved) + 1:
            raise GitIgnoreError("Git returned an incomplete check-ignore response")
        decisions: list[GitIgnoreDecision] = []
        for index, path in enumerate(resolved):
            source, line, pattern, echoed = fields[index * 4 : index * 4 + 4]
            if echoed != relative[index]:
                raise GitIgnoreError("Git returned an unexpected check-ignore path")
            if source:
                try:
                    line_number = int(line)
                except ValueError as error:
                    raise GitIgnoreError("Git returned an invalid ignore line number") from error
                if line_number < 1 or not pattern:
                    raise GitIgnoreError("Git returned invalid ignore provenance")
                decision = GitIgnoreDecision(
                    path=path,
                    ignored=not pattern.startswith(b"!"),
                    source=_decode_git_output(source),
                    pattern=_decode_git_output(pattern),
                    line=line_number,
                )
            elif line or pattern:
                raise GitIgnoreError("Git returned incomplete ignore provenance")
            else:
                decision = GitIgnoreDecision(path=path, ignored=False)
            baseline = _match_loaded_ignore(
                self._initial_excludes,
                path.relative_to(self.root).as_posix(),
                is_directory=not path.is_symlink() and path.is_dir(),
            )
            if baseline is not None and baseline.ignored:
                decision = _decision_from_match(path=path, match=baseline)
            decisions.append(decision)
        return tuple(decisions)

    def is_ignored_many(
        self,
        targets: Iterable[str | os.PathLike[str] | Path],
    ) -> tuple[bool, ...]:
        """Return rule decisions in input order using one Git process."""

        return tuple(decision.ignored for decision in self.explain_many(targets))

    def _decisions(
        self, targets: Sequence[Path], snapshot: _IgnoreSnapshot
    ) -> tuple[GitIgnoreDecision, ...]:
        return self.explain_many(targets)

    def decision(self, *, target: Path, snapshot: _IgnoreSnapshot) -> GitIgnoreDecision:
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
