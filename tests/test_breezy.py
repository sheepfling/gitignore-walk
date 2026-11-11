"""Breezy policy rules and exception-aware traversal behavior."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from gitignore_walk import (
    BreezyIgnoreError,
    BreezyIgnorePolicy,
    BreezyPolicyConfig,
    IgnoreWalker,
    select_policy,
)
from gitignore_walk._schemes.breezy import policy as breezy_policy_module
from gitignore_walk._schemes.breezy.policy import _compile_rule, _glob_to_regex

ORACLE_ROOT = Path(__file__).parent / "oracles" / "breezy"
ORACLE_CASES: list[dict[str, Any]] = json.loads(
    (ORACLE_ROOT / "cases.json").read_text(encoding="utf-8")
)["cases"]
DEFAULT_RULES: tuple[str, ...] = tuple(
    json.loads(
        (ORACLE_ROOT / "results" / "brz-3.3.24-macos-arm64.json").read_text(encoding="utf-8")
    )["default_rules"]["patterns"]
)
_BREEZY_API_READY = False


@pytest.fixture
def breezy_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a Breezy tree while avoiding a local Breezy executable dependency."""
    monkeypatch.setattr(BreezyIgnorePolicy, "_load_default_patterns", lambda self: ())
    (tmp_path / ".bzr").mkdir()
    return tmp_path


@pytest.mark.skipif(os.name != "nt", reason="Breezy's default config location is platform-specific")
def test_windows_appdata_global_ignore_path(breezy_root: Path, tmp_path: Path) -> None:
    appdata = tmp_path / "appdata"
    global_ignore = appdata / "Breezy" / "ignore"
    global_ignore.parent.mkdir(parents=True)
    global_ignore.write_text("*.appdata-probe\n", encoding="utf-8")
    policy = BreezyIgnorePolicy(breezy_root, environment={"APPDATA": str(appdata)})

    decision = policy.explain("cache.appdata-probe")

    assert decision.ignored
    assert decision.source == str(global_ignore)


