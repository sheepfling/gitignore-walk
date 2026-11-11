"""Check the captured Sapling `.gitignore` behavior across a release boundary."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.oracles.compat import sapling_release_profiles

_ORACLE_RESULTS = Path(__file__).parent / "oracles" / "compat" / "results"
_PROBES = {
    "empty/target/under-empty-ignore.tmp",
    "missing/target/under-missing-ignore.tmp",
    "nested/target/under-nested-ignore.tmp",
    "nested/child/local.childignore",
}


def test_sapling_release_profiles_capture_storage_mode_behavior() -> None:
    """Keep the `.gitignore` fix boundary explicit across three Sapling releases."""
    profiles = (
        (
            "sapling-0.2.20261028-behavior-debian13-arm64.json",
            "Sapling 0.2.20261028",
            {"sl": set(), "git": _PROBES},
        ),
        (
            "sapling-0.2.20261102-behavior-debian13-arm64.json",
            "Sapling 0.2.20261102",
            {"sl": _PROBES, "git": _PROBES},
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


def test_sapling_fix_release_windows_capture_matches_both_storage_modes() -> None:
    """Retain native Windows evidence for Sapling's 0.2.20261102 ignore fix."""
    capture = json.loads(
        (_ORACLE_RESULTS / "sapling-0.2.20261102-behavior-windows-x64.json").read_text(
            encoding="utf-8"
        )
    )

    assert capture["status"] == "captured"
    assert capture["profile_version"] == "0.2.20261102"
    assert capture["client"].startswith("Sapling 0.2.20261102")
    assert capture["platform"].startswith("Windows-2025Server-")
    assert capture["machine"].lower() in {"amd64", "x86_64"}
    assert {case["mode"] for case in capture["cases"]} == {"sl", "git"}
    for case in capture["cases"]:
        assert case["candidate_matches"]
        assert set(case["ignored"]) == _PROBES


def test_sapling_release_profile_records_version_command_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Record startup failure without labeling absent probes as conformance."""
    output = tmp_path / "capture.json"
    result = subprocess.CompletedProcess(
        args=["sl", "--version"], returncode=255, stdout="", stderr="client failed to start"
    )

    def failed_version_probe(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        assert command == ["sl", "--version"]
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        assert Path(environment["HOME"], ".gitconfig").is_file()
        return result

    monkeypatch.setattr(sapling_release_profiles.subprocess, "run", failed_version_probe)
    monkeypatch.setattr(sapling_release_profiles.platform, "platform", lambda: "test-platform")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sapling_release_profiles.py",
            "--sl",
            "sl",
            "--profile-version",
            "0.2.20261102",
            "--output",
            str(output),
        ],
    )

    assert sapling_release_profiles.main() == 0
    capture = json.loads(output.read_text(encoding="utf-8"))
    assert capture["status"] == "client-error"
    assert capture["conformance"] == "client-error-observed"
    assert capture["version_probe"]["exit_code"] == 255
    assert capture["version_probe"]["stderr"] == "client failed to start"
    assert capture["cases"] == []
