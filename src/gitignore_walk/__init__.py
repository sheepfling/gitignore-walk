"""Explain and traverse Git-ignore policies with explicit policy scope."""

from ._git import GitStandardPolicy
from ._portable import (
    GitIgnoreDecision,
    GitIgnoreError,
    GitIgnorePolicy,
    GitIgnoreWalker,
    is_gitignored,
    matches_gitignore,
    parse_gitignore,
)

__all__ = [
    "GitIgnoreDecision",
    "GitIgnoreError",
    "GitIgnorePolicy",
    "GitIgnoreWalker",
    "GitStandardPolicy",
    "is_gitignored",
    "matches_gitignore",
    "parse_gitignore",
]
