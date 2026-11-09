"""Integrity checks for captured Subversion native observations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from tests.oracles.svn.transitions import EXPECTED_STATUS_ITEMS

ORACLE_ROOT = Path(__file__).parent / "oracles" / "svn"
CASES = json.loads((ORACLE_ROOT / "cases.json").read_text(encoding="utf-8"))["cases"]
CAPTURE_FILES = (
    "svn-1.15.0-macos-arm64.json",
    "svn-1.14.5-linux-aarch64.json",
    "svn-1.14.5-linux-x86_64.json",
    "svn-1.14.5-windows-x86_64.json",
)
CAPTURES: dict[str, dict[str, Any]] = {
    name: json.loads((ORACLE_ROOT / "results" / name).read_text(encoding="utf-8"))
    for name in CAPTURE_FILES
}


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_subversion_capture_matches_candidate(profile: str, case: dict[str, Any]) -> None:
    capture = CAPTURES[profile]
    assert capture["status"] == "captured"
    observation = next((item for item in capture["cases"] if item["id"] == case["id"]), None)
    if observation is None:
        pytest.skip("committed native profile predates this candidate; live oracle covers it")
    if observation["native_status"] == "skipped":
        pytest.skip(observation["skip_reason"])

    assert observation["native_status"] == "captured"
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
            if case["native_status"] == "captured"
        }
        for capture in CAPTURES.values()
    ]

    baseline = observations[0]
    for observation in observations[1:]:
        shared_cases = baseline.keys() & observation.keys()
        assert all(baseline[case_id] == observation[case_id] for case_id in shared_cases)


def test_subversion_status_transition_capture_matches_expected_states() -> None:
    """Keep the committed native status-transition evidence complete and internally consistent."""
    path = ORACLE_ROOT / "results" / "svn-status-transitions-1.15.0-macos-arm64.json"
    capture = json.loads(path.read_text(encoding="utf-8"))
    assert capture["status"] == "captured"
    assert capture["client"]["svn"]["version"] == "1.15.0"
    assert len(capture["cases"]) == 1
    case = capture["cases"][0]
    assert case["id"] == "svn.status-membership-transitions"
    assert case["candidate_matches"]
    assert case["expected_status_items"] == EXPECTED_STATUS_ITEMS
    assert case["observed_status_items"] == EXPECTED_STATUS_ITEMS
    assert (
        hashlib.sha256(case["normalized_stdout"].encode()).hexdigest()
        == case["normalized_stdout_sha256"]
    )
