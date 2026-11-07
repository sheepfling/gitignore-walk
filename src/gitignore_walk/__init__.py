"""Explain and traverse Git-ignore policies with explicit policy scope."""

from ._git import GitStandardPolicy
from ._ignore_file import (
    GitIgnoreMatch,
    GitIgnoreMatcher,
    GitIgnoreSpec,
    RegexMatcher,
    matches_gitignore,
    parse_gitignore,
)
from ._pathspec import PathSpecMatcher
from ._portable import (
    GitIgnoreDecision,
    GitIgnoreError,
    GitIgnorePolicy,
    GitIgnoreWalkEntry,
    GitIgnoreWalker,
    is_gitignored,
)

__all__ = [
    "GitIgnoreDecision",
    "GitIgnoreError",
    "GitIgnoreMatch",
    "GitIgnoreMatcher",
    "GitIgnorePolicy",
    "GitIgnoreSpec",
    "GitIgnoreWalkEntry",
    "GitIgnoreWalker",
    "GitStandardPolicy",
    "PathSpecMatcher",
    "RegexMatcher",
    "is_gitignored",
    "matches_gitignore",
    "parse_gitignore",
]
