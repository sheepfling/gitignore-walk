"""Read-only Sapling and Jujutsu Git-ignore compatibility policies."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gitignore_walk import (
    IgnoreWalker,
    JujutsuIgnorePolicy,
    JujutsuPolicyConfig,
    JujutsuPolicySelection,
    SaplingIgnorePolicy,
    SaplingPolicyConfig,
    SaplingPolicySelection,
    select_policy,
)

_SOURCE_EXPECTATIONS = {
    "sapling-git": ["global.global", "info.priority", "local.local"],
    "sapling-sl": [],
    "jj-colocated": ["global.global", "info.priority", "local.local"],
    "jj-noncolocated": ["global.global", "priority.global"],
}


@pytest.mark.parametrize("mode", sorted(_SOURCE_EXPECTATIONS))
def test_native_captured_ignore_sources_match_read_only_policy(tmp_path: Path, mode: str) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    home = tmp_path / "home"
    (home / ".config" / "git").mkdir(parents=True)
    (home / ".config" / "git" / "ignore").write_text("*.global\n", encoding="utf-8")
    nested = root / "nested"
    nested.mkdir()
    environment = {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config")}

    if mode in {"sapling-git", "jj-colocated"}:
        _git_init(root)
    elif mode == "sapling-sl":
        (root / ".sl").mkdir()
    else:
        (root / ".jj").mkdir()
    if mode.startswith("jj-"):
        (root / ".jj").mkdir(exist_ok=True)

    (root / ".gitignore").write_text("*.tmp\n!local.priority\n", encoding="utf-8")
    git_info = root / ".git" / "info"
    if git_info.is_dir():
        (git_info / "exclude").write_text(
            "*.local\n!priority.global\ninfo.priority\nlocal.priority\n", encoding="utf-8"
        )
    for name in (
        "global.global",
        "local.local",
        "priority.global",
        "info.priority",
        "local.priority",
    ):
        (nested / name).touch()

    if mode.startswith("sapling-"):
        policy = SaplingIgnorePolicy(nested, environment=environment)
        assert policy.workspace_root == root
    else:
        policy = JujutsuIgnorePolicy(nested, environment=environment)
        assert policy.workspace_root == root

    expected_ignored = set(_SOURCE_EXPECTATIONS[mode])
    all_names = {
        "global.global",
        "local.local",
        "priority.global",
        "info.priority",
        "local.priority",
    }
    decisions = policy.explain_many(all_names)
    assert {decision.path.name for decision in decisions if decision.ignored} == expected_ignored
    assert {decision.scheme for decision in decisions} == {
        "sapling" if mode.startswith("sapling-") else "jujutsu"
    }

    walker = IgnoreWalker(nested, policy=policy)
    walked_ignored = {path.name for path in walker.iter_files(selection="ignored")}
    assert walked_ignored == expected_ignored


def test_sapling_sl_workspace_does_not_inherit_outer_git_info_exclude(tmp_path: Path) -> None:
    outer = tmp_path / "outer"
    outer.mkdir()
    _git_init(outer)
    info = outer / ".git" / "info" / "exclude"
    info.write_text("*.local\n", encoding="utf-8")
    workspace = outer / "sapling"
    (workspace / ".sl").mkdir(parents=True)
    (workspace / "inside.local").touch()

    policy = SaplingIgnorePolicy(workspace)

    assert policy.workspace_root == workspace
    assert not policy.explain("inside.local").ignored


def test_jujutsu_workspace_does_not_inherit_outer_git_info_exclude(tmp_path: Path) -> None:
    outer = tmp_path / "outer"
    outer.mkdir()
    _git_init(outer)
    info = outer / ".git" / "info" / "exclude"
    info.write_text("*.local\n", encoding="utf-8")
    workspace = outer / "jujutsu"
    (workspace / ".jj").mkdir(parents=True)
    (workspace / "inside.local").touch()

    policy = JujutsuIgnorePolicy(workspace)

    assert policy.workspace_root == workspace
    assert not policy.explain("inside.local").ignored


def test_compatible_scheme_selection_is_typed_and_explicit(tmp_path: Path) -> None:
    sapling_root = tmp_path / "sapling"
    (sapling_root / ".sl").mkdir(parents=True)
    jj_root = tmp_path / "jj"
    (jj_root / ".jj").mkdir(parents=True)

    sapling = select_policy(sapling_root, SaplingPolicyConfig())
    jujutsu = select_policy(jj_root, JujutsuPolicyConfig())

    assert isinstance(sapling, SaplingPolicySelection)
    assert isinstance(sapling.policy, SaplingIgnorePolicy)
    assert sapling.backend == "sapling-gitignore-portable"
    assert isinstance(jujutsu, JujutsuPolicySelection)
    assert isinstance(jujutsu.policy, JujutsuIgnorePolicy)
    assert jujutsu.backend == "jujutsu-gitignore-portable"


def _git_init(root: Path) -> None:
    result = subprocess.run(
        ["git", "init", "-q", str(root)], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise AssertionError(result.stderr)
