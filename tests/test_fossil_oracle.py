"""Integrity checks for committed Fossil native observations."""

from __future__ import annotations

import base64
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
    "fossil-2.26-linux-x86_64.json",
    "fossil-2.23-ubuntu-24.04-x86_64.json",
)
CAPTURES: dict[str, dict[str, Any]] = {
    name: json.loads((ORACLE_ROOT / "results" / name).read_text(encoding="utf-8"))
    for name in CAPTURE_FILES
}
MEMBERSHIP_CAPTURE = json.loads(
    (ORACLE_ROOT / "results" / "fossil-membership-2.28-macos-arm64.json").read_text(
        encoding="utf-8"
    )
)
LINUX_MEMBERSHIP_CAPTURE = json.loads(
    (ORACLE_ROOT / "results" / "fossil-membership-2.23-ubuntu-24.04-x86_64.json").read_text(
        encoding="utf-8"
    )
)
NESTED_CHECKOUT_CAPTURE_FILES = (
    "fossil-nested-checkout-2.28-macos-arm64.json",
    "fossil-nested-checkout-2.23-ubuntu-24.04-x86_64.json",
)
NESTED_CHECKOUT_CAPTURES: dict[str, dict[str, Any]] = {
    name: json.loads((ORACLE_ROOT / "results" / name).read_text(encoding="utf-8"))
    for name in NESTED_CHECKOUT_CAPTURE_FILES
}
TOKENIZER_CASES = tuple(case for case in CASES if "probes" in case["setup"])
TOKENIZER_PROBES = tuple(
    (case, probe) for case in TOKENIZER_CASES for probe in case["setup"]["probes"]
)


def _windows_unrepresentable_query_reason(query: str) -> str | None:
    """Return why Win32 cannot create an oracle query as a filesystem entry."""
    components = query.split("/")
    if any("\\" in component for component in components):
        return "Windows paths cannot represent a POSIX filename containing backslash"
    if any(any(ord(character) < 32 for character in component) for component in components):
        return "Windows filenames cannot contain ASCII control characters"
    if any(
        any(character in component for character in '<>:"|?*') or component.endswith((" ", "."))
        for component in components
    ):
        return "Windows cannot represent this Fossil oracle filename"
    return None


def _skip_unrepresentable_windows_query(query: str) -> None:
    """Skip oracle paths that Win32 cannot create as filesystem entries."""
    if os.name == "nt":
        reason = _windows_unrepresentable_query_reason(query)
        if reason is not None:
            pytest.skip(reason)


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        ("one\x1ctwo", "Windows filenames cannot contain ASCII control characters"),
        (r"one\two", "Windows paths cannot represent a POSIX filename containing backslash"),
        ("visible.txt", None),
    ],
)
def test_windows_oracle_query_representability(query: str, reason: str | None) -> None:
    assert _windows_unrepresentable_query_reason(query) == reason


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
        expected_probes = case["setup"]["probes"]
        captured_probes = observation["setting_probes"]
        assert len(captured_probes) == len(expected_probes)
        for expected, captured in zip(expected_probes, captured_probes, strict=True):
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


@pytest.mark.parametrize("profile", NESTED_CHECKOUT_CAPTURE_FILES)
def test_fossil_nested_checkout_capture_matches_native_boundary(profile: str) -> None:
    capture = NESTED_CHECKOUT_CAPTURES[profile]
    case = capture["case"]

    assert capture["schema_version"] == 1
    assert capture["status"] == "captured"
    assert capture["client"]["fossil"].startswith("This is fossil version ")
    assert case["id"] == "fossil.walk-stops-at-nested-checkout"
    assert case["command"] == ["fossil", "extras", "--dotfiles"]
    assert case["expected_paths"] == ["outer.txt"]
    assert case["observed_native_paths"] == case["expected_paths"]
    assert case["observed_policy_paths"] == case["observed_native_paths"]
    assert case["candidate_matches_native"] is True
    assert case["native_matches_expected"] is True
    assert case["exit_code"] == 0
    assert case["stderr"] == ""


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
    _skip_unrepresentable_windows_query(case["query"])
    setup = case["setup"]
    setting = setup.get(
        "versioned_ignore_glob",
        setup.get(
            "local_ignore_glob",
            setup.get("ignore_glob", setup.get("global_ignore_glob", "")),
        ),
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
    ("case", "probe"),
    TOKENIZER_PROBES,
    ids=[f"{case['id']}:{probe['value']}->{probe['query']}" for case, probe in TOKENIZER_PROBES],
)
def test_fossil_policy_matches_captured_tokenizer_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    case: dict[str, Any],
    probe: dict[str, Any],
) -> None:
    _skip_unrepresentable_windows_query(probe["query"])
    captured = next(item for item in CAPTURES[profile]["cases"] if item["id"] == case["id"])
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


