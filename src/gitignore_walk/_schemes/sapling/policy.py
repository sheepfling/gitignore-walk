"""Read-only Sapling ignore policy using its captured Git-compatible rule sources."""

from __future__ import annotations

# This adapter intentionally reuses the Git dialect evaluator while selecting Sapling's
# workspace and source layout from native evidence.
# pyright: reportPrivateUsage=false
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..git.portable import (
    GitIgnorePolicy,
    _default_global_excludes_path,
    _find_repository_metadata,
)


class SaplingIgnorePolicy(GitIgnorePolicy):
    """Evaluate captured Sapling `.gitignore` behavior without running `sl`.

    Sapling's `.sl` storage mode reads workspace `.gitignore` files but does not apply Git's XDG
    ignore file or `.git/info/exclude`. Sapling's `.git` mode uses all three sources with Git
    precedence. The policy discovers the nearest `.sl` or `.git` workspace marker and keeps the
    caller's ``root`` as the query and traversal bound.

    This policy covers only the captured ignore dialect/source behavior. It does not query
    Sapling membership or implement Sapling's other configuration sources.

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
        initial_excludes: Sequence[str] | None = None,
    ) -> None:
        """Bind a caller root to a discovered Sapling `.sl` or `.git` workspace."""
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
        self.workspace_root = workspace_root
        self._repository_root = workspace_root
        metadata = _find_repository_metadata(workspace_root)
        self._repository_excludes = (
            metadata.common_dir / "info" / "exclude"
            if storage == "git" and metadata is not None and metadata.root == workspace_root
            else None
        )
        self._global_excludes = (
            _default_global_excludes_path(environment) if storage == "git" else None
        )


def _find_workspace(root: Path) -> tuple[Path, str]:
    """Find the nearest Sapling workspace marker and return its storage mode."""
    for candidate in (root, *root.parents):
        if (candidate / ".sl").exists():
            return candidate, "sl"
        if (candidate / ".git").exists():
            return candidate, "git"
    raise ValueError(f"no Sapling .sl or .git workspace found above {root}")
