"""P4IGNORE parser, policy selection, and conservative traversal tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from gitignore_walk import (
    IgnoreWalker,
    PerforceIgnoreError,
    PerforceIgnorePolicy,
    PerforcePolicyConfig,
    PerforcePolicySelection,
    select_policy,
)
from gitignore_walk._schemes.perforce import policy as perforce_policy_module

ORACLE_ROOT = Path(__file__).parent / "oracles" / "perforce"
CASES: list[dict[str, Any]] = json.loads((ORACLE_ROOT / "cases.json").read_text(encoding="utf-8"))[
    "cases"
]
CAPTURE_FILES = (
    "p4-2026.1-macos-arm64.json",
    "p4-2026.1-linux-x86_64.json",
    "p4-2026.1-linux-ubuntu24.04-x86_64.json",
)
OBSERVATIONS = {
    profile: {
        case["id"]: case
        for case in json.loads((ORACLE_ROOT / "results" / profile).read_text(encoding="utf-8"))[
            "cases"
        ]
    }
    for profile in CAPTURE_FILES
}


def _policy_for_case(root: Path, case: dict[str, Any]) -> PerforceIgnorePolicy:
    root.mkdir(parents=True, exist_ok=True)
    for relative, contents in case["setup"].get("parent_files", {}).items():
        path = root.parent / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as stream:
            stream.write(contents)
    for relative, contents in case["setup"].get("files", {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as stream:
            stream.write(contents)
    target = root / case["query"]
    target.parent.mkdir(parents=True, exist_ok=True)
    if "\n" not in case["query"] and not target.exists():
        target.touch()
    environment = {}
    if "P4IGNORE" in case["setup"]:
        environment["P4IGNORE"] = case["setup"]["P4IGNORE"]
    if "P4CONFIG" in case["setup"]:
        environment["P4CONFIG"] = case["setup"]["P4CONFIG"]
    return PerforceIgnorePolicy(root, environment=environment)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
@pytest.mark.parametrize("profile", CAPTURE_FILES, ids=lambda name: name.removesuffix(".json"))
def test_perforce_policy_matches_captured_native_observation(
    tmp_path: Path, case: dict[str, Any], profile: str
) -> None:
    if case["dimension"].startswith("configuration-"):
        pytest.skip("P4CONFIG observations are exercised with captured `p4 set` output")
    policy = _policy_for_case(tmp_path / "workspace", case)
    observation = OBSERVATIONS[profile][case["id"]]
    ignore_check = observation.get("ignore_check")
    observed = (
        ignore_check["observed_ignored"]
        if ignore_check is not None
        else observation["observed_ignored"]
    )
    assert observation["candidate_matches"] is not False
    platform_expectations = case.get("expected_by_platform")
    if platform_expectations is not None:
        native_platform = "macos" if "macos" in profile else "linux"
        assert observed is platform_expectations[native_platform]
        if sys.platform == "darwin":
            local_platform = "macos"
        elif sys.platform == "linux":
            local_platform = "linux"
        else:
            local_platform = None
        if local_platform != native_platform:
            pytest.skip("native P4 ignore case result depends on filesystem case behavior")

    assert policy.explain(case["query"]).ignored is observed
    if ignore_check is not None:
        assert ignore_check["observed_ignored"] is observed


def test_perforce_selection_is_discriminated_and_scheme_local(tmp_path: Path) -> None:
    (tmp_path / ".p4ignore").write_text("*.tmp\n", encoding="utf-8")

    selection = select_policy(tmp_path, PerforcePolicyConfig(environment={}))

    assert isinstance(selection, PerforcePolicySelection)
    assert isinstance(selection.policy, PerforceIgnorePolicy)
    assert selection.mode == "perforce"
    assert selection.backend == "perforce-python"
    assert selection.policy.scheme == "perforce"


def test_perforce_can_discover_workspace_without_widening_caller_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    caller_root = workspace / "sub"
    caller_root.mkdir(parents=True)
    (workspace / ".p4ignore").write_text("*.tmp\n", encoding="utf-8")
    target = caller_root / "a.tmp"
    target.touch()

    def captured_p4_info(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command[1:] == ["-ztag", "info"]
        assert Path(kwargs["cwd"]) == caller_root
        assert kwargs["env"] == {"P4CLIENT": "client"}
        return subprocess.CompletedProcess(command, 0, f"... clientRoot {workspace}\n", "")

    monkeypatch.setattr(perforce_policy_module.subprocess, "run", captured_p4_info)
    selection = select_policy(
        caller_root,
        PerforcePolicyConfig(environment={"P4CLIENT": "client"}, discover_client_workspace=True),
    )

    assert isinstance(selection.policy, PerforceIgnorePolicy)
    assert selection.policy.root == caller_root
    assert selection.policy.workspace_root == workspace
    decision = selection.policy.trace("a.tmp")
    assert decision.decision.ignored is True
    assert decision.matches[0].scope == "."
    with pytest.raises(ValueError, match="inside policy root"):
        selection.policy.explain("../outside.tmp")


def test_perforce_client_view_filters_files_without_pruning_unmapped_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "main").mkdir(parents=True)
    (workspace / "main" / "visible.txt").touch()
    (workspace / "main" / "private").mkdir()
    (workspace / "main" / "private" / "secret.txt").touch()
    (workspace / "outside.txt").touch()
    where_paths: list[Path] = []

    def captured_p4(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        if command[1:] == ["-ztag", "info"]:
            return subprocess.CompletedProcess(command, 0, f"... clientRoot {workspace}\n", "")
        assert command[1:3] == ["-ztag", "where"]
        path = Path(command[3])
        where_paths.append(path)
        relative = path.relative_to(workspace).as_posix()
        if relative == "main/visible.txt":
            output = (
                "... depotFile //depot/main/visible.txt\n"
                "... clientFile //client/main/visible.txt\n"
                f"... path {path}\n\n"
            )
            return subprocess.CompletedProcess(command, 0, output, "")
        if relative == "main/private/secret.txt":
            output = (
                "... unmap \n"
                "... depotFile //depot/main/private/secret.txt\n"
                "... clientFile //client/main/private/secret.txt\n"
                f"... path {path}\n\n"
            )
            return subprocess.CompletedProcess(command, 0, output, "")
        return subprocess.CompletedProcess(
            command, 0, "", f"{relative} - file(s) not in client view.\n"
        )

    monkeypatch.setattr(perforce_policy_module.subprocess, "run", captured_p4)
    selection = select_policy(
        workspace,
        PerforcePolicyConfig(
            environment={"P4CLIENT": "client"},
            discover_client_workspace=True,
            client_view_aware=True,
        ),
    )
    assert isinstance(selection, PerforcePolicySelection)
    policy = selection.policy

    selected = {
        path.relative_to(workspace).as_posix()
        for path in IgnoreWalker(workspace, policy=policy).iter_files()
    }

    assert selected == {"main/visible.txt"}
    assert {path.relative_to(workspace).as_posix() for path in where_paths} == {
        "main/visible.txt",
        "main/private/secret.txt",
        "outside.txt",
    }
    assert policy.explain("main/private/secret.txt").ignored is False


def test_perforce_client_view_filter_requires_client_workspace_discovery(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="client_view_aware requires discover_client_workspace"):
        PerforceIgnorePolicy(tmp_path, client_view_aware=True)


def test_perforce_workspace_discovery_requires_a_tagged_client_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing_client_root(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "... clientName client\n", "")

    monkeypatch.setattr(perforce_policy_module.subprocess, "run", missing_client_root)

    with pytest.raises(PerforceIgnoreError, match="no tagged clientRoot") as error:
        PerforceIgnorePolicy(tmp_path, environment={}, discover_client_workspace=True)

    assert error.value.operation == "workspace"


def test_perforce_leading_slash_anchors_to_the_nested_ignore_file(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    nested = root / "sub"
    nested.mkdir(parents=True)
    (nested / ".p4ignore").write_text("/config/*.tmp\n", encoding="utf-8")
    policy = PerforceIgnorePolicy(root, environment={})

    direct = policy.trace("sub/config/a.tmp")
    deeper = policy.explain("sub/nested/config/a.tmp")

    assert direct.decision.ignored is True
    assert direct.matches[0].scope == "sub"
    assert deeper.ignored is False


@pytest.mark.parametrize("topdown", [True, False])
def test_perforce_exceptions_keep_ignored_parent_traversable(tmp_path: Path, topdown: bool) -> None:
    root = tmp_path / "workspace"
    build = root / "build"
    build.mkdir(parents=True)
    keep = build / "keep"
    drop = build / "drop"
    keep.touch()
    drop.touch()
    (root / ".p4ignore").write_text("build/\n!build/keep\n", encoding="utf-8")
    policy = PerforceIgnorePolicy(root, environment={})
    directory_decision = policy.explain("build")

    assert directory_decision.ignored is True
    assert policy.explain("build/keep").ignored is False
    assert policy.explain("build/drop").ignored is True
    assert policy.can_prune_ignored_directory(build, directory_decision) is False
    selected = set(IgnoreWalker(root, policy=policy).iter_files(topdown=topdown))
    assert keep in selected
    assert drop not in selected


def test_perforce_trace_marks_the_last_matching_rule_effective(tmp_path: Path) -> None:
    (tmp_path / ".p4ignore").write_text("*.tmp\n!keep.tmp\n", encoding="utf-8")
    policy = PerforceIgnorePolicy(tmp_path, environment={})

    trace = policy.trace("keep.tmp")

    assert trace.decision.ignored is False
    assert [match.effective for match in trace.matches] == [False, True]
    assert [match.ignored for match in trace.matches] == [True, False]


def test_perforce_trace_marks_the_first_configured_source_effective(tmp_path: Path) -> None:
    (tmp_path / "first").write_text("*.tmp\n", encoding="utf-8")
    (tmp_path / "second").write_text("!*.tmp\n", encoding="utf-8")
    policy = PerforceIgnorePolicy(
        tmp_path,
        environment={"P4IGNORE": "first;second"},
    )

    trace = policy.trace("build.tmp")

    assert trace.decision.ignored is True
    assert [match.effective for match in trace.matches] == [True, False]
    assert [match.ignored for match in trace.matches] == [True, False]


def test_perforce_policy_reports_source_read_failures(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad.ignore"
    bad_file.write_bytes(b"\xff")
    policy = PerforceIgnorePolicy(
        tmp_path,
        environment={"P4IGNORE": "bad.ignore"},
    )

    with pytest.raises(PerforceIgnoreError, match="Unable to read Perforce ignore source"):
        policy.explain("target")
