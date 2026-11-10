"""Integrity checks for captured Subversion native observations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from tests.oracles.svn.run import _apr_build_line
from tests.oracles.svn.transitions import EXPECTED_STATUS_ITEMS

ORACLE_ROOT = Path(__file__).parent / "oracles" / "svn"
CASES = json.loads((ORACLE_ROOT / "cases.json").read_text(encoding="utf-8"))["cases"]
CAPTURE_FILES = (
    "svn-1.15.0-macos-arm64.json",
    "svn-1.14.5-linux-aarch64.json",
    "svn-1.14.5-linux-x86_64.json",
    "svn-1.14.5-windows-x86_64.json",
    "svn-1.14.3-ubuntu-24.04-x86_64.json",
)
CAPTURES: dict[str, dict[str, Any]] = {
    name: json.loads((ORACLE_ROOT / "results" / name).read_text(encoding="utf-8"))
    for name in CAPTURE_FILES
}
USER_CONFIG_CAPTURE = json.loads(
    (ORACLE_ROOT / "results" / "svn-user-config-1.15.0-macos-arm64.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (
            b"svn, version 1.15.0\n\n   - APR 1.7.6 (compiled with 1.7.6)\n",
            "APR 1.7.6 (compiled with 1.7.6)",
        ),
        (b"   - APR-Util 1.6.6 (compiled with 1.6.5)\n", None),
        (b"svn, version 1.15.0\n", None),
    ],
)
def test_subversion_apr_build_parser(output: bytes, expected: str | None) -> None:
    """Retain the linked APR line when the native client reports it."""
    assert _apr_build_line(output) == expected


def test_subversion_macos_capture_uses_ambient_user_config() -> None:
    capture = USER_CONFIG_CAPTURE
    assert capture["status"] == "captured"
    assert capture["client"]["svn_version"] == "1.15.0"
    assert capture["expected_ignored_paths"] == ["candidate.user-config-hide"]
    assert capture["native_ignored_paths"] == capture["expected_ignored_paths"]
    assert capture["policy_ignored_paths"] == capture["expected_ignored_paths"]
    assert (
        capture["policy_source"]
        == "Subversion runtime configuration: <isolated-home>/.subversion/config"
    )
    assert (
        hashlib.sha256(capture["native_status_xml"].encode("utf-8")).hexdigest()
        == capture["native_status_stdout_sha256"]
    )
    assert capture["candidate_matches"]


def test_subversion_sparse_files_capture_preserves_collapsed_directory_status() -> None:
    """Retain native status evidence for sparse immediate-file depth traversal."""
    capture = CAPTURES["svn-1.15.0-macos-arm64.json"]
    assert capture["status"] == "captured"
    assert capture["client"]["svn"]["version"] == "1.15.0"
    assert capture["client"]["platform"].startswith("macOS-")
    case = next(
        case
        for case in capture["cases"]
        if case["id"] == "svn.sparse-files-collapses-unversioned-directory"
    )
    assert case["id"] == "svn.sparse-files-collapses-unversioned-directory"
    assert case["candidate_matches"]
    assert case["observed_ignored_paths"] == ["pkg/loose.tmp"]
    assert case["observed_status_paths"] == [
        "pkg/loose.tmp",
        "pkg/nested",
        "pkg/visible.txt",
    ]
    default_status = case["observations"]["default"]["paths"]
    assert "pkg/nested" in default_status
    assert "pkg/nested/deep.tmp" not in default_status


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
    if case["dimension"] == "apr-glob-flags":
        assert capture["client"]["svn"]["apr_build"]
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


def test_subversion_system_user_config_precedence_capture() -> None:
    """Keep native precedence evidence separate from the standard status corpus."""
    path = ORACLE_ROOT / "results" / "svn-config-precedence-debian-13-x86_64.json"
    capture = json.loads(path.read_text(encoding="utf-8"))
    assert capture["status"] == "captured"
    assert capture["client"]["svn_version"] == "1.14.5"
    assert capture["system_pattern"] == "*.system-only-hide"
    assert capture["user_pattern"] == "*.user-only-hide"
    assert (
        capture["system_config_sha256"]
        == hashlib.sha256(b"[miscellany]\nglobal-ignores = *.system-only-hide\n").hexdigest()
    )
    assert (
        capture["user_config_sha256"]
        == hashlib.sha256(b"[miscellany]\nglobal-ignores = *.user-only-hide\n").hexdigest()
    )
    assert capture["native_status_command"] == [
        "svn",
        "status",
        "--xml",
        "--no-ignore",
        ".",
    ]
    assert capture["native_status_exit_code"] == 0
    assert (
        capture["native_status_stdout_sha256"]
        == hashlib.sha256(capture["native_status_stdout"].encode()).hexdigest()
    )
    assert capture["expected_ignored_paths"] == ["candidate.user-only-hide"]
    assert capture["native_ignored_paths"] == capture["expected_ignored_paths"]
    assert capture["policy_ignored_paths"] == capture["expected_ignored_paths"]
    assert capture["policy_source"] == (
        "Subversion runtime configuration: <isolated-home>/.subversion/config"
    )
    assert capture["candidate_matches"]
