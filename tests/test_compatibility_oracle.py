"""Integrity checks for captured Sapling/Jujutsu Git-ignore compatibility probes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

ORACLE_ROOT = Path(__file__).parent / "oracles" / "compat"
CAPTURE = json.loads(
    (ORACLE_ROOT / "results" / "sapling-0.2.20261103-jj-0.47.1-macos-arm64.json").read_text(
        encoding="utf-8"
    )
)
OBSERVATIONS = {case["id"]: case for case in CAPTURE["cases"]}


@pytest.mark.parametrize("case_id", sorted(OBSERVATIONS))
def test_compatibility_capture_reconciles_ignore_candidates(case_id: str) -> None:
    observation = OBSERVATIONS[case_id]

    assert observation["isolated_temporary_workspace"] is True
    assert observation["candidate_matches"] is True
    assert observation["ignored"] == ["a.tmp"]
    assert observation["included"] == ["b.log", "visible.txt"]


@pytest.mark.parametrize("case_id", sorted(OBSERVATIONS))
def test_compatibility_capture_reconciles_ignore_source_discovery(case_id: str) -> None:
    source_discovery = OBSERVATIONS[case_id]["source_discovery"]
    expected_ignored = {
        "sapling.git-mode": ["global.global", "info.priority", "local.local"],
        "sapling.sl-mode": [],
        "jj.colocated": ["global.global", "info.priority", "local.local"],
        "jj.noncolocated": ["global.global", "priority.global"],
    }

    assert source_discovery["candidate_matches"] is True
    assert source_discovery["query_files"] == [
        "global.global",
        "info.priority",
        "local.local",
        "local.priority",
        "priority.global",
    ]
    assert source_discovery["ignored"] == expected_ignored[case_id]


@pytest.mark.parametrize(
    ("case_id", "expected_markers"),
    [
        ("sapling.git-mode", [".git"]),
        ("sapling.sl-mode", [".sl"]),
        ("jj.colocated", [".git", ".jj"]),
        ("jj.noncolocated", [".jj"]),
    ],
)
def test_compatibility_modes_keep_their_distinct_repository_markers(
    case_id: str, expected_markers: list[str]
) -> None:
    assert OBSERVATIONS[case_id]["metadata_markers"] == expected_markers


def test_jujutsu_probe_records_that_status_snapshotted_only_a_temp_workspace() -> None:
    for case_id in ("jj.colocated", "jj.noncolocated"):
        observation: dict[str, Any] = OBSERVATIONS[case_id]
        assert observation["status_snapshots_disposable_workspace"] is True
