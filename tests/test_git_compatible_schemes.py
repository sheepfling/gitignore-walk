"""Read-only Sapling and Jujutsu Git-ignore compatibility policies."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from gitignore_walk import (
    GitIgnoreError,
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
    system_config.write_text(f"[core]\n\texcludesFile = {system_ignore}\n", encoding="utf-8")
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
    included_config.write_text(f"[core]\n\texcludesFile = {branch_ignore}\n", encoding="utf-8")
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
    included_config.write_text(f"[core]\n\texcludesFile = {remote_ignore}\n", encoding="utf-8")
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
