"""Integrity checks for captured Perforce ignore observations."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from gitignore_walk import IgnoreWalker, PerforceIgnorePolicy
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
    expected_native_error = case.get("expected_native_error")
    if expected_native_error is not None:
        assert expected is None
        assert observation["native_error"] == expected_native_error
        assert expected_native_error in observation["stderr"]
        assert observation["observed_ignored"] is None
        assert observation["candidate_matches"] is None
        assert observation["exit_code"] != 0
        ignore_check = observation["ignore_check"]
        assert ignore_check["exit_code"] == 0
        expected_ignore_match = case.get("expected_ignore_match", True)
        assert ignore_check["observed_ignored"] is expected_ignore_match
        if "expected_ignore_match" in case:
            assert observation["ignore_check_matches"] is True
    elif case.get("capture_where"):
        assert expected is None
        assert observation["observed_ignored"] is None
        assert observation["candidate_matches"] is None
        assert observation["exit_code"] == 0
        assert "file(s) not in client view." in observation["stderr"]
        assert observation["ignore_check"]["observed_ignored"] is False
        assert {
            path: {key: result[key] for key in ("stdout", "stderr")}
            for path, result in observation["where_results"].items()
        } == case["expected_where"]
        assert all(result["exit_code"] == 0 for result in observation["where_results"].values())
        assert {
            path: {key: result["tagged"][key] for key in ("stdout", "stderr")}
            for path, result in observation["where_results"].items()
        } == case["expected_tagged_where"]
        assert all(
            result["tagged"]["exit_code"] == 0 for result in observation["where_results"].values()
        )
        assert observation["ignore_check_matches"] is True
    elif isinstance(expected, bool):
        assert observation["candidate_matches"] is True
        assert observation["observed_ignored"] is expected
    else:
        assert observation["candidate_matches"] is None
        assert isinstance(observation["observed_ignored"], bool)
    if expected_native_error is None:
        assert observation["exit_code"] == (1 if observation["observed_ignored"] else 0)
    client_root_probe = observation.get("client_root_probe")
    assert (client_root_probe is not None) is case.get("capture_client_root", False)
    if client_root_probe is not None:
        assert client_root_probe["exit_code"] == 0
        assert client_root_probe["client_root"] == case["expected_client_root"]
        assert client_root_probe["command"] == ["p4", "-ztag", "info"]
    assert "gitignore-walk-p4-oracle-" not in observation["stdout"] + observation["stderr"]
    walk_preview = observation.get("walk_preview")
    assert (walk_preview is not None) is case.get("capture_walk", False)
    if walk_preview is not None:
        assert walk_preview["exit_code"] == 0


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
@pytest.mark.parametrize("topdown", [True, False], ids=["topdown", "bottomup"])
def test_perforce_walker_matches_recursive_native_add_preview(
    tmp_path: Path, profile: str, topdown: bool
) -> None:
    case_id = "p4.walk-exception-keeps-parent-traversable"
    case = next(case for case in CASES if case["id"] == case_id)
    observation = OBSERVATIONS[profile][case_id]
    root = tmp_path / "workspace"
    root.mkdir()
    for relative, contents in case["setup"]["files"].items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    policy = PerforceIgnorePolicy(root, environment={})
    walker = IgnoreWalker(root, policy=policy)
    preview = observation["walk_preview"]
    native_candidates = {
        line.removeprefix("//depot/").partition("#")[0]
        for line in preview["stdout"].splitlines()
        if line.startswith("//depot/") and line.endswith(" - opened for add")
    }
    all_files = set(case["setup"]["files"])
    included = {
        path.relative_to(root).as_posix()
        for path in walker.iter_files(selection="included", topdown=topdown)
    }
    ignored = {
        path.relative_to(root).as_posix()
        for path in walker.iter_files(selection="ignored", topdown=topdown)
    }

    assert preview["exit_code"] == 0
    assert native_candidates == {".p4ignore", "build/keep.txt", "notes.txt"}
    assert included == native_candidates
    assert ignored == all_files - native_candidates


@pytest.mark.parametrize("profile", CAPTURE_FILES, ids=lambda name: name.removesuffix(".json"))
@pytest.mark.parametrize(
    "case_id",
    [
        "p4.p4config-discovers-ignore-source",
        "p4.p4config-ignore-overrides-environment",
        "p4.nested-p4config-selects-nested-ignore-source",
        "p4.parent-p4config-scope-outside-client-root",
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
    for relative, contents in case["setup"].get("parent_files", {}).items():
        path = root.parent / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    for relative, contents in case["setup"].get("files", {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    query = root / case["query"]
    query.parent.mkdir(parents=True, exist_ok=True)
    query.touch(exist_ok=True)
    query_cwd = query.parent if case.get("query_cwd") == "parent" else root
    p4_set_output = (
        observation["p4_set_output"]
        .replace("<workspace>", str(root))
        .replace("<temp>", str(root.parent))
    )
    client_root_output = observation.get("client_root_probe")
    if client_root_output is not None:
        client_root_output = client_root_output["stdout"].replace("<workspace>", str(root))
    policy_root = query.parent if client_root_output is not None else root

    def captured_p4_set(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command[1:] == ["-ztag", "info"]:
            assert Path(kwargs["cwd"]) == policy_root
            assert client_root_output is not None
            return subprocess.CompletedProcess(command, 0, client_root_output, "")
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
    policy = PerforceIgnorePolicy(
        policy_root,
        environment=environment,
        read_client_config=True,
        discover_client_workspace=client_root_output is not None,
    )

    assert observation["p4_set_exit_code"] == 0
    assert policy.is_ignored(query) is observation["observed_ignored"]
    if case_id == "p4.parent-p4config-scope-outside-client-root":
        trace = policy.trace(query)
        assert trace.decision.ignored is True
        assert trace.matches[0].scope == ".."


@pytest.mark.parametrize("profile", CAPTURE_FILES, ids=lambda name: name.removesuffix(".json"))
def test_perforce_workspace_root_matches_captured_native_client_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    case = next(case for case in CASES if case["id"] == "p4.discovers-client-root-from-descendant")
    observation = OBSERVATIONS[profile][case["id"]]
    workspace = tmp_path / "workspace"
    caller_root = workspace / "sub"
    caller_root.mkdir(parents=True)
    (workspace / ".p4ignore").write_text("*.tmp\n", encoding="utf-8")
    (caller_root / "a.tmp").touch()
    captured_root = observation["client_root_probe"]["stdout"].replace(
        "<workspace>", str(workspace)
    )

    def captured_p4_info(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command[1:] == ["-ztag", "info"]
        assert Path(kwargs["cwd"]) == caller_root
        return subprocess.CompletedProcess(command, 0, captured_root, "")

    monkeypatch.setattr(perforce_policy_module.subprocess, "run", captured_p4_info)
    policy = PerforceIgnorePolicy(caller_root, environment={}, discover_client_workspace=True)

    assert policy.workspace_root == workspace
    assert policy.root == caller_root
    assert policy.explain("a.tmp").ignored is True


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
