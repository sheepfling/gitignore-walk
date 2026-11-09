"""Breezy policy rules and exception-aware traversal behavior."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from gitignore_walk import (
    BreezyIgnoreError,
    BreezyIgnorePolicy,
    BreezyPolicyConfig,
    IgnoreWalker,
    select_policy,
)
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


@pytest.fixture
def breezy_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a Breezy tree while avoiding a local Breezy executable dependency."""
    monkeypatch.setattr(BreezyIgnorePolicy, "_load_default_patterns", lambda self: ())
    (tmp_path / ".bzr").mkdir()
    return tmp_path


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


def test_breezy_named_capture_is_normalized_with_diagnostic() -> None:
    rule = _compile_rule("RE:(?P<name>cache)/.*", source=".bzrignore", line=1)
    assert rule is not None
    assert rule.matches("cache/file")
    assert rule.diagnostic is not None
    assert rule.diagnostic.code == "named-regex-capture-normalized"


def test_breezy_rejects_global_inline_regex_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(BreezyIgnorePolicy, "_load_default_patterns", lambda self: ())
    (tmp_path / ".bzr").mkdir()
    (tmp_path / ".bzrignore").write_text("RE:(?i)foo\n", encoding="utf-8")

    with pytest.raises(BreezyIgnoreError, match="Invalid Breezy pattern"):
        BreezyIgnorePolicy(tmp_path)


def test_breezy_selector_uses_discriminated_selection(breezy_root: Path) -> None:
    selection = select_policy(breezy_root, BreezyPolicyConfig())

    assert selection.mode == "breezy"
    assert selection.backend == "breezy-native-defaults"
    assert isinstance(selection.policy, BreezyIgnorePolicy)


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
