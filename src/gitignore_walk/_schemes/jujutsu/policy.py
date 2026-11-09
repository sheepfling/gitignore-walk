"""Read-only Jujutsu ignore policy using its captured Git-compatible sources."""

from __future__ import annotations

# This adapter intentionally reuses Git's ignore dialect while keeping Jujutsu workspace discovery
# and colocated `.git` source handling separate from Git resolver selection.
# pyright: reportPrivateUsage=false
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..git.portable import GitIgnorePolicy, _find_repository_metadata


class JujutsuIgnorePolicy(GitIgnorePolicy):
    """Evaluate captured Jujutsu `.gitignore` behavior without running `jj`.

    The policy discovers the nearest `.jj` workspace. It reads workspace `.gitignore` files and
    the conventional XDG Git ignore file. A colocated `.git` directory contributes its
    `info/exclude`; an enclosing Git repository outside the Jujutsu workspace does not. This
    read-only evaluator avoids invoking `jj` commands that snapshot the working copy.

    This policy covers the captured source layout and Git-compatible ignore dialect. It does not
    report Jujutsu membership or alternate global configuration sources.

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
        initial_excludes: Sequence[str] = (".jj",),
    ) -> None:
        """Bind a caller root to its nearest enclosing `.jj` workspace."""
        caller_root = Path(root).expanduser().resolve()
        if not caller_root.is_dir():
            raise ValueError(f"Jujutsu policy root must be a directory: {caller_root}")
        workspace_root = _find_workspace(caller_root)
        super().__init__(caller_root, environment=environment, initial_excludes=initial_excludes)
        self.workspace_root = workspace_root
        self._repository_root = workspace_root
        metadata = _find_repository_metadata(workspace_root)
        self._repository_excludes = (
            metadata.common_dir / "info" / "exclude"
            if metadata is not None and metadata.root == workspace_root
            else None
        )


def _find_workspace(root: Path) -> Path:
    """Find the nearest enclosing Jujutsu `.jj` marker."""
    for candidate in (root, *root.parents):
        if (candidate / ".jj").is_dir():
            return candidate
    raise ValueError(f"no Jujutsu .jj workspace found above {root}")
