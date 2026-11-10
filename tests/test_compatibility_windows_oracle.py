"""Integrity checks for the Windows Jujutsu compatibility capture."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

CAPTURE_PATH = (
    Path(__file__).parent / "oracles" / "compat" / "results" / "jj-0.47.1-windows-x64.json"
)
CAPTURE: dict[str, Any] = json.loads(CAPTURE_PATH.read_text(encoding="utf-8"))
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
