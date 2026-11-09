"""Downstream type-check fixture for resolver configuration and selection."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from typing_extensions import assert_type

from gitignore_walk import (
    BreezyIgnorePolicy,
    BreezyPolicyConfig,
    BreezyPolicySelection,
    DarcsBoringPolicy,
    DarcsPolicyConfig,
    DarcsPolicySelection,
    FossilIgnorePolicy,
    FossilPolicyConfig,
    FossilPolicySelection,
    GitIgnorePolicy,
    GitPolicyConfig,
    GitPolicySelection,
    GitStandardPolicy,
    IgnoreDecision,
    IgnoreWalker,
    JujutsuIgnorePolicy,
    JujutsuPolicyConfig,
    JujutsuPolicySelection,
    MercurialIgnorePolicy,
    MercurialPolicyConfig,
    MercurialPolicySelection,
    PerforceIgnorePolicy,
    PerforcePolicyConfig,
    PerforcePolicySelection,
    PolicyConfig,
    PortablePolicyConfig,
    PortablePolicySelection,
    PreferGitPolicyConfig,
    SaplingIgnorePolicy,
    SaplingPolicyConfig,
    SaplingPolicySelection,
    SubversionIgnorePolicy,
    SubversionPolicyConfig,
    SubversionPolicySelection,
    select_policy,
)


def check_policy_selection(root: Path, git_executable: str) -> None:
    """Check config discrimination and result narrowing by actual backend."""
    portable = select_policy(root)
    assert_type(portable, PortablePolicySelection)
    assert_type(portable.policy, GitIgnorePolicy)
    assert_type(portable.policy.explain("target"), IgnoreDecision)
    walker = IgnoreWalker(root, policy=portable.policy)
    assert_type(walker, IgnoreWalker)

    portable_config = PortablePolicyConfig()
    portable_result = select_policy(root, portable_config)
    assert_type(portable_result, PortablePolicySelection)

    git_result = select_policy(root, GitPolicyConfig(git_executable=git_executable))
    assert_type(git_result, GitPolicySelection)
    assert_type(git_result.policy, GitStandardPolicy)

    mercurial_result = select_policy(root, MercurialPolicyConfig())
    assert_type(mercurial_result, MercurialPolicySelection)
    assert_type(mercurial_result.policy, MercurialIgnorePolicy)
    assert_type(mercurial_result.policy.scheme, str)

    subversion_result = select_policy(root, SubversionPolicyConfig())
    assert_type(subversion_result, SubversionPolicySelection)
    assert_type(subversion_result.policy, SubversionIgnorePolicy)

    fossil_result = select_policy(root, FossilPolicyConfig())
    assert_type(fossil_result, FossilPolicySelection)
    assert_type(fossil_result.policy, FossilIgnorePolicy)

    breezy_result = select_policy(root, BreezyPolicyConfig())
    assert_type(breezy_result, BreezyPolicySelection)
    assert_type(breezy_result.policy, BreezyIgnorePolicy)

    perforce_result = select_policy(root, PerforcePolicyConfig())
    assert_type(perforce_result, PerforcePolicySelection)
    assert_type(perforce_result.policy, PerforceIgnorePolicy)

    darcs_result = select_policy(root, DarcsPolicyConfig())
    assert_type(darcs_result, DarcsPolicySelection)
    assert_type(darcs_result.policy, DarcsBoringPolicy)

    sapling_result = select_policy(root, SaplingPolicyConfig())
    assert_type(sapling_result, SaplingPolicySelection)
    assert_type(sapling_result.policy, SaplingIgnorePolicy)

    jujutsu_result = select_policy(root, JujutsuPolicyConfig())
    assert_type(jujutsu_result, JujutsuPolicySelection)
    assert_type(jujutsu_result.policy, JujutsuIgnorePolicy)

    preferred = select_policy(root, PreferGitPolicyConfig(git_executable=git_executable))
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
    mercurial_config: PolicyConfig = MercurialPolicyConfig()
    check_policy_config(mercurial_config)
    subversion_config: PolicyConfig = SubversionPolicyConfig()
    check_policy_config(subversion_config)
    fossil_config: PolicyConfig = FossilPolicyConfig()
    check_policy_config(fossil_config)
    breezy_config: PolicyConfig = BreezyPolicyConfig()
    check_policy_config(breezy_config)
    perforce_config: PolicyConfig = PerforcePolicyConfig()
    check_policy_config(perforce_config)
    darcs_config: PolicyConfig = DarcsPolicyConfig()
    check_policy_config(darcs_config)
    sapling_config: PolicyConfig = SaplingPolicyConfig()
    check_policy_config(sapling_config)
    jujutsu_config: PolicyConfig = JujutsuPolicyConfig()
    check_policy_config(jujutsu_config)


def check_policy_config(config: PolicyConfig) -> None:
    """Check that the config tag narrows its fields to the matching variant."""
    if config.mode == "portable":
        assert_type(config, PortablePolicyConfig)
    elif config.mode == "git":
        assert_type(config, GitPolicyConfig)
    elif config.mode == "prefer-git":
        assert_type(config, PreferGitPolicyConfig)
    elif config.mode == "mercurial":
        assert_type(config, MercurialPolicyConfig)
    elif config.mode == "perforce":
        assert_type(config, PerforcePolicyConfig)
    elif config.mode == "subversion":
        assert_type(config, SubversionPolicyConfig)
    elif config.mode == "fossil":
        assert_type(config, FossilPolicyConfig)
    elif config.mode == "breezy":
        assert_type(config, BreezyPolicyConfig)
    elif config.mode == "darcs":
        assert_type(config, DarcsPolicyConfig)
    elif config.mode == "sapling":
        assert_type(config, SaplingPolicyConfig)
    else:
        assert_type(config, JujutsuPolicyConfig)
