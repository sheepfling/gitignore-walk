"""Integrity checks for captured Breezy native observations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from gitignore_walk import BreezyIgnorePolicy, IgnoreWalker

ORACLE_ROOT = Path(__file__).parent / "oracles" / "breezy"
CASES = json.loads((ORACLE_ROOT / "cases.json").read_text(encoding="utf-8"))["cases"]
CAPTURE_FILES = (
    "brz-3.3.24-macos-arm64.json",
    "brz-3.3.24-linux-aarch64-py312.json",
    "brz-3.3.24-linux-x86_64-py312.json",
    "brz-3.3.24-windows-x86_64-py312.json",
)
CAPTURES: dict[str, dict[str, Any]] = {
    name: json.loads((ORACLE_ROOT / "results" / name).read_text(encoding="utf-8"))
    for name in CAPTURE_FILES
}


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_breezy_captures_match_versioned_candidates(profile: str, case: dict[str, Any]) -> None:
    capture = CAPTURES[profile]
    observation = next(item for item in capture["cases"] if item["id"] == case["id"])

    assert capture["status"] == "captured"
    expected = case["expected_candidate"]
    if isinstance(expected, bool):
        assert observation["candidate_matches"] is True
        assert observation["observed_ignored"] is expected
    else:
        assert observation["candidate_matches"] is None


@pytest.mark.parametrize("profile", CAPTURE_FILES)
def test_breezy_capture_commands_succeed_in_isolated_configuration(profile: str) -> None:
    capture = CAPTURES[profile]

    assert capture["default_rules"]["exit_code"] == 0
    assert capture["default_rules"]["isolated_configuration"] is True
    assert all(case["isolated_configuration"] for case in capture["cases"])
    assert all(case["init_exit_code"] == 0 for case in capture["cases"])
    assert all(
        case["ignored_exit_code"]
        == (
            3
            if case["id"] in {"brz.regex-invalid-pattern", "brz.regex-global-inline-flag-rejected"}
            else 0
        )
        for case in capture["cases"]
    )
    assert all(
        case["status_exit_code"]
        == (
            3
            if case["id"] in {"brz.regex-invalid-pattern", "brz.regex-global-inline-flag-rejected"}
            else 0
        )
        for case in capture["cases"]
    )
    assert all(case["anchor_add_exit_code"] in (None, 0) for case in capture["cases"])


def test_breezy_profiles_agree_on_rules_and_membership_observations() -> None:
    baseline = CAPTURES[CAPTURE_FILES[0]]
    for profile in CAPTURE_FILES[1:]:
        other = CAPTURES[profile]
        assert baseline["default_rules"]["patterns"] == other["default_rules"]["patterns"]
        for baseline_case, other_case in zip(baseline["cases"], other["cases"], strict=True):
            assert baseline_case["id"] == other_case["id"]
            assert baseline_case["observed_ignored"] == other_case["observed_ignored"]
            assert baseline_case["observed_unknown"] == other_case["observed_unknown"]
            assert baseline_case["ignored_paths"] == other_case["ignored_paths"]
            assert baseline_case["unknown_paths"] == other_case["unknown_paths"]


def test_breezy_ignore_query_creates_the_user_ignore_file() -> None:
    for capture in CAPTURES.values():
        default_case = next(
            case for case in capture["cases"] if case["id"] == "brz.missing-user-file-defaults"
        )
        assert default_case["global_ignore_existed_before"] is False
        assert default_case["global_ignore_exists_after"] is True
        assert default_case["observed_ignored"] is True


def test_breezy_parent_exception_keeps_descendants_reachable() -> None:
    for capture in CAPTURES.values():
        case = next(
            case for case in capture["cases"] if case["id"] == "brz.parent-exception-traversal"
        )
        assert case["observed_ignored"] is False
        assert {"cache/drop.tmp", "cache/keep.tmp"} <= set(case["unknown_paths"])


def test_breezy_invalid_regex_is_a_native_query_error() -> None:
    for capture in CAPTURES.values():
        for case_id in ("brz.regex-invalid-pattern", "brz.regex-global-inline-flag-rejected"):
            case = next(case for case in capture["cases"] if case["id"] == case_id)
            assert case["ignored_exit_code"] == 3
            assert "Invalid pattern" in case["stderr"]


def test_breezy_named_regex_capture_is_normalized_with_a_warning() -> None:
    for capture in CAPTURES.values():
        case = next(
            case for case in capture["cases"] if case["id"] == "brz.regex-named-capture-match"
        )
        assert case["observed_ignored"] is True
        assert "not allowed within a regular expression" in case["stderr"]
        assert "Replacing with '(?:'" in case["stderr"]


def test_breezy_parent_exception_rule_opens_directory_even_without_matching_file() -> None:
    for capture in CAPTURES.values():
        case = next(
            case for case in capture["cases"] if case["id"] == "brz.parent-exception-target-absent"
        )
        assert case["observed_ignored"] is False
        assert "cache/drop.tmp" in case["unknown_paths"]


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize("topdown", [True, False], ids=["topdown", "bottomup"])
@pytest.mark.parametrize(
    "case_id",
    [
        "brz.walk-ignored-parent-exception-opens-siblings",
        "brz.regex-exception-opens-ignored-parent",
        "brz.ignored-parent-without-exception",
    ],
)
def test_breezy_walker_matches_captured_exception_parent_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    topdown: bool,
    case_id: str,
) -> None:
    case = next(case for case in CASES if case["id"] == case_id)
    observation = next(item for item in CAPTURES[profile]["cases"] if item["id"] == case_id)
    default_patterns = tuple(CAPTURES[profile]["default_rules"]["patterns"])
    monkeypatch.setattr(BreezyIgnorePolicy, "_load_default_patterns", lambda self: default_patterns)
    root = tmp_path / "checkout"
    root.mkdir()
    (root / ".bzr").mkdir()
    for relative, contents in case["setup"]["files"].items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    query = root / case["query"]
    query.parent.mkdir(parents=True, exist_ok=True)
    query.touch(exist_ok=True)
    anchor = query.parent / ".oracle-walk-anchor"
    anchor.write_text("native walker anchor\n", encoding="utf-8")
    policy = BreezyIgnorePolicy(
        root,
        global_ignore_file=tmp_path / "config" / "breezy" / "ignore",
    )
    walker = IgnoreWalker(root, policy=policy)
    tracked = {anchor.relative_to(root).as_posix()}
    included = {
        path.relative_to(root).as_posix()
        for path in walker.iter_files(selection="included", topdown=topdown)
    }
    ignored = {
        path.relative_to(root).as_posix()
        for path in walker.iter_files(selection="ignored", topdown=topdown)
    }

    assert observation["status_exit_code"] == 0
    assert included - tracked == set(observation["unknown_paths"])
    assert ignored - tracked == set(observation["ignored_paths"])
    assert (case["query"] in included) is (case_id != "brz.ignored-parent-without-exception")
    if case_id == "brz.walk-ignored-parent-exception-opens-siblings":
        assert "cache/drop.tmp" in included
    if case_id == "brz.regex-exception-opens-ignored-parent":
        assert "cache/drop.tmp" in ignored
        assert "cache/sibling.tmp" in ignored
    can_prune = policy.can_prune_ignored_directory(root / "cache", policy.explain("cache"))
    assert can_prune is (case_id == "brz.ignored-parent-without-exception")
