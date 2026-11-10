"""Integrity checks for captured Sapling/Jujutsu Git-ignore compatibility probes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

ORACLE_ROOT = Path(__file__).parent / "oracles" / "compat"
CAPTURE_FILES = (
    "sapling-0.2.20261103-jj-0.47.1-macos-arm64.json",
    "sapling-0.2.20261103-jj-0.47.1-debian13-arm64.json",
)
CAPTURES: dict[str, dict[str, Any]] = {
    profile: json.loads((ORACLE_ROOT / "results" / profile).read_text(encoding="utf-8"))
    for profile in CAPTURE_FILES
}
OBSERVATIONS = {
    profile: {case["id"]: case for case in capture["cases"]}
    for profile, capture in CAPTURES.items()
}


@pytest.mark.parametrize("profile", CAPTURE_FILES)
def test_compatibility_capture_records_exact_client_families(profile: str) -> None:
    capture = CAPTURES[profile]

    assert capture["status"] == "captured"
    assert "Sapling 0.2.20261103" in capture["clients"]["sapling"]
    assert capture["clients"]["jujutsu"].startswith("jj 0.47.1")


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize("case_id", sorted(OBSERVATIONS[CAPTURE_FILES[0]]))
def test_compatibility_capture_reconciles_ignore_candidates(profile: str, case_id: str) -> None:
    observation = OBSERVATIONS[profile][case_id]

    assert observation["isolated_temporary_workspace"] is True
    assert observation["candidate_matches"] is True
    assert observation["ignored"] == ["a.tmp"]
    assert observation["included"] == ["b.log", "visible.txt"]


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize("case_id", sorted(OBSERVATIONS[CAPTURE_FILES[0]]))
def test_compatibility_capture_reconciles_ignore_source_discovery(
    profile: str, case_id: str
) -> None:
    source_discovery = OBSERVATIONS[profile][case_id]["source_discovery"]
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


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize("case_id", sorted(OBSERVATIONS[CAPTURE_FILES[0]]))
def test_compatibility_capture_reconciles_path_pattern_discovery(
    profile: str, case_id: str
) -> None:
    pattern_discovery = OBSERVATIONS[profile][case_id]["pattern_discovery"]

    assert pattern_discovery["candidate_matches"] is True
    assert pattern_discovery["query_files"] == [
        "blocked/keep.txt",
        "cache/drop.tmp",
        "cache/keep.tmp",
        "nested/deep/deep.log",
        "nested/root-only.tmp",
        "root-only.tmp",
    ]
    assert pattern_discovery["ignored"] == [
        "blocked/keep.txt",
        "cache/drop.tmp",
        "nested/deep/deep.log",
        "root-only.tmp",
    ]
    assert pattern_discovery["included"] == ["cache/keep.tmp", "nested/root-only.tmp"]


@pytest.mark.parametrize(
    ("case_id", "expected_markers"),
    [
        ("sapling.git-mode", [".git"]),
        ("sapling.sl-mode", [".sl"]),
        ("jj.colocated", [".git", ".jj"]),
        ("jj.noncolocated", [".jj"]),
    ],
)
@pytest.mark.parametrize("profile", CAPTURE_FILES)
def test_compatibility_modes_keep_their_distinct_repository_markers(
    profile: str, case_id: str, expected_markers: list[str]
) -> None:
    assert OBSERVATIONS[profile][case_id]["metadata_markers"] == expected_markers


def test_jujutsu_probe_records_that_status_snapshotted_only_a_temp_workspace() -> None:
    for observations in OBSERVATIONS.values():
        for case_id in ("jj.colocated", "jj.noncolocated"):
            observation: dict[str, Any] = observations[case_id]
            assert observation["status_snapshots_disposable_workspace"] is True