def test_fossil_membership_transition_capture_is_complete() -> None:
    """Retain exact native inventory and status evidence for membership transitions."""
    assert MEMBERSHIP_CAPTURE["schema_version"] == 1
    assert MEMBERSHIP_CAPTURE["status"] == "captured"
    assert MEMBERSHIP_CAPTURE["client"]["fossil"].startswith("This is fossil version 2.28 ")
    assert MEMBERSHIP_CAPTURE["client"]["platform"].startswith("macOS-")
    assert MEMBERSHIP_CAPTURE["inventory"] == {
        "root_entries": ["deleted.tmp", "modified.tmp", "moved.tmp", "nested", "tracked.tmp"],
        "nested_entries": ["versioned.txt"],
    }
    assert MEMBERSHIP_CAPTURE["before_transitions"]["status_files"] == []
    assert MEMBERSHIP_CAPTURE["after_transitions"]["status_by_name"] == {
        "added.tmp": "new",
        "deleted.tmp": "missing",
        "modified.tmp": "edited",
        "renamed.tmp": ["missing", "renamed"],
    }
    assert {case["id"] for case in MEMBERSHIP_CAPTURE["cases"]} == {
        "fossil.membership.added.tmp",
        "fossil.membership.clean-status",
        "fossil.membership.deleted.tmp",
        "fossil.membership.modified.tmp",
        "fossil.membership.nested-inventory",
        "fossil.membership.renamed.tmp",
        "fossil.membership.root-inventory",
    }
    assert all(case["candidate_matches"] for case in MEMBERSHIP_CAPTURE["cases"])
    raw_results = MEMBERSHIP_CAPTURE["native_results"]
    assert all(result["exit_code"] == 0 for result in raw_results.values())
    root_payload = json.loads(base64.b64decode(raw_results["root_inventory"]["stdout_base64"]))[
        "payload"
    ]
    status_payload = json.loads(
        base64.b64decode(raw_results["transition_status"]["stdout_base64"])
    )["payload"]
    assert (
        sorted(entry["name"] for entry in root_payload["entries"])
        == MEMBERSHIP_CAPTURE["inventory"]["root_entries"]
    )
    assert {item["name"]: item["status"] for item in status_payload["files"]} == MEMBERSHIP_CAPTURE[
        "after_transitions"
    ]["status_by_name"]


def test_fossil_linux_membership_capture_matches_transition_contract() -> None:
    """Check the Linux capture against the committed macOS membership observations."""
    capture = LINUX_MEMBERSHIP_CAPTURE

    assert capture["schema_version"] == 1
    assert capture["status"] == "captured"
    assert capture["client"]["fossil"].startswith("This is fossil version 2.23 ")
    assert capture["client"]["platform"].startswith("Linux-")
    assert capture["inventory"] == MEMBERSHIP_CAPTURE["inventory"]
    assert capture["before_transitions"] == MEMBERSHIP_CAPTURE["before_transitions"]
    assert capture["after_transitions"] == MEMBERSHIP_CAPTURE["after_transitions"]
    assert {case["id"] for case in capture["cases"]} == {
        case["id"] for case in MEMBERSHIP_CAPTURE["cases"]
    }
    assert all(case["candidate_matches"] for case in capture["cases"])

    raw_results = capture["native_results"]
    assert all(result["exit_code"] == 0 for result in raw_results.values())
    root_payload = json.loads(base64.b64decode(raw_results["root_inventory"]["stdout_base64"]))[
        "payload"
    ]
    status_payload = json.loads(
        base64.b64decode(raw_results["transition_status"]["stdout_base64"])
    )["payload"]
    assert (
        sorted(entry["name"] for entry in root_payload["entries"])
        == capture["inventory"]["root_entries"]
    )
    assert {item["name"]: item["status"] for item in status_payload["files"]} == capture[
        "after_transitions"
    ]["status_by_name"]


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
@pytest.mark.parametrize("case", TOKENIZER_CASES, ids=lambda case: case["id"])
def test_fossil_tokenizer_probes_match_captured_observations(
    profile: str, case: dict[str, Any]
) -> None:
    """Keep native-observed tokenizer decisions aligned with the portable parser."""
    capture = CAPTURES[profile]
    observation = next(item for item in capture["cases"] if item["id"] == case["id"])

    assert observation["evidence_status"] == "native-observed"
    probes = observation["setting_probes"]
    assert probes
    for probe in probes:
        patterns = _parse_glob_list(probe["value"])
        actual = any(_matches_glob(probe["query"], pattern) for pattern in patterns)
        assert actual is probe["observed_ignored"], probe
