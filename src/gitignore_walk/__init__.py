"""Explain and traverse Git-ignore policies with explicit policy scope."""

from ._git import GitStandardPolicy
from ._ignore_file import GitIgnoreSpec, matches_gitignore, parse_gitignore
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
    "GitIgnorePolicy",
    "GitIgnoreSpec",
    "GitIgnoreWalkEntry",
    "GitIgnoreWalker",
    "GitStandardPolicy",
    "is_gitignored",
    "matches_gitignore",
    "parse_gitignore",
]
