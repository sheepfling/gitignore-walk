"""Explain and traverse Git-ignore policies with explicit policy scope."""

from ._errors import GitIgnoreError, GitIgnoreParseError
from ._git import GitStandardPolicy
from ._ignore_file import (
    GitIgnoreMatch,
    GitIgnoreMatcher,
    GitIgnoreSpec,
    RegexMatcher,
    matches_gitignore,
    parse_gitignore,
)
from ._portable import (
    GitIgnoreDecision,
    GitIgnorePolicy,
    GitIgnoreWalkEntry,
    GitIgnoreWalker,
    IgnorePolicy,
    is_gitignored,
)

__all__ = [
    "GitIgnoreDecision",
    "GitIgnoreError",
    "GitIgnoreMatch",
    "GitIgnoreParseError",
    "GitIgnoreMatcher",
    "GitIgnorePolicy",
    "GitIgnoreSpec",
    "GitIgnoreWalkEntry",
    "GitIgnoreWalker",
    "GitStandardPolicy",
    "IgnorePolicy",
    "RegexMatcher",
    "is_gitignored",
    "matches_gitignore",
    "parse_gitignore",
]
