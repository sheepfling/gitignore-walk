"""Git ignore dialect implementations and their public Git-facing helpers."""

from ._ignore_file import (
    RegexMatcher,
    matches_gitignore,
    parse_gitignore,
)
from ._ignore_protocols import GitIgnoreMatcher
from ._ignore_types import GitIgnoreMatch, GitIgnoreSpec
from .native import GitStandardPolicy
from .portable import GitIgnorePolicy, is_gitignored

__all__ = [
    "GitIgnoreMatch",
    "GitIgnoreMatcher",
    "GitIgnorePolicy",
    "GitIgnoreSpec",
    "GitStandardPolicy",
    "RegexMatcher",
    "is_gitignored",
    "matches_gitignore",
    "parse_gitignore",
]
