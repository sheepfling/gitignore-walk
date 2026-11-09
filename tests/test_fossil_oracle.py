"""Integrity checks for committed Fossil native observations."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from gitignore_walk import FossilIgnorePolicy, IgnoreWalker
from gitignore_walk._schemes.fossil import policy as fossil_policy_module
from gitignore_walk._schemes.fossil.policy import _matches_glob, _parse_glob_list

ORACLE_ROOT = Path(__file__).parent / "oracles" / "fossil"
CASES = json.loads((ORACLE_ROOT / "cases.json").read_text(encoding="utf-8"))["cases"]
CAPTURE_FILES = (
    "fossil-2.28-macos-arm64.json",
    "fossil-2.26-linux-aarch64.json",
)
CAPTURES: dict[str, dict[str, Any]] = {
    name: json.loads((ORACLE_ROOT / "results" / name).read_text(encoding="utf-8"))
    for name in CAPTURE_FILES
}
MALFORMED_CASE = next(case for case in CASES if case["id"] == "fossil.malformed-quotes")
MALFORMED_PROBES = MALFORMED_CASE["setup"]["probes"]


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_fossil_capture_matches_known_candidate(profile: str, case: dict[str, Any]) -> None:
    capture = CAPTURES[profile]
    observation = next(item for item in capture["cases"] if item["id"] == case["id"])

    assert capture["status"] == "captured"
    if isinstance(case["expected_candidate"], bool):
        assert observation["candidate_matches"] is True
        assert observation["observed_ignored"] is case["expected_candidate"]
    else:
        assert observation["candidate_matches"] is None
        assert observation["observed_ignored"] is None or isinstance(
            observation["observed_ignored"], bool
        )
        captured_probes = observation["setting_probes"]
        assert len(captured_probes) == len(MALFORMED_PROBES)
        for expected, captured in zip(MALFORMED_PROBES, captured_probes, strict=True):
            assert captured["query"] == expected["query"]
            assert captured["value"] == expected["value"]
            assert captured["observed_ignored"] is expected["expected_candidate"]


@pytest.mark.parametrize("profile", CAPTURE_FILES)
def test_fossil_capture_has_no_setup_or_probe_command_failures(profile: str) -> None:
    capture = CAPTURES[profile]
    assert all(not case["setup_failed"] for case in capture["cases"])
    assert all(
        case["extras"] is None or case["extras"]["exit_code"] == 0 for case in capture["cases"]
    )


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize(
    "case",
    [case for case in CASES if isinstance(case["expected_candidate"], bool)],
    ids=lambda case: case["id"],
)
def test_fossil_policy_matches_captured_ignore_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    case: dict[str, Any],
) -> None:
    if os.name == "nt":
        components = case["query"].split("/")
        if any("\\" in component for component in components):
            pytest.skip("Windows paths cannot represent a POSIX filename containing backslash")
        if any(
            any(character in component for character in '<>:"|?*') or component.endswith((" ", "."))
            for component in components
        ):
            pytest.skip("Windows cannot represent this Fossil oracle filename")
    setup = case["setup"]
    setting = setup.get(
        "versioned_ignore_glob",
        setup.get("local_ignore_glob", setup.get("ignore_glob", "")),
    )
    root = tmp_path / "checkout"
    root.mkdir()
    (root / ".fslckout").touch()
    for relative, contents in setup.get("files", {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    query = case["query"]
    query_path = root / query
    query_path.parent.mkdir(parents=True, exist_ok=True)
    query_path.write_text("oracle fixture\n", encoding="utf-8")

    def captured_setting(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert command[1:] == ["settings", "ignore-glob", "--value"]
        assert Path(kwargs["cwd"]) == root
        return subprocess.CompletedProcess(command, 0, setting.encode(), b"")

    monkeypatch.setattr(fossil_policy_module.subprocess, "run", captured_setting)
    policy = FossilIgnorePolicy(root, environment={"PATH": ""})

    assert policy.explain(query).ignored is case["expected_candidate"]


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize(
    "probe",
    MALFORMED_PROBES,
    ids=lambda probe: f"{probe['value']}->{probe['query']}",
)
def test_fossil_policy_matches_captured_malformed_token_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    probe: dict[str, Any],
) -> None:
    if os.name == "nt":
        components = probe["query"].split("/")
        if any("\\" in component for component in components):
            pytest.skip("Windows paths cannot represent a POSIX filename containing backslash")
        if any(any(character in component for character in '<>:"|?*') for component in components):
            pytest.skip("Windows cannot represent this Fossil oracle filename")
    captured = next(
        case for case in CAPTURES[profile]["cases"] if case["id"] == MALFORMED_CASE["id"]
    )
    observed = next(
        item
        for item in captured["setting_probes"]
        if item["value"] == probe["value"] and item["query"] == probe["query"]
    )
    assert observed["observed_ignored"] is probe["expected_candidate"]

    root = tmp_path / "checkout"
    root.mkdir()
    (root / ".fslckout").touch()
    query_path = root / probe["query"]
    query_path.parent.mkdir(parents=True, exist_ok=True)
    query_path.write_text("oracle fixture\n", encoding="utf-8")

    def captured_setting(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert command[1:] == ["settings", "ignore-glob", "--value"]
        assert Path(kwargs["cwd"]) == root
        return subprocess.CompletedProcess(command, 0, probe["value"].encode(), b"")

    monkeypatch.setattr(fossil_policy_module.subprocess, "run", captured_setting)
    policy = FossilIgnorePolicy(root, environment={"PATH": ""})

    assert policy.is_ignored(probe["query"]) is probe["expected_candidate"]


def test_fossil_captured_profiles_agree() -> None:
    observations = []
    for capture in CAPTURES.values():
        observations.append(
            {
                case["id"]: {
                    "observed_ignored": case["observed_ignored"],
                    "setting_probes": [
                        (probe["query"], probe["exit_code"], probe["observed_ignored"])
                        for probe in case["setting_probes"]
                    ],
                }
                for case in capture["cases"]
            }
        )

    assert observations[0] == observations[1]


@pytest.mark.parametrize("profile", CAPTURE_FILES)
def test_fossil_walker_matches_captured_extras_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    case = next(case for case in CASES if case["id"] == "fossil.directory-inheritance")
    observation = next(item for item in CAPTURES[profile]["cases"] if item["id"] == case["id"])
    root = tmp_path / "checkout"
    root.mkdir()
    (root / ".fslckout").touch()
    setup = case["setup"]
    for relative, contents in setup["files"].items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    query_path = root / case["query"]
    query_path.parent.mkdir(parents=True, exist_ok=True)
    query_path.write_text("oracle fixture\n", encoding="utf-8")

    def captured_setting(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert command[1:] == ["settings", "ignore-glob", "--value"]
        assert Path(kwargs["cwd"]) == root
        return subprocess.CompletedProcess(command, 0, setup["ignore_glob"].encode(), b"")

    monkeypatch.setattr(fossil_policy_module.subprocess, "run", captured_setting)
    policy = FossilIgnorePolicy(root, environment={"PATH": ""})
    walker = IgnoreWalker(root, policy=policy)
    native_extras = set(observation["extras"]["listed_paths"])
    included = {
        path.relative_to(root).as_posix() for path in walker.iter_files(selection="included")
    }
    ignored = {path.relative_to(root).as_posix() for path in walker.iter_files(selection="ignored")}
    expected_paths = set(setup["files"]) | {case["query"], ".fslckout"}

    assert observation["extras"]["exit_code"] == 0
    assert included == native_extras
    assert ignored == expected_paths - native_extras
    assert ".fslckout" in ignored
    assert "cache/nested/second.tmp" in ignored
    assert "cacheable/visible.txt" in included


@pytest.mark.parametrize("profile", CAPTURE_FILES)
def test_fossil_open_tokenizer_probes_match_captured_observations(profile: str) -> None:
    """Keep observed malformed-token behavior covered without claiming full conformance."""
    capture = CAPTURES[profile]
    observation = next(case for case in capture["cases"] if case["id"] == "fossil.malformed-quotes")

    assert observation["evidence_status"] == "open-question"
    probes = observation["setting_probes"]
    assert probes
    for probe in probes:
        patterns = _parse_glob_list(probe["value"])
        actual = any(_matches_glob(probe["query"], pattern) for pattern in patterns)
        assert actual is probe["observed_ignored"], probe
