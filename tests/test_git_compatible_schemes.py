"""Read-only Sapling and Jujutsu Git-ignore compatibility policies."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from gitignore_walk import (
    GitIgnoreError,
    GitIgnorePolicy,
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

_PATTERN_RULES = (
    "blocked/\n!blocked/keep.txt\ncache/*\n!cache/keep.tmp\n/root-only.tmp\n**/deep.log\n"
)
_PATTERN_FILES = (
    "blocked/keep.txt",
    "cache/drop.tmp",
    "cache/keep.tmp",
    "root-only.tmp",
    "nested/root-only.tmp",
    "nested/deep/deep.log",
)
_PATTERN_IGNORED = {
    "blocked/keep.txt",
    "cache/drop.tmp",
    "root-only.tmp",
    "nested/deep/deep.log",
}
_COMPAT_ORACLE_ROOT = Path(__file__).parent / "oracles" / "compat"
_COMPAT_FIXTURE = json.loads((_COMPAT_ORACLE_ROOT / "cases.json").read_text(encoding="utf-8"))
_JJ_046_CAPTURE = json.loads(
    (_COMPAT_ORACLE_ROOT / "results" / "jj-0.46.0-debian13-x86_64.json").read_text(encoding="utf-8")
)
_WORKSPACE_BOUNDARY_CASES = _COMPAT_FIXTURE["workspace_boundary"]
_WORKSPACE_BOUNDARY_PROFILES = (
    "workspace-boundaries-sapling-0.2.20261103-jj-0.47.1-macos-arm64.json",
    "workspace-boundaries-sapling-0.2.20261103-jj-0.47.1-debian13-arm64.json",
    "workspace-boundaries-sapling-0.2.20261103-jj-0.47.1-debian13-x86_64.json",
)
_JJ_046_WORKSPACE_BOUNDARY_PROFILES = (
    "workspace-boundaries-jj-0.46.0-macos-arm64.json",
    "workspace-boundaries-jj-0.46.0-debian13-x86_64.json",
)


def _git_config_path(path: Path) -> str:
    """Serialize an absolute path using Git config's portable slash form."""
    return path.as_posix()


def _git_supports_worktree_conditional_includes() -> bool:
    result = subprocess.run(["git", "--version"], capture_output=True, text=True, check=False)
    version = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", result.stdout)
    return bool(version and tuple(map(int, version.groups())) >= (2, 56, 0))


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
    git_directory = root / ".git"
    if git_directory.is_dir():
        git_info = git_directory / "info"
        git_info.mkdir(parents=True, exist_ok=True)
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
    info.parent.mkdir(parents=True, exist_ok=True)
    info.write_text("*.local\n", encoding="utf-8")
    workspace = outer / "sapling"
    (workspace / ".sl").mkdir(parents=True)
    (workspace / "inside.local").touch()

    policy = SaplingIgnorePolicy(workspace)

    assert policy.workspace_root == workspace
    assert not policy.explain("inside.local").ignored


@pytest.mark.parametrize(
    ("parent_storage", "nested_storage", "nested_files_visible"),
    tuple(
        (case["parent_storage"], case["nested_storage"], case["expected_nested_visible"])
        for case in _WORKSPACE_BOUNDARY_CASES["sapling_cases"]
    ),
)
def test_sapling_walk_respects_captured_storage_specific_workspace_boundaries(
    tmp_path: Path,
    parent_storage: str,
    nested_storage: str,
    nested_files_visible: bool,
) -> None:
    """Stop only at nested Sapling workspaces with the parent's storage marker."""
    root = tmp_path / "workspace"
    root.mkdir()
    environment = {
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
    }
    if parent_storage == "sl":
        (root / ".sl").mkdir()
    else:
        _git_init(root)
    (root / ".gitignore").write_text("outer.tmp\n", encoding="utf-8")
    (root / "outer.tmp").touch()
    nested = root / "nested"
    nested.mkdir()
    marker = ".sl" if nested_storage == "sl" else ".git"
    (nested / marker).mkdir()
    nested_file = nested / "child.log"
    nested_file.touch()

    policy = SaplingIgnorePolicy(root, environment=environment)
    walker = IgnoreWalker(root, policy=policy)
    all_files = {path.relative_to(root).as_posix() for path in walker.iter_files(selection="all")}
    ignored_files = {
        path.relative_to(root).as_posix() for path in walker.iter_files(selection="ignored")
    }
    assert not policy.explain("nested/child.log").ignored
    assert "outer.tmp" in ignored_files
    assert ("nested/child.log" in all_files) is nested_files_visible
    if not nested_files_visible:
        assert list(walker.iter_files(top=nested, selection="all")) == []


