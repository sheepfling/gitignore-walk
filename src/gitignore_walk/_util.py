"""Small package utilities shared by implementation modules."""

from __future__ import annotations

import os
from pathlib import Path


def is_windows() -> bool:
    """Return whether the current Python process runs on Windows."""
    return os.name == "nt"


def lexical_target_path(root: Path, target: str | os.PathLike[str]) -> Path:
    """Return a normalized absolute target path without following symbolic links."""
    target_path = Path(target).expanduser()
    if not target_path.is_absolute():
        target_path = root / target_path
    return Path(os.path.abspath(target_path))


def is_nested_workspace_directory(
    target: Path, workspace_root: Path, markers: tuple[str, ...]
) -> bool:
    """Return whether a descendant directory contains another workspace's marker."""
    if target == workspace_root or not target.is_relative_to(workspace_root):
        return False
    return any((target / marker).exists() for marker in markers)
