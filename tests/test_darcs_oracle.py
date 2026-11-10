"""Integrity checks for captured Darcs boring-file behavior."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.oracles.darcs.run import _global_boring_path

ORACLE_ROOT = Path(__file__).parent / "oracles" / "darcs"
CASES = json.loads((ORACLE_ROOT / "cases.json").read_text(encoding="utf-8"))["cases"]
CAPTURE_FILES = (
    "darcs-2.18.5-macos-arm64.json",
    "darcs-debian13-x86_64.json",
    "darcs-debian13-arm64.json",
)
CAPTURES = {
    profile: json.loads((ORACLE_ROOT / "results" / profile).read_text(encoding="utf-8"))
    for profile in CAPTURE_FILES
}
OBSERVATIONS = {
    profile: {case["id"]: case for case in capture["cases"]}
    for profile, capture in CAPTURES.items()
}


@pytest.mark.parametrize(
    ("windows", "environment", "expected"),
    [
        (False, {"HOME": "/tmp/home", "APPDATA": "/tmp/appdata"}, "/tmp/home/.darcs/boring"),
        (True, {"HOME": "/tmp/home", "APPDATA": "/tmp/appdata"}, "/tmp/appdata/darcs/boring"),
        (
            True,
            {
                "APPDATA": "/tmp/appdata",
                "DARCS_TESTING_PREFS_DIR": "/tmp/darcs-test-prefs",
            },
            "/tmp/darcs-test-prefs/boring",
        ),
    ],
)
def test_darcs_global_boring_path_uses_platform_configuration_directory(
    windows: bool, environment: dict[str, str], expected: str
) -> None:
    assert _global_boring_path(environment, windows=windows) == Path(expected)


@pytest.mark.parametrize("profile", CAPTURE_FILES, ids=lambda name: name.removesuffix(".json"))
def test_darcs_capture_profiles_are_isolated_and_complete(profile: str) -> None:
    capture = CAPTURES[profile]
    assert capture["status"] == "captured"
    assert capture["client"]["version"].startswith("2.18.")
    assert {case["id"] for case in capture["cases"]} == {case["id"] for case in CASES}
    assert all(case["setup_isolated"] is True for case in capture["cases"])


@pytest.mark.parametrize("profile", CAPTURE_FILES, ids=lambda name: name.removesuffix(".json"))
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_darcs_captured_boring_decisions_match_closed_candidates(
    profile: str, case: dict[str, Any]
) -> None:
    observation = OBSERVATIONS[profile][case["id"]]
    if case["expected_boring"] is None:
        pytest.skip("native observation is retained as an open contract question")
    assert case["native_status"] == "captured"
    assert observation["observed_boring"] is case["expected_boring"]


@pytest.mark.parametrize("profile", CAPTURE_FILES, ids=lambda name: name.removesuffix(".json"))
def test_darcs_local_global_and_configured_sources_are_additive(profile: str) -> None:
    observations = OBSERVATIONS[profile]
    assert observations["darcs.boringfile-selects-versioned-source"]["observed_boring"] is True
    assert observations["darcs.boringfile-replaces-local"]["observed_boring"] is True
    assert observations["darcs.global-additive"]["observed_boring"] is True
    assert observations["darcs.global-remains-active-with-local-rules"]["observed_boring"] is True
    assert (
        observations["darcs.global-remains-active-with-configured-boringfile"]["observed_boring"]
        is True
    )


@pytest.mark.parametrize("profile", CAPTURE_FILES, ids=lambda name: name.removesuffix(".json"))
def test_darcs_invalid_regex_is_skipped_with_a_warning(profile: str) -> None:
    observation = OBSERVATIONS[profile]["darcs.comments-and-invalid-regex"]
    assert observation["observed_boring"] is None
    assert "Warning: Ignored invalid boring regex: invalid[" in observation["whatsnew_stderr"]
