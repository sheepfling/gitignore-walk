"""Read-only Jujutsu ignore policy using its captured Git-compatible sources."""

from __future__ import annotations

# This adapter intentionally reuses Git's ignore dialect while keeping Jujutsu workspace discovery
# and colocated `.git` source handling separate from Git resolver selection.
# pyright: reportPrivateUsage=false
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..git._configuration import resolve_core_excludes_file
from ..git.portable import GitIgnorePolicy, _find_repository_metadata


class JujutsuIgnorePolicy(GitIgnorePolicy):
    """Evaluate captured Jujutsu `.gitignore` behavior without running `jj`.

    The policy discovers the nearest `.jj` workspace. It reads workspace `.gitignore` files and
    the conventional XDG Git ignore file. A colocated `.git` directory contributes its
    `info/exclude`; an enclosing Git repository outside the Jujutsu workspace does not. This
    read-only evaluator avoids invoking `jj` commands that snapshot the working copy.

    This policy covers the captured source layout and Git-compatible ignore dialect. It does not
    report Jujutsu membership. Callers can pass ``core.excludesFile`` explicitly or opt in to Git
    configuration discovery with ``read_git_config``.

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
        """
        caller_root = Path(root).expanduser().resolve()
        if not caller_root.is_dir():
            raise ValueError(f"Jujutsu policy root must be a directory: {caller_root}")
        workspace_root = _find_workspace(caller_root)
        super().__init__(caller_root, environment=environment, initial_excludes=initial_excludes)
        self._allow_symlinked_gitignore = follow_symlinked_gitignore
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


def _find_workspace(root: Path) -> Path:
    """Find the nearest enclosing Jujutsu `.jj` marker."""
    for candidate in (root, *root.parents):
        if (candidate / ".jj").is_dir():
            return candidate
    raise ValueError(f"no Jujutsu .jj workspace found above {root}")
