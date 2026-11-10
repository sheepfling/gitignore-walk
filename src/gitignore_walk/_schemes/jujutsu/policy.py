"""Read-only Jujutsu ignore policy using its captured Git-compatible sources."""

from __future__ import annotations

# This adapter intentionally reuses Git's ignore dialect while keeping Jujutsu workspace discovery
# and colocated `.git` source handling separate from Git resolver selection.
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
from ..._util import lexical_target_path
from ..git._configuration import resolve_core_excludes_file
from ..git.portable import (
    GitIgnorePolicy,
    _find_repository_metadata,
    _GitIgnoreMembershipWalkSession,
)
from .errors import JujutsuIgnoreError


class JujutsuIgnorePolicy(GitIgnorePolicy):
    """Evaluate captured Jujutsu `.gitignore` behavior without running `jj`.

    The policy discovers the nearest `.jj` workspace. It reads workspace `.gitignore` files and
    the conventional XDG Git ignore file. A colocated `.git` directory contributes its
    `info/exclude`; an enclosing Git repository outside the Jujutsu workspace does not. This
    read-only evaluator avoids invoking `jj` commands that snapshot the working copy. Opt-in
    membership queries list the saved working-copy tree with `--ignore-working-copy`. Walks stop
    at nested Jujutsu workspaces and do not enter `.jj` or colocated `.git` metadata directories.

    This policy covers the captured source layout and Git-compatible ignore dialect. Membership is
    unknown unless ``membership_aware`` is enabled. Callers can pass ``core.excludesFile``
    explicitly or opt in to Git configuration discovery with ``read_git_config``.

    Attributes:
        root: Caller-selected target and traversal boundary.
        workspace_root: Nearest enclosing `.jj` workspace.
        scheme: Stable ``"jujutsu"`` identifier.
    """

    @property
    def scheme(self) -> str:
        """Return the stable identifier for Jujutsu policy decisions."""
        return "jujutsu"

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        environment: Mapping[str, str] | None = None,
        global_excludes_file: str | os.PathLike[str] | None = None,
        read_git_config: bool = False,
        git_executable: str = "git",
        git_config_timeout: float = 30.0,
        initial_excludes: Sequence[str] = (".jj",),
        follow_symlinked_gitignore: bool = False,
        membership_aware: bool = False,
        jujutsu_executable: str = "jj",
        timeout: float = 30.0,
    ) -> None:
        """Bind a caller root to its nearest enclosing `.jj` workspace.

        ``global_excludes_file`` overrides the conventional XDG ignore path. Pass the path
        configured by Git's ``core.excludesFile`` when the Jujutsu environment selects a custom
        file. Set ``read_git_config`` to ask ``git config`` to resolve that setting (including
        global config includes); this requires ``git_executable`` to be available. For a
        non-colocated workspace, the internal Git store supplies conditional-include context unless
        ``environment`` already sets ``GIT_DIR``.

        Set ``follow_symlinked_gitignore`` for Jujutsu before version 0.46.0, which followed
        nested symlinked `.gitignore` files. The default skips these sources, matching version
        0.46.0 and newer.

        Set ``membership_aware`` to list the saved working-copy tree with ``jj file list`` and
        ``--ignore-working-copy``. Saved-tree files are versioned; present files absent from that
        tree are unversioned. Absent paths not in the tree remain unknown. This avoids asking
        Jujutsu to snapshot filesystem changes while answering the query.
        """
        caller_root = Path(root).expanduser().resolve()
        if not caller_root.is_dir():
            raise ValueError(f"Jujutsu policy root must be a directory: {caller_root}")
        workspace_root = _find_workspace(caller_root)
        super().__init__(caller_root, environment=environment, initial_excludes=initial_excludes)
        self._allow_symlinked_gitignore = follow_symlinked_gitignore
        if not isfinite(timeout) or timeout <= 0:
            raise ValueError("Jujutsu client timeout must be finite and positive")
        self.membership_aware = membership_aware
        self.jujutsu_executable = jujutsu_executable
        self.environment = environment
        self.timeout = timeout
        self.workspace_root = workspace_root
        self._repository_root = workspace_root
        metadata = _find_repository_metadata(workspace_root)
        self._repository_excludes = (
            metadata.git_dir / "info" / "exclude"
            if metadata is not None and metadata.root == workspace_root
            else None
        )
        if global_excludes_file is not None:
            self._global_excludes = Path(global_excludes_file).expanduser()
        elif read_git_config:
            git_dir = None
            if metadata is None or metadata.root != workspace_root:
                internal_git_dir = workspace_root / ".jj" / "repo" / "store" / "git"
                if internal_git_dir.is_dir():
                    git_dir = internal_git_dir
            self._global_excludes = resolve_core_excludes_file(
                workspace_root,
                environment=environment,
                git_executable=git_executable,
                timeout=git_config_timeout,
                default_path=self._global_excludes,
                git_dir=git_dir,
            )

    def explain(self, target: str | os.PathLike[str]) -> IgnoreDecision:
        """Explain ignore rules and optionally annotate saved-tree membership."""
        decision = super().explain(target)
        membership = self._load_membership() if self.membership_aware else None
        return self._with_membership(decision, membership, target)

    def trace(self, target: str | os.PathLike[str]) -> IgnoreTrace:
        """Return the inherited rule trace and optional saved-tree membership annotation."""
        trace = super().trace(target)
        membership = self._load_membership() if self.membership_aware else None
        return replace(trace, decision=self._with_membership(trace.decision, membership, target))

    def iter_explain(
        self,
        targets: Iterable[str | os.PathLike[str]],
        *,
        batch_size: int = 256,
    ) -> Iterator[IgnoreDecision]:
        """Explain targets in order using one saved-tree membership snapshot per iteration."""
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
        """Create a walk session with stable source and optional saved-tree snapshots."""
        membership = self._load_membership() if self.membership_aware else None
        return _GitIgnoreMembershipWalkSession(self, membership, self._with_membership)

    def _with_membership(
        self,
        decision: IgnoreDecision,
        versioned: set[Path] | None,
        requested: str | os.PathLike[str],
    ) -> IgnoreDecision:
        """Annotate saved-tree files and present unlisted files with known membership."""
        if versioned is None:
            return decision
        requested_path = lexical_target_path(self.root, requested)
        if requested_path in versioned:
            membership: Literal["versioned", "unversioned"] | None = "versioned"
        elif requested_path.is_file() or requested_path.is_symlink():
            membership = "unversioned"
        else:
            membership = None
        return replace(decision, membership=membership)

    def _load_membership(self) -> set[Path]:
        """Capture Jujutsu's saved working-copy files without snapshotting filesystem changes."""
        environment = dict(os.environ if self.environment is None else self.environment)
        try:
            result = subprocess.run(
                [
                    self.jujutsu_executable,
                    "--ignore-working-copy",
                    "file",
                    "list",
                    "--revision",
                    "@",
                    "--template",
                    'path ++ "\\0"',
                ],
                cwd=self.workspace_root,
                env=environment,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise JujutsuIgnoreError(
                f"Unable to discover Jujutsu working-copy membership: {error}",
                operation="membership",
            ) from error
        if result.returncode != 0:
            detail = result.stderr.decode(errors="replace").strip() or "unknown Jujutsu error"
            raise JujutsuIgnoreError(
                f"Jujutsu working-copy membership query failed: {detail}",
                operation="membership",
            )

        versioned: set[Path] = set()
        for record in result.stdout.split(b"\0"):
            if not record:
                continue
            relative = os.fsdecode(record)
            if os.name == "nt":
                relative = relative.replace("\\", "/")
            relative_path = PurePath(relative)
            if relative_path.is_absolute() or relative_path.drive or ".." in relative_path.parts:
                raise JujutsuIgnoreError(
                    "Jujutsu returned a saved-tree path outside its workspace.",
                    operation="membership",
                )
            versioned.add(self.workspace_root / relative_path)
        return versioned

    def should_descend_directory(self, target: Path) -> bool:
        """Keep walks out of Jujutsu metadata and nested Jujutsu workspaces."""
        if target.name in {".git", ".jj"}:
            return False
        return not (target / ".jj").exists()


def _find_workspace(root: Path) -> Path:
    """Find the nearest enclosing Jujutsu `.jj` marker."""
    for candidate in (root, *root.parents):
        if (candidate / ".jj").is_dir():
            return candidate
    raise ValueError(f"no Jujutsu .jj workspace found above {root}")
