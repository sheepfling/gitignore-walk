"""Downstream type-check fixture for resolver configuration and selection."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from typing_extensions import assert_type

from gitignore_walk import (
    GitIgnorePolicy,
    GitPolicyConfig,
    GitPolicySelection,
    GitStandardPolicy,
    PolicyConfig,
    PolicySelection,
    PortablePolicyConfig,
    PortablePolicySelection,
    PreferGitPolicyConfig,
    select_policy,
)


def check_policy_selection(root: Path, git_executable: str) -> None:
    """Check config discrimination and result narrowing by actual backend."""
    portable = select_policy(root)
    assert_type(portable, PortablePolicySelection)
    assert_type(portable.policy, GitIgnorePolicy)

    portable_config = PortablePolicyConfig()
    portable_result = select_policy(root, portable_config)
    assert_type(portable_result, PortablePolicySelection)

    git_result = select_policy(root, GitPolicyConfig(git_executable=git_executable))
    assert_type(git_result, GitPolicySelection)
    assert_type(git_result.policy, GitStandardPolicy)

    preferred: PolicySelection = select_policy(
        root, PreferGitPolicyConfig(git_executable=git_executable)
    )
    if preferred.backend == "git":
        assert_type(preferred.policy, GitStandardPolicy)
        assert_type(preferred.fallback_reason, None)
        assert_type(preferred.mode, Literal["git", "prefer-git"])
    else:
        assert_type(preferred.policy, GitIgnorePolicy)
        assert_type(
            preferred.fallback_reason,
            Literal["git-executable-missing"] | None,
        )
        assert_type(preferred.mode, Literal["portable", "prefer-git"])

    config: PolicyConfig = PreferGitPolicyConfig(git_executable=git_executable)
    check_policy_config(config)


def check_policy_config(config: PolicyConfig) -> None:
    """Check that the config tag narrows its fields to the matching variant."""
    if config.mode == "portable":
        assert_type(config, PortablePolicyConfig)
    elif config.mode == "git":
        assert_type(config, GitPolicyConfig)
    else:
        assert_type(config, PreferGitPolicyConfig)
