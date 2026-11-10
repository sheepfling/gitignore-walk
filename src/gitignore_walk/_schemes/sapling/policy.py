"""Read-only Sapling ignore policy using its captured Git-compatible rule sources."""

from __future__ import annotations

# This adapter intentionally reuses the Git dialect evaluator while selecting Sapling's
# workspace and source layout from native evidence.
# pyright: reportPrivateUsage=false
import os
import subprocess
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import replace
from itertools import tee
from math import isfinite
from pathlib import Path, PurePath
from typing import Literal

from ..._policy import IgnoreDecision, IgnoreTrace, _IgnoreWalkSession
from ..git._configuration import resolve_core_excludes_file
from ..git.portable import (
    GitIgnorePolicy,
    _default_global_excludes_path,
    _find_repository_metadata,
    _GitIgnoreMembershipWalkSession,
    _lexical_target_path,
)
from .errors import SaplingIgnoreError


class SaplingIgnorePolicy(GitIgnorePolicy):
    """Evaluate captured Sapling `.gitignore` behavior without running `sl`.

    Sapling's `.sl` storage mode reads workspace `.gitignore` files but does not apply Git's XDG
    ignore file or `.git/info/exclude`. Sapling's `.git` mode uses all three sources with Git
    precedence. For nested `.gitignore` files, `.sl` mode follows symlinks while `.git` mode skips
    them, matching the captured Sapling behavior. Walking stops at nested workspaces that use the
    same storage marker as the selected workspace. The policy discovers the nearest `.sl` or `.git`
    workspace marker and keeps the caller's ``root`` as the query and traversal bound.

    This policy covers only the captured ignore dialect/source behavior. It does not query
    Sapling membership or discover ``core.excludesFile`` from Git configuration; callers can pass
    that resolved path explicitly with ``global_excludes_file``.

    Attributes:
        root: Caller-selected target and traversal boundary.
        workspace_root: Nearest enclosing `.sl` or `.git` workspace.
        scheme: Stable ``"sapling"`` identifier.
    """

    @property
    def scheme(self) -> str:
        """Return the stable identifier for Sapling policy decisions."""
        return "sapling"

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        environment: Mapping[str, str] | None = None,
        global_excludes_file: str | os.PathLike[str] | None = None,
        read_git_config: bool = False,
        git_executable: str = "git",
        git_config_timeout: float = 30.0,
        initial_excludes: Sequence[str] | None = None,
        membership_aware: bool = False,
        sapling_executable: str = "sl",
        timeout: float = 30.0,
    ) -> None:
        """Bind a caller root to a discovered Sapling `.sl` or `.git` workspace.

        ``global_excludes_file`` overrides the conventional XDG ignore path in `.git` storage
        mode. Pass the path configured by Git's ``core.excludesFile`` when Sapling's environment
        selects a custom file. Set ``read_git_config`` to ask ``git config`` to resolve that
        setting (including global config includes); this requires ``git_executable`` to be
        available. `.sl` storage mode does not read a Git global ignore source.

        Set ``membership_aware`` to query Sapling's NUL-delimited ``status --all`` output. The
        native status distinguishes versioned files (including ignored tracked files) from
        unversioned and ignored files; paths not reported by status remain unknown.
        """
        caller_root = Path(root).expanduser().resolve()
        if not caller_root.is_dir():
            raise ValueError(f"Sapling policy root must be a directory: {caller_root}")
        workspace_root, storage = _find_workspace(caller_root)
        excludes = (
            ((".sl",) if storage == "sl" else (".git",))
            if initial_excludes is None
            else initial_excludes
        )
        super().__init__(caller_root, environment=environment, initial_excludes=excludes)
        self._allow_symlinked_gitignore = storage == "sl"
        self._workspace_marker = ".sl" if storage == "sl" else ".git"
        self.workspace_root = workspace_root
        self._repository_root = workspace_root
        if not isfinite(timeout) or timeout <= 0:
            raise ValueError("Sapling client timeout must be finite and positive")
        self.membership_aware = membership_aware
        self.sapling_executable = sapling_executable
        self.environment = environment
        self.timeout = timeout
        metadata = _find_repository_metadata(workspace_root)
        self._repository_excludes = (
            metadata.common_dir / "info" / "exclude"
            if storage == "git" and metadata is not None and metadata.root == workspace_root
            else None
        )
        if storage == "git":
            default_path = _default_global_excludes_path(environment)
            if global_excludes_file is not None:
                self._global_excludes = Path(global_excludes_file).expanduser()
            elif read_git_config:
                self._global_excludes = resolve_core_excludes_file(
                    workspace_root,
                    environment=environment,
                    git_executable=git_executable,
                    timeout=git_config_timeout,
                    default_path=default_path,
                )
            else:
                self._global_excludes = default_path
        else:
            self._global_excludes = None

    def explain(self, target: str | os.PathLike[str]) -> IgnoreDecision:
        """Explain ignore rules and optionally annotate native Sapling membership."""
        decision = super().explain(target)
        membership = self._load_membership() if self.membership_aware else None
        return self._with_membership(decision, membership, target)

    def trace(self, target: str | os.PathLike[str]) -> IgnoreTrace:
        """Return the inherited rule trace and optional native membership annotation."""
        trace = super().trace(target)
        membership = self._load_membership() if self.membership_aware else None
        return replace(trace, decision=self._with_membership(trace.decision, membership, target))

    def iter_explain(
        self,
        targets: Iterable[str | os.PathLike[str]],
        *,
        batch_size: int = 256,
    ) -> Iterator[IgnoreDecision]:
        """Explain targets in order using one native membership snapshot per iteration."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        membership = self._load_membership() if self.membership_aware else None
        requested_targets, policy_targets = tee(targets)
        for decision, requested in zip(
            super().iter_explain(policy_targets, batch_size=batch_size),
            requested_targets,
            strict=True,
        ):
            yield self._with_membership(decision, membership, requested)

    def _open_walk(self) -> _IgnoreWalkSession:
        """Create a walk session with stable source and optional status snapshots."""
        membership = self._load_membership() if self.membership_aware else None
        return _GitIgnoreMembershipWalkSession(self, membership, self._with_membership)

    def _with_membership(
        self,
        decision: IgnoreDecision,
        membership: Mapping[Path, Literal["versioned", "unversioned"]] | None,
        requested: str | os.PathLike[str],
    ) -> IgnoreDecision:
        """Return a decision annotated with known native membership, if available."""
        if membership is None:
            return decision
        path = _lexical_target_path(self.root, requested)
        return replace(decision, membership=membership.get(path))

    def _load_membership(self) -> dict[Path, Literal["versioned", "unversioned"]]:
        """Capture Sapling status classes for one decision batch or walk."""
        environment = dict(os.environ if self.environment is None else self.environment)
        try:
            result = subprocess.run(
                [self.sapling_executable, "status", "--all", "--print0", "--root-relative"],
                cwd=self.workspace_root,
                env=environment,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SaplingIgnoreError(
                f"Unable to discover Sapling working-copy membership: {error}",
                operation="membership",
            ) from error
        if result.returncode != 0:
            detail = result.stderr.decode(errors="replace").strip() or "unknown Sapling error"
            raise SaplingIgnoreError(
                f"Sapling working-copy membership query failed: {detail}",
                operation="membership",
            )

        membership: dict[Path, Literal["versioned", "unversioned"]] = {}
        for record in result.stdout.split(b"\0"):
            if not record:
                continue
            if len(record) < 3 or record[1:2] != b" ":
                raise SaplingIgnoreError(
                    "Sapling returned an invalid NUL-delimited status record.",
                    operation="membership",
                )
            code = record[:1]
            relative = os.fsdecode(record[2:])
            if os.name == "nt":
                relative = relative.replace("\\", "/")
            relative_path = PurePath(relative)
            if relative_path.is_absolute() or relative_path.drive or ".." in relative_path.parts:
                raise SaplingIgnoreError(
                    "Sapling returned a status path outside its workspace.",
                    operation="membership",
                )
            path = self.workspace_root / relative_path
            if code in (b"C", b"M", b"A", b"R", b"!"):
                membership[path] = "versioned"
            elif code in (b"?", b"I"):
                membership[path] = "unversioned"
            else:
                raise SaplingIgnoreError(
                    f"Sapling returned unsupported status code {code!r}.",
                    operation="membership",
                )
        return membership

    def should_descend_directory(self, target: Path) -> bool:
        """Keep walks out of Sapling metadata and nested same-storage workspaces."""
        if target.name == ".git" or (self._workspace_marker == ".sl" and target.name == ".sl"):
            return False
        return not (target / self._workspace_marker).exists()


def _find_workspace(root: Path) -> tuple[Path, str]:
    """Find the nearest Sapling workspace marker and return its storage mode."""
    for candidate in (root, *root.parents):
        if (candidate / ".sl").exists():
            return candidate, "sl"
        if (candidate / ".git").exists():
            return candidate, "git"
    raise ValueError(f"no Sapling .sl or .git workspace found above {root}")
