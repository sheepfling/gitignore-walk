"""Explain and traverse Git-ignore policies with explicit policy scope."""

from ._git import GitStandardPolicy
from ._patterns import GitIgnoreSpec
from ._portable import (
    GitIgnoreDecision,
    GitIgnoreError,
    GitIgnorePolicy,
    GitIgnoreWalkEntry,
    GitIgnoreWalker,
    is_gitignored,
    matches_gitignore,
    parse_gitignore,
)

__all__ = [
    "GitIgnoreDecision",
    "GitIgnoreError",
    "GitIgnorePolicy",
    "GitIgnoreSpec",
    "GitIgnoreWalkEntry",
    "GitIgnoreWalker",
    "GitStandardPolicy",
    "is_gitignored",
    "matches_gitignore",
    "parse_gitignore",
]
