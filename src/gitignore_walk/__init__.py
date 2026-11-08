"""Explain and traverse Git-ignore policies with explicit policy scope."""

from ._policy import (
    IgnoreDecision,
    IgnoreDiagnostic,
    IgnorePolicy,
    IgnoreTrace,
    IgnoreTraceMatch,
    IgnoreWalkEntry,
)
from ._schemes.git import (
    GitIgnoreMatch,
    GitIgnoreMatcher,
    GitIgnorePolicy,
    GitIgnoreSpec,
    GitStandardPolicy,
    RegexMatcher,
    is_gitignored,
    matches_gitignore,
    parse_gitignore,
)
from ._selection import (
    GitPolicyConfig,
    GitPolicySelection,
    PolicyConfig,
    PolicySelection,
    PortablePolicyConfig,
    PortablePolicySelection,
    PreferGitPolicyConfig,
    select_policy,
)
from ._walker import IgnoreWalker
from .errors import GitIgnoreError, GitIgnoreParseError

__all__ = [
    "GitIgnoreError",
    "GitIgnoreMatch",
    "GitIgnoreMatcher",
    "GitIgnoreParseError",
    "GitIgnorePolicy",
    "GitIgnoreSpec",
    "GitPolicyConfig",
    "GitPolicySelection",
    "GitStandardPolicy",
    "IgnoreDecision",
    "IgnoreDiagnostic",
    "IgnorePolicy",
    "IgnoreTrace",
    "IgnoreTraceMatch",
    "IgnoreWalkEntry",
    "IgnoreWalker",
    "PolicyConfig",
    "PolicySelection",
    "PortablePolicyConfig",
    "PortablePolicySelection",
    "PreferGitPolicyConfig",
    "RegexMatcher",
    "is_gitignored",
    "matches_gitignore",
    "parse_gitignore",
    "select_policy",
]
