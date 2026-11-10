"""Check the captured Sapling `.gitignore` behavior across a release boundary."""

from __future__ import annotations

import json
from pathlib import Path

_ORACLE_RESULTS = Path(__file__).parent / "oracles" / "compat" / "results"
_PROBES = {
    "empty/target/under-empty-ignore.tmp",
    "missing/target/under-missing-ignore.tmp",
    "nested/target/under-nested-ignore.tmp",
    "nested/child/local.childignore",
}


def test_sapling_release_profiles_capture_storage_mode_behavior() -> None:
    """Keep observed `.sl` and `.git` behavior explicit for both Sapling releases."""
    profiles = (
        (
            "sapling-0.2.20261028-behavior-debian13-arm64.json",
            "Sapling 0.2.20261028",
            {"sl": set(), "git": _PROBES},
        ),
        (
            "sapling-0.2.20261103-behavior-debian13-arm64.json",
            "Sapling 0.2.20261103",
            {"sl": _PROBES, "git": _PROBES},
        ),
    )
    for filename, client_prefix, expected_by_mode in profiles:
        capture = json.loads((_ORACLE_RESULTS / filename).read_text(encoding="utf-8"))
        assert capture["client"].startswith(client_prefix)
        assert {case["mode"] for case in capture["cases"]} == set(expected_by_mode)
        for case in capture["cases"]:
            expected = expected_by_mode[case["mode"]]
            assert case["candidate_matches"]
            assert set(case["query_files"]) == _PROBES
            assert set(case["ignored"]) == expected
