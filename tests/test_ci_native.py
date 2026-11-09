"""Regression checks for local and hosted native-CI orchestration."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import ci, ci_native


def write_capture(path: Path, **data: object) -> None:
    path.write_text(
        json.dumps({"status": "captured", "cases": [{"id": "fixture"}], **data}), encoding="utf-8"
    )


def test_prerequisites_are_explicit_and_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    missing = {"p4d", "svnserve"}
    monkeypatch.setattr(ci_native.shutil, "which", lambda tool: None if tool in missing else tool)
    ci_native.require_tools(["hg", "svn", "brz"], include_git=True)
    with pytest.raises(RuntimeError, match="p4d"):
        ci_native.require_tools(ci_native.BACKENDS)


@pytest.mark.parametrize("backends", [[], ["unknown"]])
def test_invalid_backend_selection_is_rejected(backends: list[str]) -> None:
    with pytest.raises(ValueError):
        ci_native.require_tools(backends)


def test_git_is_required_for_pre_push(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ci_native.shutil, "which", lambda tool: None if tool == "git" else tool)
    with pytest.raises(RuntimeError, match="git"):
        ci_native.require_tools(["hg"], include_git=True)


@pytest.mark.parametrize("status", ["skipped", "failed", "unknown", None])
def test_uncaptured_primary_oracle_is_not_a_pass(tmp_path: Path, status: object) -> None:
    path = tmp_path / "capture.json"
    write_capture(path, status=status)
    assert not ci_native.inspect_capture(path)["passed"]


def test_explicit_auxiliary_skip_is_visible(tmp_path: Path) -> None:
    path = tmp_path / "capture.json"
    write_capture(path, status="skipped", reason="unsupported platform")
    result = ci_native.inspect_capture(path, allow_skip=True)
    assert result["passed"]
    assert result["status"] == "skipped"
    assert result["reason"] == "unsupported platform"


@pytest.mark.parametrize("contents", ["not json", "[]", '{"cases": [1]}'])
def test_malformed_capture_fails(tmp_path: Path, contents: str) -> None:
    path = tmp_path / "capture.json"
    path.write_text(contents, encoding="utf-8")
    assert not ci_native.inspect_capture(path)["passed"]


def test_empty_primary_capture_fails(tmp_path: Path) -> None:
    path = tmp_path / "capture.json"
    write_capture(path, cases=[])
    assert not ci_native.inspect_capture(path)["passed"]


def test_missing_capture_fails(tmp_path: Path) -> None:
    assert not ci_native.inspect_capture(tmp_path / "absent.json")["passed"]


def test_candidate_mismatches_fail_but_open_cases_do_not(tmp_path: Path) -> None:
    path = tmp_path / "capture.json"
    write_capture(path, cases=[{"id": "research", "candidate_matches": None}])
    assert ci_native.inspect_capture(path)["passed"]
    write_capture(path, cases=[{"id": "regression", "candidate_matches": False}])
    result = ci_native.inspect_capture(path)
    assert not result["passed"]
    assert result["mismatches"] == ["regression"]


def test_darcs_boolean_mismatch_fails(tmp_path: Path) -> None:
    path = tmp_path / "capture.json"
    write_capture(path, cases=[{"id": "darcs", "expected_boring": True, "observed_boring": False}])
    assert not ci_native.inspect_capture(path)["passed"]


def test_case_skips_remain_visible(tmp_path: Path) -> None:
    path = tmp_path / "capture.json"
    write_capture(path, cases=[{"id": "platform-only", "native_status": "skipped"}])
    result = ci_native.inspect_capture(path)
    assert result["passed"]
    assert result["skipped_cases"] == ["platform-only"]


def test_hg_captures_matching_walking_and_trust(tmp_path: Path) -> None:
    arguments, paths = ci_native.capture_arguments("hg", tmp_path)
    assert len(paths) == 3
    assert "--walk-output" in arguments
    assert "--trust-output" in arguments


def test_native_continues_after_failure_and_uses_fresh_captures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ci_native.shutil, "which", lambda tool: tool)
    calls: list[str] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command[3])
        path = Path(command[command.index("--output") + 1])
        if command[3] == "oracle-fossil":
            write_capture(path)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(ci_native.subprocess, "run", run)
    monkeypatch.setattr(ci_native.platform, "platform", lambda: "test-platform")
    for _ in range(2):
        assert ci_native.run_native(tmp_path, ["svn", "fossil"], tmp_path / "runs") == 1
    summaries = sorted((tmp_path / "runs").glob("native-*/summary.json"))
    assert len(summaries) == 2
    assert calls == ["oracle-svn", "oracle-fossil"] * 2
    for path in summaries:
        result = json.loads(path.read_text())
        assert result["status"] == "failed"
        assert [backend["passed"] for backend in result["backends"]] == [False, True]


def test_command_failure_cannot_be_hidden_by_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ci_native.shutil, "which", lambda tool: tool)

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        write_capture(Path(command[command.index("--output") + 1]))
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(ci_native.subprocess, "run", run)
    monkeypatch.setattr(ci_native.platform, "platform", lambda: "test-platform")
    assert ci_native.run_native(tmp_path, ["svn"], tmp_path / "runs") == 1


def test_summary_distinguishes_pass_with_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ci_native.shutil, "which", lambda tool: tool)

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        write_capture(
            Path(command[command.index("--output") + 1]),
            cases=[{"id": "platform-only", "native_status": "skipped"}],
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(ci_native.subprocess, "run", run)
    monkeypatch.setattr(ci_native.platform, "platform", lambda: "test-platform")
    assert ci_native.run_native(tmp_path, ["svn"], tmp_path / "runs") == 0
    result = json.loads(next((tmp_path / "runs").glob("native-*/summary.json")).read_text())
    assert result["status"] == "passed_with_skips"


def test_pre_push_runs_core_before_native(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    steps: list[str] = []
    monkeypatch.setattr(ci, "setup_env", lambda: None)
    monkeypatch.setattr(ci, "require_tools", lambda *_args, **_kwargs: steps.append("tools"))
    monkeypatch.setattr(ci, "_test", lambda _python: steps.append("tests") or 0)
    monkeypatch.setattr(ci, "_quality", lambda: steps.append("quality") or 0)
    monkeypatch.setattr(ci, "_package", lambda: steps.append("package") or 0)
    monkeypatch.setattr(ci, "run_native", lambda *_args, **_kwargs: steps.append("native") or 0)
    assert ci.main(["pre-push", "--backends", "svn", "--output-dir", str(tmp_path)]) == 0
    assert steps == ["tools", "tests", "quality", "package", "native"]


def test_pre_push_stops_when_core_checks_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ci, "setup_env", lambda: None)
    monkeypatch.setattr(ci, "require_tools", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ci, "_test", lambda _python: 3)
    monkeypatch.setattr(ci, "_quality", lambda: pytest.fail("must not run after failed tests"))
    assert ci.main(["pre-push"]) == 3


def test_pytest_runs_have_distinct_temporary_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots: list[str] = []
    monkeypatch.setattr(ci, "test_temp", lambda: tmp_path)
    monkeypatch.setattr(ci, "_python_version", lambda _python: "3.12")

    def run(command: list[str], **_kwargs: object) -> int:
        roots.append(command[command.index("--basetemp") + 1])
        return 0

    monkeypatch.setattr(ci, "_run", run)
    assert ci._test("python") == ci._test("python") == 0
    assert roots[0] != roots[1]
    assert all(Path(root).parent == tmp_path for root in roots)


@pytest.mark.parametrize(
    "case",
    [
        {
            "expected_candidate": False,
            "observed_ignored": None,
            "candidate_matches": None,
            "exit_code": 255,
        },
        {"expected_candidate": {"ignored": True}, "candidate_matches": None},
        {"expected_ignored_paths": [], "candidate_matches": None},
        {
            "expected_candidate": False,
            "candidate_matches": True,
            "ignored_exit_code": 3,
            "status_exit_code": 3,
        },
    ],
)
def test_closed_query_errors_do_not_pass(tmp_path: Path, case: dict[str, object]) -> None:
    path = tmp_path / "capture.json"
    write_capture(path, cases=[{"id": "closed", **case}])
    assert not ci_native.inspect_capture(path)["passed"]


def test_open_invalid_pattern_probe_is_not_a_boolean_failure(tmp_path: Path) -> None:
    path = tmp_path / "capture.json"
    write_capture(
        path,
        cases=[
            {
                "id": "open",
                "expected_candidate": None,
                "candidate_matches": None,
                "ignored_exit_code": 3,
            }
        ],
    )
    assert ci_native.inspect_capture(path)["passed"]


def test_observed_hg_fallback_is_not_rejected_for_debug_command_exit(tmp_path: Path) -> None:
    path = tmp_path / "capture.json"
    write_capture(
        path,
        cases=[
            {
                "id": "fallback",
                "expected_candidate": False,
                "candidate_matches": True,
                "exit_code": 1,
                "observation_method": "status-membership",
            }
        ],
    )
    assert ci_native.inspect_capture(path)["passed"]


@pytest.mark.parametrize("exit_code", [0, 1])
def test_pytest_retains_only_failed_run_temporary_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit_code: int
) -> None:
    monkeypatch.setattr(ci, "test_temp", lambda: tmp_path)
    monkeypatch.setattr(ci, "_python_version", lambda _python: "3.12")
    monkeypatch.setattr(ci, "_run", lambda *_args, **_kwargs: exit_code)
    assert ci._test("python") == exit_code
    assert bool(list(tmp_path.iterdir())) is bool(exit_code)


def test_privileged_trust_probe_is_explicitly_opt_in(tmp_path: Path) -> None:
    local, _ = ci_native.capture_arguments("hg", tmp_path)
    hosted, _ = ci_native.capture_arguments("hg", tmp_path, include_trust=True)
    assert "--skip-trust" in local
    assert "--skip-trust" not in hosted


def test_skipping_trust_records_skip_without_launching_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runners: list[str] = []

    def run(command: list[str], **_kwargs: object) -> int:
        runners.append(Path(command[1]).name)
        return 0

    monkeypatch.setattr(ci, "_run", run)
    trust = tmp_path / "trust.json"
    assert (
        ci._oracle_hg("hg", tmp_path / "match.json", tmp_path / "walk.json", trust, skip_trust=True)
        == 0
    )
    assert runners == ["run.py", "walk.py"]
    assert json.loads(trust.read_text())["status"] == "skipped"
