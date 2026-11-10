"""Read-only Sapling ignore policy using its captured Git-compatible rule sources."""

from __future__ import annotations

# This adapter intentionally reuses the Git dialect evaluator while selecting Sapling's
# workspace and source layout from native evidence.
# pyright: reportPrivateUsage=false
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..git._configuration import resolve_core_excludes_file
from ..git.portable import (
    GitIgnorePolicy,
    _default_global_excludes_path,
    _find_repository_metadata,
)


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
    ) -> None:
        """Bind a caller root to a discovered Sapling `.sl` or `.git` workspace.

        ``global_excludes_file`` overrides the conventional XDG ignore path in `.git` storage
        mode. Pass the path configured by Git's ``core.excludesFile`` when Sapling's environment
        selects a custom file. Set ``read_git_config`` to ask ``git config`` to resolve that
        setting (including global config includes); this requires ``git_executable`` to be
        available. `.sl` storage mode does not read a Git global ignore source.
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
