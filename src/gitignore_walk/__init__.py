"""Explain and traverse Git-ignore policies with explicit policy scope."""

from ._git import GitStandardPolicy
from ._ignore_file import RegexMatcher, matches_gitignore, parse_gitignore
from ._ignore_protocols import GitIgnoreMatcher
from ._ignore_types import GitIgnoreMatch, GitIgnoreSpec
from ._portable import (
    GitIgnoreDecision,
    GitIgnorePolicy,
    GitIgnoreTrace,
    GitIgnoreTraceMatch,
    GitIgnoreWalkEntry,
    GitIgnoreWalker,
    IgnorePolicy,
    is_gitignored,
)
from .errors import GitIgnoreError, GitIgnoreParseError

__all__ = [
    "GitIgnoreDecision",
    "GitIgnoreError",
    "GitIgnoreMatch",
    "GitIgnoreMatcher",
    "GitIgnoreParseError",
    "GitIgnorePolicy",
    "GitIgnoreSpec",
    "GitIgnoreTrace",
    "GitIgnoreTraceMatch",
    "GitIgnoreWalkEntry",
    "GitIgnoreWalker",
    "GitStandardPolicy",
    "IgnorePolicy",
    "RegexMatcher",
    "is_gitignored",
    "matches_gitignore",
    "parse_gitignore",
]