@pytest.mark.parametrize("colocated", [False, True])
def test_jujutsu_walk_stops_at_nested_workspace_and_metadata(
    tmp_path: Path, colocated: bool
) -> None:
    """Keep nested `.jj` workspaces and colocated `.git` data outside a parent walk."""
    root = tmp_path / "workspace"
    root.mkdir()
    environment = {
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
    }
    (root / ".jj").mkdir()
    if colocated:
        (root / ".git").mkdir()
    (root / ".gitignore").write_text("outer.tmp\n", encoding="utf-8")
    (root / "outer.tmp").touch()
    nested = root / "nested"
    nested.mkdir()
    (nested / ".jj").mkdir()
    nested_file = nested / "child.log"
    nested_file.touch()

    policy = JujutsuIgnorePolicy(root, environment=environment)
    walker = IgnoreWalker(root, policy=policy)
    all_files = {path.relative_to(root).as_posix() for path in walker.iter_files(selection="all")}
    ignored_files = {
        path.relative_to(root).as_posix() for path in walker.iter_files(selection="ignored")
    }
    assert not policy.explain("nested/child.log").ignored
    assert "outer.tmp" in ignored_files
    assert "nested/child.log" not in all_files
    assert "nested/child.log" not in ignored_files
    assert list(walker.iter_files(top=nested, selection="all")) == []


@pytest.mark.parametrize(
    "profile", _WORKSPACE_BOUNDARY_PROFILES, ids=lambda name: name.removesuffix(".json")
)
def test_workspace_boundary_native_profiles_match_the_captured_contract(profile: str) -> None:
    """Keep Sapling's storage-specific and Jujutsu's nested-workspace boundaries evidenced."""
    capture = json.loads((_COMPAT_ORACLE_ROOT / "results" / profile).read_text(encoding="utf-8"))
    assert capture["status"] == "captured"
    assert capture["clients"]["sapling"].startswith("Sapling 0.2.20261103")
    assert capture["clients"]["jujutsu"].startswith("jj 0.47.1")

    cases = {case["id"]: case for case in capture["cases"]}
    expected = {
        probe["id"]: probe["expected_nested_visible"]
        for probe in (
            *_WORKSPACE_BOUNDARY_CASES["sapling_cases"],
            *_WORKSPACE_BOUNDARY_CASES["jujutsu_cases"],
        )
    }
    assert set(cases) == set(expected)
    assert all(case["candidate_matches"] for case in cases.values())
    assert {case_id: case["native_visible"] for case_id, case in cases.items()} == expected


@pytest.mark.parametrize(
    "profile", _JJ_046_WORKSPACE_BOUNDARY_PROFILES, ids=lambda name: name.removesuffix(".json")
)
def test_jujutsu_046_workspace_boundaries_match_the_captured_contract(profile: str) -> None:
    """Keep nested Jujutsu workspace behavior checked against the older supported profile."""
    capture = json.loads((_COMPAT_ORACLE_ROOT / "results" / profile).read_text(encoding="utf-8"))
    assert capture["status"] == "captured"
    assert capture["clients"]["jujutsu"].startswith("jj 0.46.0-")
    expected = {
        probe["id"]: probe["expected_nested_visible"]
        for probe in _WORKSPACE_BOUNDARY_CASES["jujutsu_cases"]
    }
    cases = {case["id"]: case for case in capture["cases"]}
    assert set(cases) == set(expected)
    assert all(case["candidate_matches"] for case in cases.values())
    assert {case_id: case["native_visible"] for case_id, case in cases.items()} == expected


