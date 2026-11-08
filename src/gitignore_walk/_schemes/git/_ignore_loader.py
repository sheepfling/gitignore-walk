"""Read ignore files and attach source labels to their compiled rules."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TypeVar, overload

from ...errors import GitIgnoreError
from ._ignore_file import DEFAULT_MATCHER
from ._ignore_protocols import GitIgnoreMatcher
from ._ignore_types import GitIgnoreFile, GitIgnoreSpec

SpecT = TypeVar("SpecT")

__all__ = ["load_gitignore"]


@overload
def load_gitignore(
    path: Path,
    *,
    matcher: None = None,
    allow_symlink: bool = False,
) -> GitIgnoreFile[GitIgnoreSpec] | None: ...


@overload
def load_gitignore(
    path: Path,
    *,
    matcher: GitIgnoreMatcher[SpecT],
    allow_symlink: bool = False,
) -> GitIgnoreFile[SpecT] | None: ...


def load_gitignore(
    path: Path,
    *,
    matcher: GitIgnoreMatcher[Any] | None = None,
    allow_symlink: bool = False,
) -> GitIgnoreFile[Any] | None:
    """Read and compile one ignore file, following symlinks only when requested."""

    if matcher is None:
        matcher = DEFAULT_MATCHER

    try:
        if not path.is_file() or (path.is_symlink() and not allow_symlink):
            return None
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise GitIgnoreError(
            f"unable to read Git-ignore source: {path}: {error}",
            operation="read",
            path=os.fspath(path),
        ) from error

    if path.name == ".gitignore":
        source = f"repository .gitignore {path}"
    elif path.name == "exclude" and path.parent.name == "info":
        source = f"repository info/exclude {path}"
    else:
        source = f"user-global excludes {path}"
    return GitIgnoreFile(source=source, spec=matcher.parse(lines, source=source), matcher=matcher)
