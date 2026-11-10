"""Integrity checks for the Windows Jujutsu compatibility capture."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

RESULTS_DIR = Path(__file__).parent / "oracles" / "compat" / "results"
VERSIONS = ("0.45.1", "0.46.0", "0.47.1")
CAPTURES: dict[str, dict[str, Any]] = {
    version: json.loads(
        (RESULTS_DIR / f"jj-{version}-windows-x64.json").read_text(encoding="utf-8")
    )
    for version in VERSIONS
}
CAPTURE = CAPTURES["0.47.1"]
OBSERVATIONS = {case["id"]: case for case in CAPTURE["cases"]}
FIXTURE_PATH = Path(__file__).parent / "oracles" / "compat" / "cases.json"
PATTERN_FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
PATTERN_QUERY_FILES = sorted(PATTERN_FIXTURE["pattern_query_files"])
PATTERN_IGNORED = sorted(PATTERN_FIXTURE["expected_pattern_ignored"])
PATTERN_INCLUDED = sorted(set(PATTERN_QUERY_FILES) - set(PATTERN_IGNORED))


def test_windows_jujutsu_capture_records_the_pinned_client_and_modes() -> None:
    assert CAPTURE["status"] == "captured"
    assert CAPTURE["platform"].startswith("Windows-2025Server")
    assert CAPTURE["clients"]["jujutsu"].startswith("jj 0.47.1")
    assert set(OBSERVATIONS) == {"jj.colocated", "jj.noncolocated"}


@pytest.mark.parametrize("case_id", ["jj.colocated", "jj.noncolocated"])
def test_windows_jujutsu_capture_reconciles_ignore_candidates(case_id: str) -> None:
    observation = OBSERVATIONS[case_id]

    assert observation["status_snapshots_disposable_workspace"] is True
    assert observation["candidate_matches"] is True
    assert observation["ignored"] == ["a.tmp"]
    assert observation["included"] == ["b.log", "visible.txt"]


@pytest.mark.parametrize("case_id", ["jj.colocated", "jj.noncolocated"])
def test_windows_jujutsu_capture_reconciles_source_discovery(case_id: str) -> None:
    source_discovery = OBSERVATIONS[case_id]["source_discovery"]
    expected_ignored = {
        "jj.colocated": ["global.global", "info.priority", "local.local"],
        "jj.noncolocated": ["global.global", "priority.global"],
    }

    assert source_discovery["candidate_matches"] is True
    assert source_discovery["ignored"] == expected_ignored[case_id]


@pytest.mark.parametrize("case_id", ["jj.colocated", "jj.noncolocated"])
def test_windows_jujutsu_capture_reconciles_environment_selected_global_config(
    case_id: str,
) -> None:
    environment_global = OBSERVATIONS[case_id]["environment_global"]

    assert environment_global["config_environment_variable"] == "GIT_CONFIG_GLOBAL"
    assert environment_global["query_files"] == ["environment.global", "environment.visible"]
    assert environment_global["ignored"] == ["environment.global"]
    assert environment_global["included"] == ["environment.visible"]
    assert environment_global["candidate_matches"] is True


@pytest.mark.parametrize("case_id", ["jj.colocated", "jj.noncolocated"])
def test_windows_jujutsu_capture_reconciles_path_patterns(case_id: str) -> None:
    pattern_discovery = OBSERVATIONS[case_id]["pattern_discovery"]

    assert pattern_discovery["candidate_matches"] is True
    assert pattern_discovery["query_files"] == PATTERN_QUERY_FILES
    assert pattern_discovery["ignored"] == PATTERN_IGNORED
    assert pattern_discovery["included"] == PATTERN_INCLUDED


@pytest.mark.parametrize(
    ("case_id", "expected_markers"),
    [("jj.colocated", [".git", ".jj"]), ("jj.noncolocated", [".jj"])],
)
def test_windows_jujutsu_modes_keep_their_distinct_repository_markers(
    case_id: str, expected_markers: list[str]
) -> None:
    assert OBSERVATIONS[case_id]["metadata_markers"] == expected_markers


@pytest.mark.parametrize("version", VERSIONS)
def test_windows_jujutsu_versioned_captures_cover_both_workspace_modes(version: str) -> None:
    capture = CAPTURES[version]

    assert capture["status"] == "captured"
    assert capture["platform"].startswith("Windows-2025Server")
    assert capture["clients"]["jujutsu"].startswith(f"jj {version}")
    assert {case["id"] for case in capture["cases"]} == {"jj.colocated", "jj.noncolocated"}
    assert all(case["candidate_matches"] for case in capture["cases"])
    assert all(
        case[probe]["candidate_matches"]
        for case in capture["cases"]
        for probe in (
            "source_discovery",
            "pattern_discovery",
            "extended_pattern_discovery",
            "configured_global",
            "configured_system",
            "conditional_global",
            "conditional_gitdir_i",
            "conditional_worktree",
            "conditional_worktree_i",
            "conditional_onbranch",
            "conditional_remote_url",
            "conditional_gitdir_override",
            "configured_repository",
            "environment_global",
            "environment_count",
        )
    )
    expected_query_files = sorted(PATTERN_FIXTURE["extended_pattern_query_files"])
    expected_ignored = sorted(PATTERN_FIXTURE["expected_extended_pattern_ignored"])
    for case in capture["cases"]:
        extended = case["extended_pattern_discovery"]
        assert extended["query_files"] == expected_query_files
        assert extended["ignored"] == expected_ignored
        assert extended["included"] == sorted(set(expected_query_files) - set(expected_ignored))


@pytest.mark.parametrize(
    ("version", "expected_ignored"),
    [
        ("0.45.1", ["nested/probe.symlink"]),
        ("0.46.0", []),
        ("0.47.1", []),
    ],
)
@pytest.mark.parametrize("case_id", ["jj.colocated", "jj.noncolocated"])
def test_windows_jujutsu_captures_the_symlink_source_version_boundary(
    version: str, expected_ignored: list[str], case_id: str
) -> None:
    symlink = next(case for case in CAPTURES[version]["cases"] if case["id"] == case_id)[
        "symlinked_gitignore"
    ]

    assert symlink["native_status"] == "captured"
    assert symlink["ignored"] == expected_ignored
    assert symlink["candidate_matches"] is True
