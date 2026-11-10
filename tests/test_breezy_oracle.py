"""Integrity checks for captured Breezy native observations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from gitignore_walk import BreezyIgnorePolicy, IgnoreWalker
from tests.oracles.breezy.run import _capture_profile_name, _select_cases_for_profile

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


@pytest.mark.parametrize(
    ("system", "machine", "python_version", "expected"),
    [
        ("Darwin", "arm64", (3, 12), "brz-3.3.24-macos-arm64.json"),
        ("Linux", "aarch64", (3, 12), "brz-3.3.24-linux-aarch64-py312.json"),
        ("Windows", "AMD64", (3, 12), "brz-3.3.24-windows-x86_64-py312.json"),
    ],
)
def test_breezy_profile_scoping_uses_capture_filename(
    system: str, machine: str, python_version: tuple[int, int], expected: str
) -> None:
    assert (
        _capture_profile_name(
            "Breezy (brz) 3.3.24",
            system=system,
            machine=machine,
            python_version=python_version,
        )
        == expected
    )


def test_breezy_capture_only_runs_cases_declared_for_the_current_profile() -> None:
    cases = [
        {"id": "shared"},
        {"id": "mac-only", "capture_profiles": ["brz-3.3.24-macos-arm64.json"]},
    ]

    selected, excluded = _select_cases_for_profile(cases, "brz-3.3.24-windows-x86_64-py312.json")

    assert [case["id"] for case in selected] == ["shared"]
    assert excluded == [
        {
            "id": "mac-only",
            "required_profiles": ["brz-3.3.24-macos-arm64.json"],
            "current_profile": "brz-3.3.24-windows-x86_64-py312.json",
        }
    ]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_breezy_captures_match_versioned_candidates(case: dict[str, Any]) -> None:
    profiles = case.get("capture_profiles", CAPTURE_FILES)
    for profile in profiles:
        capture = CAPTURES[profile]
        observation = next(item for item in capture["cases"] if item["id"] == case["id"])

        assert capture["status"] == "captured"
        expected = case["expected_candidate"]
        if isinstance(expected, bool):
            assert observation["candidate_matches"] is True
            assert observation["observed_ignored"] is expected
        else:
            assert observation["candidate_matches"] is None
        if "expected_winning_pattern" in case:
            assert observation["winning_pattern_matches"] is True
            assert observation["observed_pattern"] == case["expected_winning_pattern"]


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
            if case["id"]
            in {
                "brz.regex-invalid-pattern",
                "brz.regex-global-inline-flag-rejected",
                "brz.regex-backreference-invalid-pattern",
            }
            else 0
        )
        for case in capture["cases"]
    )
    assert all(
        case["status_exit_code"]
        == (
            3
            if case["id"]
            in {
                "brz.regex-invalid-pattern",
                "brz.regex-global-inline-flag-rejected",
                "brz.regex-backreference-invalid-pattern",
            }
            else 0
        )
        for case in capture["cases"]
    )
    assert all(case["anchor_add_exit_code"] in (None, 0) for case in capture["cases"])


@pytest.mark.parametrize("profile", CAPTURE_FILES)
def test_breezy_captures_record_exact_profile_exclusions(profile: str) -> None:
    capture = CAPTURES[profile]
    selected, excluded = _select_cases_for_profile(CASES, profile)

    assert {case["id"] for case in capture["cases"]} == {case["id"] for case in selected}
    assert capture["excluded_cases"] == excluded


def test_breezy_profiles_agree_on_rules_and_membership_observations() -> None:
    baseline = CAPTURES[CAPTURE_FILES[0]]
    baseline_cases = {case["id"]: case for case in baseline["cases"]}
    for profile in CAPTURE_FILES[1:]:
        other = CAPTURES[profile]
        assert baseline["default_rules"]["patterns"] == other["default_rules"]["patterns"]
        other_cases = {case["id"]: case for case in other["cases"]}
        for case_id in baseline_cases.keys() & other_cases.keys():
            baseline_case = baseline_cases[case_id]
            other_case = other_cases[case_id]
            assert baseline_case["observed_ignored"] == other_case["observed_ignored"]
            if baseline_case.get("winning_pattern_matches") is not None:
                assert baseline_case["observed_pattern"] == other_case["observed_pattern"]
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
        for case_id in (
            "brz.regex-invalid-pattern",
            "brz.regex-global-inline-flag-rejected",
        ):
            case = next(case for case in capture["cases"] if case["id"] == case_id)
            assert case["ignored_exit_code"] == 3
            assert "Invalid pattern" in case["stderr"]


def test_breezy_backreference_regex_is_a_native_query_error() -> None:
    case_id = "brz.regex-backreference-invalid-pattern"
    case_data = next(case for case in CASES if case["id"] == case_id)
    for profile in case_data["capture_profiles"]:
        observation = next(item for item in CAPTURES[profile]["cases"] if item["id"] == case_id)
        assert observation["ignored_exit_code"] == 3
        assert "Invalid pattern" in observation["stderr"]


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


@pytest.mark.parametrize("topdown", [True, False], ids=["topdown", "bottomup"])
def test_breezy_walker_matches_root_anchored_nested_exception_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, topdown: bool
) -> None:
    profile = "brz-3.3.24-macos-arm64.json"
    case_id = "brz.walk-root-anchored-nested-exception"
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
    (root / ".bzrignore").write_text("\n".join(case["setup"]["patterns"]) + "\n", encoding="utf-8")
    query = root / case["query"]
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

    assert observation["observed_ignored"] is True
    assert observation["observed_unknown"] is False
    assert included - tracked == set(observation["unknown_paths"])
    assert ignored - tracked == set(observation["ignored_paths"])
    assert "cache/keep.tmp" in included
    assert policy.can_prune_ignored_directory(root / "cache", policy.explain("cache")) is False
