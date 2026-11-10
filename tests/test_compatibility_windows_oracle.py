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
def test_windows_jujutsu_capture_reconciles_path_patterns(case_id: str) -> None:
    pattern_discovery = OBSERVATIONS[case_id]["pattern_discovery"]

    assert pattern_discovery["candidate_matches"] is True
    assert pattern_discovery["ignored"] == [
        "blocked/keep.txt",
        "cache/drop.tmp",
        "nested/deep/deep.log",
        "root-only.tmp",
    ]
    assert pattern_discovery["included"] == ["cache/keep.tmp", "nested/root-only.tmp"]


@pytest.mark.parametrize(
    ("case_id", "expected_markers"),
    [("jj.colocated", [".git", ".jj"]), ("jj.noncolocated", [".jj"])],
)
def test_windows_jujutsu_modes_keep_their_distinct_repository_markers(
    case_id: str, expected_markers: list[str]
) -> None:
    assert OBSERVATIONS[case_id]["metadata_markers"] == expected_markers