def test_default_rule_query_uses_isolated_brz_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep Breezy's default-rule query independent of the caller's config directories."""
    root = tmp_path / "checkout"
    (root / ".bzr").mkdir(parents=True)
    appdata = tmp_path / "appdata"
    captured: dict[str, str] = {}

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        capture_output: bool,
        timeout: float,
        check: bool,
    ) -> subprocess.CompletedProcess[bytes]:
        captured.update(env)
        return subprocess.CompletedProcess(command, 0, stdout=b"*.pyc\n", stderr=b"")

    monkeypatch.setattr(breezy_policy_module.subprocess, "run", fake_run)
    policy = BreezyIgnorePolicy(
        root,
        environment={"APPDATA": str(appdata), "HOME": str(tmp_path / "caller-home")},
    )

    assert policy._default_patterns == ("*.pyc",)
    assert Path(captured["BRZ_HOME"]) == Path(captured["HOME"]) / "brz-home"
    assert Path(captured["BRZ_HOME"]) != appdata
    assert captured["BRZ_PLUGIN_PATH"] == ""


@pytest.mark.parametrize("topdown", [True, False], ids=["topdown", "bottomup"])
def test_breezy_walk_stops_at_nested_tree(tmp_path: Path, topdown: bool) -> None:
    brz = shutil.which("brz")
    if brz is None:
        pytest.skip("Breezy is not installed")
    parent = tmp_path / "parent"
    child = parent / "nested"
    parent.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    environment = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "BRZ_HOME": str(home / "brz-home"),
        "BRZ_PLUGIN_PATH": "",
        "BRZ_LOG": os.devnull,
        "PATH": str(Path(brz).parent),
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
    }

    def run(*arguments: str, cwd: Path = parent) -> subprocess.CompletedProcess[bytes]:
        result = subprocess.run(
            [brz, *arguments],
            cwd=cwd,
            env=environment,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        return result

    run("init", "--no-plugins", str(parent))
    (parent / "outer.txt").write_text("outer\n", encoding="utf-8")
    run("init", "--no-plugins", str(child))
    (child / "inner.txt").write_text("inner\n", encoding="utf-8")

    native_status = run("status", "--no-plugins", "--short")
    policy = BreezyIgnorePolicy(
        parent, brz_executable=brz, environment=environment, global_ignore_file=home / "none"
    )
    walked_paths = {
        path.relative_to(parent).as_posix()
        for path in IgnoreWalker(parent, policy=policy).iter_files(topdown=topdown)
    }

    assert b"nested+" in native_status.stdout
    assert b"inner.txt" not in native_status.stdout
    assert walked_paths == {"outer.txt"}


def test_globstar_matches_zero_or_more_directory_segments() -> None:
    import re

    expression = re.compile(_glob_to_regex("cache/**/keep.tmp"))
    assert expression.fullmatch("cache/keep.tmp")
    assert expression.fullmatch("cache/a/keep.tmp")
    assert expression.fullmatch("cache/a/b/keep.tmp")
    assert not expression.fullmatch("other/keep.tmp")


def test_breezy_policy_opens_ignored_directory_for_declared_exception(
    breezy_root: Path,
) -> None:
    cache = breezy_root / "cache"
    cache.mkdir()
    (cache / "drop.tmp").touch()
    (breezy_root / ".bzrignore").write_text("cache\n!cache/keep.tmp\n", encoding="utf-8")
    policy = BreezyIgnorePolicy(breezy_root)

    directory = policy.explain("cache")
    dropped = policy.explain("cache/drop.tmp")
    kept = policy.explain("cache/keep.tmp")

    assert directory.ignored is True
    assert dropped.ignored is False
    assert kept.ignored is False
    assert policy.can_prune_ignored_directory(cache, directory) is False


@pytest.mark.parametrize("topdown", [True, False])
def test_breezy_root_anchored_nested_exception_opens_ignored_directory(
    breezy_root: Path, topdown: bool
) -> None:
    cache = breezy_root / "cache"
    cache.mkdir()
    kept = cache / "keep.tmp"
    dropped = cache / "drop.tmp"
    kept.touch()
    dropped.touch()
    (breezy_root / ".bzrignore").write_text(
        "cache\ncache/**\n!./cache/keep.tmp\n", encoding="utf-8"
    )
    policy = BreezyIgnorePolicy(breezy_root)
    walker = IgnoreWalker(breezy_root, policy=policy)

    assert policy.explain("cache/keep.tmp").ignored is False
    assert policy.explain("cache/drop.tmp").ignored is True
    assert kept in set(walker.iter_files(topdown=topdown))
    assert dropped not in set(walker.iter_files(topdown=topdown))
    assert kept not in set(walker.iter_files(topdown=topdown, selection="ignored"))
    assert dropped in set(walker.iter_files(topdown=topdown, selection="ignored"))


def test_breezy_exception_can_open_directory_when_target_does_not_exist(
    breezy_root: Path,
) -> None:
    (breezy_root / ".bzrignore").write_text("cache\n!cache/keep.tmp\n", encoding="utf-8")
    policy = BreezyIgnorePolicy(breezy_root)

    assert policy.explain("cache/drop.tmp").ignored is False


def test_breezy_strong_ignore_overrides_exception_and_can_prune(breezy_root: Path) -> None:
    cache = breezy_root / "cache"
    (cache / "private").mkdir(parents=True)
    hidden = cache / "private" / "secret.tmp"
    hidden.touch()
    (breezy_root / ".bzrignore").write_text(
        "cache\n!cache/keep.tmp\n!!cache/private\n", encoding="utf-8"
    )
    policy = BreezyIgnorePolicy(breezy_root)

    private_path = cache / "private"
    private = policy.explain(private_path)

    assert private.ignored is True
    assert policy.can_prune_ignored_directory(private_path, private) is True
    assert hidden not in set(IgnoreWalker(breezy_root, policy=policy).iter_files())


@pytest.mark.parametrize("topdown", [True, False])
def test_breezy_walker_preserves_exception_siblings_and_selects_strong_exclusions(
    breezy_root: Path, topdown: bool
) -> None:
    cache = breezy_root / "cache"
    (cache / "private").mkdir(parents=True)
    dropped = cache / "drop.tmp"
    kept = cache / "keep.tmp"
    hidden = cache / "private" / "secret.tmp"
    dropped.touch()
    kept.touch()
    hidden.touch()
    (breezy_root / ".bzrignore").write_text(
        "cache\n!cache/keep.tmp\n!!cache/private/**\n", encoding="utf-8"
    )
    policy = BreezyIgnorePolicy(breezy_root)
    walker = IgnoreWalker(breezy_root, policy=policy)

    included = set(walker.iter_files(topdown=topdown))
    ignored = set(walker.iter_files(topdown=topdown, selection="ignored"))

    assert {dropped, kept} <= included
    assert hidden not in included
    assert hidden in ignored


@pytest.mark.parametrize("topdown", [True, False])
def test_breezy_deep_exception_keeps_ignored_parent_traversable(
    breezy_root: Path, topdown: bool
) -> None:
    cache = breezy_root / "cache"
    deep = cache / "deep"
    deep.mkdir(parents=True)
    kept = deep / "keep.tmp"
    deep_sibling = deep / "drop.tmp"
    cache_sibling = cache / "drop.tmp"
    kept.touch()
    deep_sibling.touch()
    cache_sibling.touch()
    (breezy_root / ".bzrignore").write_text("cache\n!cache/deep/keep.tmp\n", encoding="utf-8")
    policy = BreezyIgnorePolicy(breezy_root)
    walker = IgnoreWalker(breezy_root, policy=policy)

    cache_decision = policy.explain(cache)
    assert cache_decision.ignored
    assert policy.can_prune_ignored_directory(cache, cache_decision) is False
    assert not policy.explain(deep).ignored
    assert policy.explain("cache/deep/keep.tmp").ignored is False
    assert policy.explain("cache/deep/drop.tmp").ignored is False
    included = set(walker.iter_files(topdown=topdown))
    ignored = set(walker.iter_files(topdown=topdown, selection="ignored"))
    assert {kept, deep_sibling, cache_sibling} <= included
    assert not {kept, deep_sibling, cache_sibling} & ignored


def test_breezy_named_capture_is_normalized_with_diagnostic() -> None:
    rule = _compile_rule("RE:(?P<name>cache)/.*", source=".bzrignore", line=1)
    assert rule is not None
    assert rule.matches("cache/file")
    assert rule.diagnostic is not None
    assert rule.diagnostic.code == "named-regex-capture-normalized"


def test_breezy_regex_matches_complete_path_and_normalizes_strong_source() -> None:
    full_path = _compile_rule("RE:cache", source=".bzrignore", line=1)
    strong_escaped = _compile_rule(r"!!RE:^cache/.*\.tmp$", source=".bzrignore", line=2)

    assert full_path is not None
    assert full_path.matches("cache")
    assert not full_path.matches("cache.tmp")
    assert strong_escaped is not None
    assert strong_escaped.priority == "strong"
    assert not strong_escaped.matches("cache/drop.tmp")


def test_breezy_rejects_global_inline_regex_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(BreezyIgnorePolicy, "_load_default_patterns", lambda self: ())
    (tmp_path / ".bzr").mkdir()
    (tmp_path / ".bzrignore").write_text("RE:(?i)foo\n", encoding="utf-8")

    with pytest.raises(BreezyIgnoreError, match="Invalid Breezy pattern"):
        BreezyIgnorePolicy(tmp_path)


def test_breezy_allows_escaped_inline_flag_text() -> None:
    rule = _compile_rule(r"RE:\(\?i\)foo", source=".bzrignore", line=1)

    assert rule is not None
    assert rule.matches("(?i)foo")


def test_breezy_backreference_to_wrapper_group_is_rejected() -> None:
    with pytest.raises(BreezyIgnoreError, match="Invalid Breezy pattern"):
        _compile_rule(r"RE:^cache/(src)-\1\.tmp$", source=".bzrignore", line=1)


def test_breezy_selector_uses_discriminated_selection(breezy_root: Path) -> None:
    selection = select_policy(breezy_root, BreezyPolicyConfig())

    assert selection.mode == "breezy"
    assert selection.backend == "breezy-native-defaults"
    assert isinstance(selection.policy, BreezyIgnorePolicy)


@pytest.mark.skipif(shutil.which("brz") is None, reason="Breezy is not installed")
@pytest.mark.parametrize("topdown", [True, False], ids=["topdown", "bottomup"])
def test_membership_aware_policy_matches_native_versioned_listing(
    tmp_path: Path, topdown: bool
) -> None:
    """Keep native Breezy membership separate from ignore rules and missing paths."""
    brz = shutil.which("brz")
    assert brz is not None
    root = tmp_path / "checkout"
    root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "BRZ_HOME": str(home / "brz-home"),
            "BRZ_PLUGIN_PATH": "",
            "BRZ_LOG": os.devnull,
            "BRZ_EMAIL": "gitignore-walk test <test@example.invalid>",
            "PATH": str(Path(brz).parent),
            "LC_ALL": "C",
            "LANG": "C",
            "TZ": "UTC",
        }
    )

    def run(*arguments: str) -> subprocess.CompletedProcess[bytes]:
        result = subprocess.run(
            [brz, *arguments],
            cwd=root,
            env=environment,
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        return result

    def add(*paths: str) -> None:
        if os.name != "nt":
            run("add", "--no-plugins", *paths)
            return

        import breezy
        from breezy import plugin
        from breezy.workingtree import WorkingTree

        global _BREEZY_API_READY
        with patch.dict(os.environ, environment, clear=True):
            if not _BREEZY_API_READY:
                breezy.initialize()
                plugin.load_plugins()
                _BREEZY_API_READY = True
            tree = WorkingTree.open(str(root))
            with tree.lock_write():
                tree.add(list(paths))

    run("init", "--no-plugins", str(root))
    for name in ("tracked.txt", "tracked.tmp", "missing.txt", "ignored.tmp"):
        (root / name).write_text(f"{name}\n", encoding="utf-8")
    tracked_in_ignored_directory = root / "cache" / "tracked.txt"
    tracked_in_ignored_directory.parent.mkdir()
    add("cache")
    tracked_in_ignored_directory.write_text("tracked below ignored directory\n", encoding="utf-8")
    add("tracked.txt", "tracked.tmp", "missing.txt", "ignored.tmp", "cache/tracked.txt")
    run("commit", "--no-plugins", "-m", "add initial files")
    (root / ".bzrignore").write_text("*.tmp\ncache\ncache/**\n", encoding="utf-8")
    add(".bzrignore")
    run("commit", "--no-plugins", "-m", "add ignore rule")
    (root / "unknown.txt").write_text("unknown\n", encoding="utf-8")
    (root / "real-dir").mkdir()
    (root / "real-dir" / "child.txt").write_text("directory target\n", encoding="utf-8")
    try:
        (root / "linked.txt").symlink_to("unknown.txt")
    except OSError:
        symlink_created = False
    else:
        symlink_created = True
    try:
        (root / "linked-dir").symlink_to("real-dir", target_is_directory=True)
    except OSError:
        directory_symlink_created = False
    else:
        directory_symlink_created = True
    linked_entries = [
        name
        for name, created in (
            ("linked.txt", symlink_created),
            ("linked-dir", directory_symlink_created),
        )
        if created
    ]
    if linked_entries:
        add(*linked_entries)
        run("commit", "--no-plugins", "-m", "track symlinks")
    (root / "ignored-unversioned.tmp").write_text("ignored and unknown\n", encoding="utf-8")
    (root / "missing.txt").unlink()

    native = run("ls", "--no-plugins", "--from-root", "--recursive", "--versioned", "--null").stdout
    native_paths = {os.fsdecode(record) for record in native.split(b"\0") if record}
    assert "tracked.txt" in native_paths
    assert "cache/tracked.txt" in native_paths
    assert "ignored.tmp" in native_paths
    if symlink_created:
        assert "linked.txt" in native_paths
    if directory_symlink_created:
        assert "linked-dir" in native_paths
    assert "missing.txt" not in native_paths

    selection = select_policy(
        root,
        BreezyPolicyConfig(
            brz_executable=brz,
            environment=environment,
            global_ignore_file=home / "missing-global-ignore",
            membership_aware=True,
        ),
    )
    assert isinstance(selection.policy, BreezyIgnorePolicy)
    policy = selection.policy
    query_targets = [
        "tracked.txt",
        "cache/tracked.txt",
        "ignored.tmp",
        "unknown.txt",
        "linked.txt",
        "linked-dir",
        "ignored-unversioned.tmp",
        "missing.txt",
    ]
    decisions = dict(zip(query_targets, policy.explain_many(query_targets), strict=True))
    assert decisions["tracked.txt"].membership == "versioned"
    assert decisions["cache/tracked.txt"].membership == "versioned"
    assert decisions["cache/tracked.txt"].ignored
    assert decisions["ignored.tmp"].membership == "versioned"
    assert decisions["ignored.tmp"].ignored
    assert decisions["unknown.txt"].membership == "unversioned"
    if symlink_created:
        assert decisions["linked.txt"].membership == "versioned"
        assert policy.trace("linked.txt").decision.membership == "versioned"
    if directory_symlink_created:
        assert decisions["linked-dir"].membership == "versioned"
    assert decisions["ignored-unversioned.tmp"].membership == "unversioned"
    assert decisions["ignored-unversioned.tmp"].ignored
    assert decisions["missing.txt"].membership is None

    walked = {
        path.relative_to(root).as_posix()
        for path in IgnoreWalker(root, policy=policy).iter_files(topdown=topdown)
    }
    assert "ignored.tmp" in walked
    assert "cache/tracked.txt" in walked
    assert "ignored-unversioned.tmp" not in walked


@pytest.mark.parametrize(
    "case",
    [case for case in ORACLE_CASES if isinstance(case["expected_candidate"], bool)],
    ids=lambda case: case["id"],
)
def test_breezy_policy_matches_captured_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: dict[str, Any]
) -> None:
    """Compare local policy decisions to the versioned Breezy candidate corpus."""
    monkeypatch.setattr(BreezyIgnorePolicy, "_load_default_patterns", lambda self: DEFAULT_RULES)
    root = tmp_path / "checkout"
    root.mkdir()
    (root / ".bzr").mkdir()
    setup = case["setup"]
    for relative, contents in setup.get("files", {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    if setup.get("patterns") is not None:
        (root / ".bzrignore").write_text("\n".join(setup["patterns"]) + "\n", encoding="utf-8")
    brz_home = tmp_path / "brz-home"
    global_file = (
        brz_home / "breezy" / "ignore"
        if setup.get("brz_home")
        else tmp_path / "config" / "breezy" / "ignore"
    )
    if "global_ignore_file_content" in setup or "brz_home_ignore_file_content" in setup:
        global_file.parent.mkdir(parents=True)
        global_content = setup.get(
            "global_ignore_file_content", setup.get("brz_home_ignore_file_content", "")
        )
        global_file.write_text(global_content, encoding="utf-8")
    query = case["query"]
    target = root / query
    if case["id"] != "brz.parent-exception-target-absent":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch(exist_ok=True)

    policy = (
        BreezyIgnorePolicy(root, environment={"BRZ_HOME": str(brz_home)})
        if setup.get("brz_home")
        else BreezyIgnorePolicy(root, global_ignore_file=global_file)
    )

    assert policy.explain(query).ignored is case["expected_candidate"]
    if "expected_winning_pattern" in case:
        assert policy.trace(query).decision.pattern == case["expected_winning_pattern"]
