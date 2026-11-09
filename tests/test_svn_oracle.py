"""Integrity checks for captured Subversion native observations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

ORACLE_ROOT = Path(__file__).parent / "oracles" / "svn"
CASES = json.loads((ORACLE_ROOT / "cases.json").read_text(encoding="utf-8"))["cases"]
CAPTURE_FILES = (
    "svn-1.15.0-macos-arm64.json",
    "svn-1.14.5-linux-aarch64.json",
    "svn-1.14.5-linux-x86_64.json",
)
CAPTURES: dict[str, dict[str, Any]] = {
    name: json.loads((ORACLE_ROOT / "results" / name).read_text(encoding="utf-8"))
    for name in CAPTURE_FILES
}


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_subversion_capture_matches_candidate(profile: str, case: dict[str, Any]) -> None:
    capture = CAPTURES[profile]
    observation = next(item for item in capture["cases"] if item["id"] == case["id"])

    assert capture["status"] == "captured"
    assert observation["candidate_matches"]
    assert set(observation["observed_ignored_paths"]) == set(case["expected_ignored_paths"])
    if "expected_status_paths" in case:
        assert set(observation["observed_status_paths"]) == set(case["expected_status_paths"])


def test_subversion_captured_profiles_agree() -> None:
    observations = [
        {
            case["id"]: (
                case["observed_ignored_paths"],
                case.get("observed_status_paths"),
            )
            for case in capture["cases"]
        }
        for capture in CAPTURES.values()
    ]

    assert all(observation == observations[0] for observation in observations[1:])
