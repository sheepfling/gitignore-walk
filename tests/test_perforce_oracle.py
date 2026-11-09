"""Integrity checks for captured Perforce ignore observations."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from gitignore_walk import PerforceIgnorePolicy
from gitignore_walk._schemes.perforce import policy as perforce_policy_module

ORACLE_ROOT = Path(__file__).parent / "oracles" / "perforce"
CASES = json.loads((ORACLE_ROOT / "cases.json").read_text(encoding="utf-8"))["cases"]
CAPTURE_FILES = (
    "p4-2026.1-macos-arm64.json",
    "p4-2026.1-linux-x86_64.json",
    "p4-2026.1-linux-ubuntu24.04-x86_64.json",
)
CAPTURES = {
    profile: json.loads((ORACLE_ROOT / "results" / profile).read_text(encoding="utf-8"))
    for profile in CAPTURE_FILES
}
OBSERVATIONS = {
    profile: {case["id"]: case for case in capture["cases"]}
    for profile, capture in CAPTURES.items()
}


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
@pytest.mark.parametrize("profile", CAPTURE_FILES, ids=lambda name: name.removesuffix(".json"))
def test_perforce_capture_matches_versioned_candidates(case: dict[str, Any], profile: str) -> None:
    capture = CAPTURES[profile]
    observation = OBSERVATIONS[profile][case["id"]]

    assert capture["status"] == "captured"
    assert observation["isolated_configuration"] is True
    expected = case["expected_candidate"]
    if isinstance(expected, bool):
        assert observation["candidate_matches"] is True
        assert observation["observed_ignored"] is expected
    else:
        assert observation["candidate_matches"] is None
        assert isinstance(observation["observed_ignored"], bool)
    assert observation["exit_code"] == (1 if observation["observed_ignored"] else 0)
    assert "gitignore-walk-p4-oracle-" not in observation["stdout"] + observation["stderr"]


@pytest.mark.parametrize("profile", CAPTURE_FILES, ids=lambda name: name.removesuffix(".json"))
def test_perforce_profile_is_server_backed_and_pinned(profile: str) -> None:
    capture = CAPTURES[profile]
    assert capture["client"]["version"].startswith("P4/"), capture["client"]
    assert all(case["server_version"].startswith("P4D/") for case in capture["cases"])
    assert all(case["exit_code"] in (0, 1) for case in capture["cases"])
    if "linux" in profile:
        assert capture["client"]["version"].startswith("P4/LINUX26X86_64/")
        assert capture["client"]["platform"].startswith("Linux-")
    else:
        assert capture["client"]["version"].startswith("P4/MACOSX12ARM64/")
        assert capture["client"]["platform"].startswith("macOS-")


@pytest.mark.parametrize("profile", CAPTURE_FILES, ids=lambda name: name.removesuffix(".json"))
@pytest.mark.parametrize(
    "case_id",
    [
        "p4.p4config-discovers-ignore-source",
        "p4.p4config-ignore-overrides-environment",
        "p4.nested-p4config-selects-nested-ignore-source",
    ],
)
def test_perforce_policy_matches_captured_p4config_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    case_id: str,
) -> None:
    case = next(case for case in CASES if case["id"] == case_id)
    observation = OBSERVATIONS[profile][case_id]
    root = tmp_path / "workspace"
    root.mkdir()
    for relative, contents in case["setup"].get("files", {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    query = root / case["query"]
    query.parent.mkdir(parents=True, exist_ok=True)
    query.touch(exist_ok=True)
    query_cwd = query.parent if case.get("query_cwd") == "parent" else root
    p4_set_output = observation["p4_set_output"].replace("<workspace>", str(root))

    def captured_p4_set(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command[1:] == ["set"]
        assert Path(kwargs["cwd"]) == query_cwd
        return subprocess.CompletedProcess(command, 0, p4_set_output, "")

    monkeypatch.setattr(perforce_policy_module.subprocess, "run", captured_p4_set)
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "P4CONFIG": case["setup"]["P4CONFIG"],
    }
    if "P4IGNORE" in case["setup"]:
        environment["P4IGNORE"] = case["setup"]["P4IGNORE"]
    policy = PerforceIgnorePolicy(root, environment=environment, read_client_config=True)

    assert observation["p4_set_exit_code"] == 0
    assert policy.is_ignored(case["query"]) is observation["observed_ignored"]


def test_perforce_config_settings_are_resolved_once_per_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / ".p4config").write_text("P4IGNORE=.p4ignore\n", encoding="utf-8")
    (root / ".p4ignore").write_text("*.tmp\n", encoding="utf-8")
    output = f"P4IGNORE=.p4ignore (config '{root}/.p4config')\n"
    calls = 0

    def captured_p4_set(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(perforce_policy_module.subprocess, "run", captured_p4_set)
    policy = PerforceIgnorePolicy(
        root, environment={"P4CONFIG": ".p4config"}, read_client_config=True
    )

    decisions = policy.explain_many(["one.tmp", "two.tmp"])

    assert [decision.ignored for decision in decisions] == [True, True]
    assert calls == 1


def test_custom_p4config_filename_is_a_builtin_exclusion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    config_name = "client.settings"
    (root / config_name).write_text("", encoding="utf-8")

    def captured_p4_set(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command[1:] == ["set"]
        assert Path(kwargs["cwd"]) == root
        output = f"P4CONFIG={config_name} (enviro)\n"
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(perforce_policy_module.subprocess, "run", captured_p4_set)
    policy = PerforceIgnorePolicy(root, environment={"PATH": ""}, read_client_config=True)

    decision = policy.explain(config_name)

    assert decision.ignored is True
    assert decision.source == "Perforce built-in defaults"
    assert decision.pattern == config_name
