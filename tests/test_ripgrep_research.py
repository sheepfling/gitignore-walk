"""Inventory checks for ripgrep research, kept separate from VCS policy tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

INVENTORY_PATH = Path(__file__).parent / "oracles" / "ripgrep" / "research_cases.json"
CAPTURE_PATH = (
    Path(__file__).parent / "oracles" / "ripgrep" / "results" / "rg-14.1.1-linux-x86_64.json"
)
INVENTORY: dict[str, Any] = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
CASES: list[dict[str, Any]] = INVENTORY["cases"]
CAPTURE: dict[str, Any] = json.loads(CAPTURE_PATH.read_text(encoding="utf-8"))


def test_ripgrep_research_inventory_matches_native_capture() -> None:
    """Ensure each scanner case is classified and backed by the pinned native observation."""
    observations = {item["case_id"]: item for item in CAPTURE["results"]}
    case_ids = [case["id"] for case in CASES]

    assert INVENTORY["case_count"] == 16
    assert len(case_ids) == len(set(case_ids)) == len(observations)
    assert set(case_ids) == set(observations)
    assert CAPTURE["counts"] == {
        "passed": 16,
        "failed": 0,
        "observed": 0,
        "skipped": 0,
        "error": 0,
    }
    for case in CASES:
        result = observations[case["id"]]
        assert case["evidence_status"].startswith("native-observed;")
        assert case["target_area"]
        assert case["target_suite"].endswith(
            "test_ripgrep_research_inventory_matches_native_capture"
        )
        assert case["coverage_status"] == (
            "native capture imported; no scanner policy is implemented"
        )
        assert result["status"] == "passed"
        assert result["expected"] == case["expected_files"]
        assert result["observed"] == case["expected_files"]