@pytest.mark.parametrize(
    ("mode", "expected_ignored"),
    [
        ("sapling-sl", True),
        ("sapling-git", False),
        ("jj-colocated", False),
        ("jj-noncolocated", False),
    ],
)
def test_symlinked_nested_gitignore_matches_captured_scheme_behavior(
    tmp_path: Path, mode: str, expected_ignored: bool
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    external_ignore = tmp_path / "external.gitignore"
    external_ignore.write_text("*.symlink\n", encoding="utf-8")
    nested = root / "nested"
    nested.mkdir()
    try:
        (nested / ".gitignore").symlink_to(external_ignore)
    except OSError as error:
        pytest.skip(f"creating symlinks is not supported: {error}")
    (nested / "probe.symlink").touch()

    if mode == "sapling-sl":
        (root / ".sl").mkdir()
        policy = SaplingIgnorePolicy(nested)
    elif mode == "sapling-git":
        _git_init(root)
        policy = SaplingIgnorePolicy(nested)
    else:
        (root / ".jj").mkdir()
        policy = JujutsuIgnorePolicy(nested)

    assert policy.explain("probe.symlink").ignored is expected_ignored


@pytest.mark.parametrize("selected", [False, True])
def test_jujutsu_can_select_pre_046_symlinked_gitignore_behavior(
    tmp_path: Path, selected: bool
) -> None:
    root = tmp_path / "workspace"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (root / ".jj").mkdir()
    external_ignore = tmp_path / "external.gitignore"
    external_ignore.write_text("*.symlink\n", encoding="utf-8")
    try:
        (nested / ".gitignore").symlink_to(external_ignore)
    except OSError as error:
        pytest.skip(f"creating symlinks is not supported: {error}")
    (nested / "probe.symlink").touch()

    if selected:
        policy = select_policy(
            nested,
            JujutsuPolicyConfig(follow_symlinked_gitignore=True),
        ).policy
    else:
        policy = JujutsuIgnorePolicy(nested, follow_symlinked_gitignore=True)

    assert policy.explain("probe.symlink").ignored


def test_jujutsu_workspace_does_not_inherit_outer_git_info_exclude(tmp_path: Path) -> None:
    outer = tmp_path / "outer"
    outer.mkdir()
    _git_init(outer)
    info = outer / ".git" / "info" / "exclude"
    info.parent.mkdir(parents=True, exist_ok=True)
    info.write_text("*.local\n", encoding="utf-8")
    workspace = outer / "jujutsu"
    (workspace / ".jj").mkdir(parents=True)
    (workspace / "inside.local").touch()

    policy = JujutsuIgnorePolicy(workspace)

    assert policy.workspace_root == workspace
    assert not policy.explain("inside.local").ignored


def test_linked_git_worktree_uses_scheme_specific_info_exclude_directory(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "linked-worktree"
    workspace.mkdir()
    (workspace / ".jj").mkdir()
    home = tmp_path / "home"
    common_dir = tmp_path / "main" / ".git"
    worktree_git_dir = common_dir / "worktrees" / "linked"
    worktree_git_dir.mkdir(parents=True)
    (workspace / ".git").write_text(f"gitdir: {worktree_git_dir}\n", encoding="utf-8")
    (worktree_git_dir / "commondir").write_text("../..\n", encoding="utf-8")
    common_excludes = common_dir / "info" / "exclude"
    common_excludes.parent.mkdir(parents=True)
    common_excludes.write_text("*.commonignore\n", encoding="utf-8")
    worktree_excludes = worktree_git_dir / "info" / "exclude"
    worktree_excludes.parent.mkdir(parents=True)
    worktree_excludes.write_text("*.worktreeignore\n", encoding="utf-8")
    (workspace / "probe.commonignore").touch()
    (workspace / "probe.worktreeignore").touch()
    environment = {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config")}

    git_policy = GitIgnorePolicy(workspace, environment=environment)
    sapling_policy = SaplingIgnorePolicy(workspace, environment=environment)
    jujutsu_policy = JujutsuIgnorePolicy(workspace, environment=environment)

    assert git_policy.explain("probe.commonignore").ignored
    assert not git_policy.explain("probe.worktreeignore").ignored
    assert sapling_policy.explain("probe.commonignore").ignored
    assert not sapling_policy.explain("probe.worktreeignore").ignored
    assert not jujutsu_policy.explain("probe.commonignore").ignored
    assert jujutsu_policy.explain("probe.worktreeignore").ignored


@pytest.mark.parametrize("scheme", ["sapling", "jujutsu"])
def test_compatible_scheme_can_use_resolved_core_excludes_file(tmp_path: Path, scheme: str) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    home = tmp_path / "home"
    xdg_ignore = home / ".config" / "git" / "ignore"
    xdg_ignore.parent.mkdir(parents=True)
    xdg_ignore.write_text("*.xdg\n", encoding="utf-8")
    configured_ignore = tmp_path / "custom-global-ignore"
    configured_ignore.write_text("*.configured\n", encoding="utf-8")
    environment = {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config")}

    if scheme == "sapling":
        _git_init(root)
        config = SaplingPolicyConfig(
            environment=environment,
            global_excludes_file=configured_ignore,
        )
    else:
        (root / ".jj").mkdir()
        config = JujutsuPolicyConfig(
            environment=environment,
            global_excludes_file=configured_ignore,
        )
    (root / "from-xdg.xdg").touch()
    (root / "from-config.configured").touch()
    selection = select_policy(root, config)

    decisions = {
        decision.path.name: decision.ignored
        for decision in selection.policy.explain_many(["from-xdg.xdg", "from-config.configured"])
    }

    assert decisions == {"from-xdg.xdg": False, "from-config.configured": True}


@pytest.mark.skipif(shutil.which("git") is None, reason="Git config discovery needs git")
@pytest.mark.parametrize("scheme", ["sapling", "jujutsu"])
@pytest.mark.parametrize("configured_value", ["~/custom-global-ignore", "", None])
def test_compatible_scheme_can_discover_global_git_config(
    tmp_path: Path, scheme: str, configured_value: str | None
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    home = tmp_path / "home"
    xdg_ignore = home / ".config" / "git" / "ignore"
    xdg_ignore.parent.mkdir(parents=True)
    xdg_ignore.write_text("*.xdg\n", encoding="utf-8")
    custom_ignore = home / "custom-global-ignore"
    custom_ignore.write_text("*.configured\n", encoding="utf-8")
    included_config = home / "included.gitconfig"
    include_value = "" if configured_value is None else f"\texcludesFile = {configured_value}\n"
    included_config.write_text(f"[core]\n{include_value}", encoding="utf-8")
    global_config = home / ".gitconfig"
    global_config.write_text("[include]\n\tpath = included.gitconfig\n", encoding="utf-8")
    environment = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_CONFIG_GLOBAL": str(global_config),
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    if scheme == "sapling":
        _git_init(root)
        config = SaplingPolicyConfig(
            environment=environment,
            read_git_config=True,
            git_executable=shutil.which("git") or "git",
        )
    else:
        (root / ".jj").mkdir()
        config = JujutsuPolicyConfig(
            environment=environment,
            read_git_config=True,
            git_executable=shutil.which("git") or "git",
        )
    (root / "from-xdg.xdg").touch()
    (root / "from-config.configured").touch()

    selection = select_policy(root, config)
    decisions = {
        decision.path.name: decision.ignored
        for decision in selection.policy.explain_many(["from-xdg.xdg", "from-config.configured"])
    }

    expected = {
        "~/custom-global-ignore": {"from-xdg.xdg": False, "from-config.configured": True},
        "": {"from-xdg.xdg": False, "from-config.configured": False},
        None: {"from-xdg.xdg": True, "from-config.configured": False},
    }
    assert decisions == expected[configured_value]


@pytest.mark.skipif(shutil.which("git") is None, reason="Git config discovery needs git")
@pytest.mark.parametrize("scheme", ["sapling", "jujutsu"])
def test_compatible_scheme_honors_alternate_git_config_global_path(
    tmp_path: Path, scheme: str
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    ignore_file = home / "alternate-ignore"
    ignore_file.write_text("*.envglobal\n", encoding="utf-8")
    alternate_config = home / "alternate.gitconfig"
    alternate_config.write_text(
        f"[core]\n\texcludesFile = {ignore_file.as_posix()}\n", encoding="utf-8"
    )
    environment = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_CONFIG_GLOBAL": str(alternate_config),
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    if scheme == "sapling":
        _git_init(root)
        config = SaplingPolicyConfig(environment=environment, read_git_config=True)
    else:
        (root / ".jj").mkdir()
        config = JujutsuPolicyConfig(environment=environment, read_git_config=True)
    (root / "from-env.envglobal").touch()
    (root / "visible.txt").touch()

    selection = select_policy(root, config)
    decisions = {
        decision.path.name: decision.ignored
        for decision in selection.policy.explain_many(["from-env.envglobal", "visible.txt"])
    }

    assert decisions == {"from-env.envglobal": True, "visible.txt": False}


@pytest.mark.skipif(shutil.which("git") is None, reason="Git config discovery needs git")
@pytest.mark.parametrize("scheme", ["sapling", "jujutsu"])
@pytest.mark.parametrize(
    ("global_value", "expected"),
    [
        (None, {"from-xdg.xdg": False, "from-system.system": True, "from-global.global": False}),
        (
            "~/global-ignore",
            {"from-xdg.xdg": False, "from-system.system": False, "from-global.global": True},
        ),
        ("", {"from-xdg.xdg": False, "from-system.system": False, "from-global.global": False}),
    ],
)
def test_compatible_scheme_discovers_system_and_global_precedence(
    tmp_path: Path,
    scheme: str,
    global_value: str | None,
    expected: dict[str, bool],
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    home = tmp_path / "home"
    xdg_ignore = home / ".config" / "git" / "ignore"
    xdg_ignore.parent.mkdir(parents=True)
    xdg_ignore.write_text("*.xdg\n", encoding="utf-8")
    system_ignore = home / "system-ignore"
    system_ignore.write_text("*.system\n", encoding="utf-8")
    global_ignore = home / "global-ignore"
    global_ignore.write_text("*.global\n", encoding="utf-8")
    system_config = tmp_path / "system.gitconfig"
    system_config.write_text(
        f"[core]\n\texcludesFile = {_git_config_path(system_ignore)}\n", encoding="utf-8"
    )
    global_config = tmp_path / "global.gitconfig"
    if global_value is None:
        global_lines = ""
    elif global_value == "":
        global_lines = "[core]\n\texcludesFile =\n"
    else:
        global_lines = f"[core]\n\texcludesFile = {global_value}\n"
    global_config.write_text(global_lines, encoding="utf-8")
    environment = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_CONFIG_SYSTEM": str(system_config),
        "GIT_CONFIG_GLOBAL": str(global_config),
    }
    environment.pop("GIT_CONFIG_NOSYSTEM", None)
    if scheme == "sapling":
        _git_init(root)
        config = SaplingPolicyConfig(environment=environment, read_git_config=True)
    else:
        (root / ".jj").mkdir()
        config = JujutsuPolicyConfig(environment=environment, read_git_config=True)
    for name in ("from-xdg.xdg", "from-system.system", "from-global.global"):
        (root / name).touch()

    selection = select_policy(root, config)
    decisions = {
        decision.path.name: decision.ignored
        for decision in selection.policy.explain_many(
            ["from-xdg.xdg", "from-system.system", "from-global.global"]
        )
    }

    assert decisions == expected


@pytest.mark.skipif(shutil.which("git") is None, reason="Git config discovery needs git")
@pytest.mark.parametrize("mode", ["sapling-git", "jj-colocated", "jj-noncolocated"])
def test_compatible_scheme_discovers_gitdir_conditional_include(tmp_path: Path, mode: str) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    home = tmp_path / "home"
    xdg_ignore = home / ".config" / "git" / "ignore"
    xdg_ignore.parent.mkdir(parents=True)
    xdg_ignore.write_text("*.global\n", encoding="utf-8")
    custom_ignore = home / "custom-ignore"
    custom_ignore.write_text("*.custom\n", encoding="utf-8")
    included_config = home / "included.gitconfig"
    included_config.write_text("[core]\n\texcludesFile = ~/custom-ignore\n", encoding="utf-8")
    global_config = home / ".gitconfig"
    global_config.write_text(
        '[includeIf "gitdir:**/workspace/.git"]\n\tpath = included.gitconfig\n',
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_CONFIG_GLOBAL": str(global_config),
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    if mode == "sapling-git":
        _git_init(root)
        config = SaplingPolicyConfig(environment=environment, read_git_config=True)
        expected = {"conditional.custom": True, "conditional.global": False}
    else:
        (root / ".jj").mkdir()
        if mode == "jj-colocated":
            _git_init(root)
            expected = {"conditional.custom": True, "conditional.global": False}
        else:
            expected = {"conditional.custom": False, "conditional.global": True}
        config = JujutsuPolicyConfig(environment=environment, read_git_config=True)
    (root / "conditional.custom").touch()
    (root / "conditional.global").touch()

    selection = select_policy(root, config)
    decisions = {
        decision.path.name: decision.ignored
        for decision in selection.policy.explain_many(["conditional.custom", "conditional.global"])
    }

    assert decisions == expected


@pytest.mark.skipif(shutil.which("git") is None, reason="Git config discovery needs git")
@pytest.mark.parametrize("mode", ["sapling-git", "jj-colocated", "jj-noncolocated"])
def test_compatible_scheme_uses_caller_gitdir_for_conditional_include(
    tmp_path: Path, mode: str
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    external_git_dir = tmp_path / "external.git"
    subprocess.run(["git", "init", "--bare", "-q", str(external_git_dir)], check=True)
    ignore_file = home / "caller-context-ignore"
    ignore_file.write_text("*.override\n", encoding="utf-8")
    included_config = home / "included.gitconfig"
    included_config.write_text(
        f"[core]\n\texcludesFile = {_git_config_path(ignore_file)}\n", encoding="utf-8"
    )
    global_config = home / ".gitconfig"
    global_config.write_text(
        '[includeIf "gitdir:**/external.git"]\n\tpath = included.gitconfig\n', encoding="utf-8"
    )
    environment = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_CONFIG_GLOBAL": str(global_config),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_DIR": str(external_git_dir),
    }
    if mode == "sapling-git":
        _git_init(root)
        config = SaplingPolicyConfig(environment=environment, read_git_config=True)
    else:
        (root / ".jj").mkdir()
        if mode == "jj-colocated":
            _git_init(root)
        else:
            internal_git_dir = root / ".jj" / "repo" / "store" / "git"
            subprocess.run(["git", "init", "--bare", "-q", str(internal_git_dir)], check=True)
        config = JujutsuPolicyConfig(environment=environment, read_git_config=True)
    (root / "caller.override").touch()

    selection = select_policy(root, config)

    assert selection.policy.explain("caller.override").ignored is True


@pytest.mark.skipif(shutil.which("git") is None, reason="Git config discovery needs git")
@pytest.mark.parametrize("mode", ["sapling-git", "jj-colocated", "jj-noncolocated"])
def test_compatible_scheme_discovers_onbranch_include_with_workspace_context(
    tmp_path: Path, mode: str
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    home = tmp_path / "home"
    xdg_ignore = home / ".config" / "git" / "ignore"
    xdg_ignore.parent.mkdir(parents=True)
    xdg_ignore.write_text("*.global\n", encoding="utf-8")
    branch_ignore = home / "branch-ignore"
    branch_ignore.write_text("*.branch\n", encoding="utf-8")
    included_config = home / "included.gitconfig"
    included_config.write_text(
        f"[core]\n\texcludesFile = {_git_config_path(branch_ignore)}\n", encoding="utf-8"
    )
    global_config = home / ".gitconfig"
    global_config.write_text(
        '[includeIf "onbranch:main"]\n\tpath = included.gitconfig\n', encoding="utf-8"
    )
    environment = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_CONFIG_GLOBAL": str(global_config),
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    if mode == "sapling-git":
        _git_init(root)
        _set_git_branch(root / ".git", "main")
        config = SaplingPolicyConfig(environment=environment, read_git_config=True)
    elif mode == "jj-colocated":
        (root / ".jj").mkdir()
        _git_init(root)
        _set_git_branch(root / ".git", "main")
        config = JujutsuPolicyConfig(environment=environment, read_git_config=True)
    else:
        (root / ".jj").mkdir()
        git_dir = root / ".jj" / "repo" / "store" / "git"
        subprocess.run(["git", "init", "--bare", "-q", str(git_dir)], check=True)
        _set_git_branch(git_dir, "main")
        config = JujutsuPolicyConfig(environment=environment, read_git_config=True)
    (root / "conditional.branch").touch()
    (root / "conditional.global").touch()

    selection = select_policy(root, config)
    decisions = {
        decision.path.name: decision.ignored
        for decision in selection.policy.explain_many(["conditional.branch", "conditional.global"])
    }

    assert decisions == {"conditional.branch": True, "conditional.global": False}

    alternate_git_dir = tmp_path / "alternate.git"
    subprocess.run(["git", "init", "--bare", "-q", str(alternate_git_dir)], check=True)
    _set_git_branch(alternate_git_dir, "other")
    caller_context = {**environment, "GIT_DIR": str(alternate_git_dir)}
    alternate_selection = select_policy(
        root,
        SaplingPolicyConfig(environment=caller_context, read_git_config=True)
        if mode == "sapling-git"
        else JujutsuPolicyConfig(environment=caller_context, read_git_config=True),
    )
    alternate_decision = alternate_selection.policy.explain("conditional.branch")
    assert alternate_decision.ignored is False


@pytest.mark.skipif(shutil.which("git") is None, reason="Git config discovery needs git")
@pytest.mark.parametrize("mode", ["sapling-git", "jj-colocated", "jj-noncolocated"])
@pytest.mark.parametrize(
    ("remote_url", "expected_ignored"),
    [
        ("https://example.invalid/acme/project.git", True),
        ("https://other.invalid/team/project.git", False),
    ],
)
def test_compatible_scheme_discovers_remote_url_conditional_include(
    tmp_path: Path, mode: str, remote_url: str, expected_ignored: bool
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    home = tmp_path / "home"
    xdg_ignore = home / ".config" / "git" / "ignore"
    xdg_ignore.parent.mkdir(parents=True)
    xdg_ignore.write_text("*.global\n", encoding="utf-8")
    remote_ignore = home / "remote-ignore"
    remote_ignore.write_text("*.remote\n", encoding="utf-8")
    included_config = home / "included.gitconfig"
    included_config.write_text(
        f"[core]\n\texcludesFile = {_git_config_path(remote_ignore)}\n", encoding="utf-8"
    )
    global_config = home / ".gitconfig"
    global_config.write_text(
        '[includeIf "hasconfig:remote.*.url:https://example.invalid/acme/**"]\n'
        "\tpath = included.gitconfig\n",
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_CONFIG_GLOBAL": str(global_config),
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    if mode == "sapling-git":
        _git_init(root)
        git_dir = root / ".git"
        config = SaplingPolicyConfig(environment=environment, read_git_config=True)
    elif mode == "jj-colocated":
        (root / ".jj").mkdir()
        _git_init(root)
        git_dir = root / ".git"
        config = JujutsuPolicyConfig(environment=environment, read_git_config=True)
    else:
        (root / ".jj").mkdir()
        git_dir = root / ".jj" / "repo" / "store" / "git"
        subprocess.run(["git", "init", "--bare", "-q", str(git_dir)], check=True)
        config = JujutsuPolicyConfig(environment=environment, read_git_config=True)
    _set_git_remote(git_dir, remote_url)
    (root / "conditional.remote").touch()

    selection = select_policy(root, config)
    decision = selection.policy.explain("conditional.remote")

    assert decision.ignored is expected_ignored

    repository_ignore = home / "repository-ignore"
    repository_ignore.write_text("*.repository\n", encoding="utf-8")
    _set_git_config(git_dir, "core.excludesFile", str(repository_ignore))
    (root / "configured.repository").touch()
    repository_selection = select_policy(root, config)
    assert repository_selection.policy.explain("configured.repository").ignored is True


@pytest.mark.skipif(shutil.which("git") is None, reason="Git config discovery needs git")
@pytest.mark.parametrize(
    ("mode", "expected_ignored"),
    [
        ("sapling-git", True),
        ("sapling-sl", False),
        ("jj-colocated", True),
        ("jj-noncolocated", False),
    ],
)
def test_compatible_scheme_discovers_case_insensitive_gitdir_include(
    tmp_path: Path, mode: str, expected_ignored: bool
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    custom_ignore = home / "case-insensitive-ignore"
    custom_ignore.write_text("*.casefold\n", encoding="utf-8")
    (home / "included.gitconfig").write_text(
        f"[core]\n\texcludesFile = {_git_config_path(custom_ignore)}\n", encoding="utf-8"
    )
    global_config = home / ".gitconfig"
    global_config.write_text(
        '[includeIf "gitdir/i:**/WORKSPACE/.GIT"]\n\tpath = included.gitconfig\n',
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_CONFIG_GLOBAL": str(global_config),
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    if mode == "sapling-git":
        _git_init(root)
        config = SaplingPolicyConfig(environment=environment, read_git_config=True)
    elif mode == "sapling-sl":
        (root / ".sl").mkdir()
        config = SaplingPolicyConfig(environment=environment, read_git_config=True)
    elif mode == "jj-colocated":
        (root / ".jj").mkdir()
        _git_init(root)
        config = JujutsuPolicyConfig(environment=environment, read_git_config=True)
    else:
        (root / ".jj").mkdir()
        git_dir = root / ".jj" / "repo" / "store" / "git"
        subprocess.run(["git", "init", "--bare", "-q", str(git_dir)], check=True)
        config = JujutsuPolicyConfig(environment=environment, read_git_config=True)

    (root / "conditional.casefold").touch()
    selection = select_policy(root, config)
    decision = selection.policy.explain("conditional.casefold")
    ignored_by_walker = [
        path.name
        for path in IgnoreWalker(root, policy=selection.policy).iter_files(selection="ignored")
    ]

    assert decision.ignored is expected_ignored
    assert ("conditional.casefold" in ignored_by_walker) is expected_ignored


@pytest.mark.skipif(
    not _git_supports_worktree_conditional_includes(),
    reason="Git worktree conditional includes require Git 2.56 or newer",
)
@pytest.mark.parametrize(
    ("mode", "expected_ignored", "condition", "suffix"),
    [
        ("sapling-git", True, "worktree", ""),
        ("sapling-sl", False, "worktree", ""),
        ("jj-colocated", True, "worktree", ""),
        ("jj-noncolocated", False, "worktree", ""),
        ("sapling-git", True, "worktree/i", "i"),
        ("sapling-sl", False, "worktree/i", "i"),
        ("jj-colocated", True, "worktree/i", "i"),
        ("jj-noncolocated", False, "worktree/i", "i"),
    ],
)
def test_compatible_scheme_resolves_worktree_conditionals_with_git_256(
    tmp_path: Path, mode: str, expected_ignored: bool, condition: str, suffix: str
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    custom_ignore = home / f"worktree{suffix}-ignore"
    custom_ignore.write_text(f"*.worktree{suffix}\n", encoding="utf-8")
    included_config = home / f"worktree{suffix}.gitconfig"
    included_config.write_text(
        f"[core]\n\texcludesFile = {_git_config_path(custom_ignore)}\n", encoding="utf-8"
    )
    global_config = home / ".gitconfig"
    path_pattern = root.resolve().as_posix()
    if condition.endswith("/i"):
        path_pattern = path_pattern.upper()
    global_config.write_text(
        f'[includeIf "{condition}:{path_pattern}"]\n\tpath = {included_config.name}\n',
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_CONFIG_GLOBAL": str(global_config),
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    if mode == "sapling-git":
        _git_init(root)
        config = SaplingPolicyConfig(environment=environment, read_git_config=True)
    elif mode == "sapling-sl":
        (root / ".sl").mkdir()
        config = SaplingPolicyConfig(environment=environment, read_git_config=True)
    elif mode == "jj-colocated":
        (root / ".jj").mkdir()
        _git_init(root)
        config = JujutsuPolicyConfig(environment=environment, read_git_config=True)
    else:
        (root / ".jj").mkdir()
        git_dir = root / ".jj" / "repo" / "store" / "git"
        subprocess.run(["git", "init", "--bare", "-q", str(git_dir)], check=True)
        config = JujutsuPolicyConfig(environment=environment, read_git_config=True)

    target = root / f"conditional.worktree{suffix}"
    target.touch()
    selection = select_policy(root, config)
    decision = selection.policy.explain(target.name)

    assert decision.ignored is expected_ignored


def test_compatible_scheme_config_discovery_errors_if_git_is_missing(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / ".jj").mkdir()

    with pytest.raises(GitIgnoreError, match=r"unable to read Git core.excludesFile"):
        select_policy(
            root,
            JujutsuPolicyConfig(read_git_config=True, git_executable="missing-git-config-client"),
        )


@pytest.mark.parametrize("mode", sorted(_SOURCE_EXPECTATIONS))
def test_compatible_schemes_match_captured_negation_and_path_patterns(
    tmp_path: Path, mode: str
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    environment = {"HOME": str(tmp_path / "home"), "XDG_CONFIG_HOME": str(tmp_path / "config")}
    if mode in {"sapling-git", "jj-colocated"}:
        _git_init(root)
    elif mode == "sapling-sl":
        (root / ".sl").mkdir()
    else:
        (root / ".jj").mkdir()
    if mode.startswith("jj-"):
        (root / ".jj").mkdir(exist_ok=True)
    (root / ".gitignore").write_text(_PATTERN_RULES, encoding="utf-8")
    for relative_path in _PATTERN_FILES:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    if mode.startswith("sapling-"):
        policy = SaplingIgnorePolicy(root, environment=environment)
    else:
        policy = JujutsuIgnorePolicy(root, environment=environment)

    decisions = {
        decision.path.relative_to(root).as_posix(): decision
        for decision in policy.explain_many(_PATTERN_FILES)
    }
    assert {path for path, decision in decisions.items() if decision.ignored} == _PATTERN_IGNORED
    assert {decision.scheme for decision in decisions.values()} == {
        "sapling" if mode.startswith("sapling-") else "jujutsu"
    }

    walker = IgnoreWalker(root, policy=policy)
    walked_ignored = {
        path.relative_to(root).as_posix()
        for path in walker.iter_files(selection="ignored")
        if path.relative_to(root).as_posix() in _PATTERN_FILES
    }
    assert walked_ignored == _PATTERN_IGNORED
    walked_included = {
        path.relative_to(root).as_posix()
        for path in walker.iter_files(selection="included")
        if path.relative_to(root).as_posix() in _PATTERN_FILES
    }
    assert walked_included == set(_PATTERN_FILES) - _PATTERN_IGNORED


def test_jujutsu_046_debian_capture_covers_the_supported_policy_subset() -> None:
    """Keep the 0.46.0 symlink-boundary profile checked against captured policy fixtures."""
    assert _JJ_046_CAPTURE["status"] == "captured"
    assert _JJ_046_CAPTURE["clients"]["jujutsu"].startswith("jj 0.46.0-")
    assert _JJ_046_CAPTURE["platform"].startswith("Linux-")

    cases = {case["id"]: case for case in _JJ_046_CAPTURE["cases"]}
    assert set(cases) == {"jj.colocated", "jj.noncolocated"}
    for case_id, source_expectation in (
        ("jj.colocated", _SOURCE_EXPECTATIONS["jj-colocated"]),
        ("jj.noncolocated", _SOURCE_EXPECTATIONS["jj-noncolocated"]),
    ):
        case = cases[case_id]
        assert case["candidate_matches"]
        assert case["source_discovery"]["candidate_matches"]
        assert case["source_discovery"]["ignored"] == source_expectation
        assert case["pattern_discovery"]["candidate_matches"]
        assert set(case["pattern_discovery"]["ignored"]) == _PATTERN_IGNORED
        assert case["symlinked_gitignore"]["candidate_matches"]
        assert all(
            case[key]["candidate_matches"]
            for key in (
                "configured_global",
                "configured_system",
                "conditional_global",
                "conditional_gitdir_i",
                "conditional_worktree",
                "conditional_worktree_i",
                "conditional_onbranch",
                "conditional_remote_url",
                "conditional_gitdir_override",
                "environment_global",
                "configured_repository",
            )
        )


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


def _set_git_branch(git_dir: Path, branch: str) -> None:
    result = subprocess.run(
        ["git", f"--git-dir={git_dir}", "symbolic-ref", "HEAD", f"refs/heads/{branch}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr)


def _set_git_remote(git_dir: Path, remote_url: str) -> None:
    _set_git_config(git_dir, "remote.origin.url", remote_url)


def _set_git_config(git_dir: Path, key: str, value: str) -> None:
    result = subprocess.run(
        ["git", f"--git-dir={git_dir}", "config", key, value],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
