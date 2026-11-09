"""Portable Git-policy regressions imported from the native research handoff."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from gitignore_walk import GitIgnorePolicy, GitStandardPolicy

ORACLE = Path(__file__).parent / "oracles" / "git" / "research_cases.json"
INVENTORY = json.loads(ORACLE.read_text(encoding="utf-8"))
CASES: list[dict[str, Any]] = INVENTORY["cases"]
TARGET_SUITES = {
    "observation-only; see coverage-status field",
    "tests/test_git_research.py::test_portable_git_policy_matches_imported_research_case",
    "tests/test_git_research.py::test_portable_git_policy_matches_non_utf8_path_candidate",
    "tests/test_git_research.py::test_native_git_policy_matches_configured_research_case",
    "tests/test_git_research.py::test_native_policy_reports_rule_match_even_for_tracked_paths",
}
PORTABLE_EXCLUDED = {
    # These are checked through GitStandardPolicy or retained as observation-only behavior.
    "git.custom_config_excludes",
    "git.configured_case_insensitive",
    "git.tracked_default",
    "git.tracked_no_index",
    "git.worktree_common_excludes",
    "git.observe_nul_in_rule",
}


def _decode_spec(spec: dict[str, Any], name: str) -> bytes:
    encoded = spec.get(f"{name}_base64")
    if encoded is not None:
        return base64.b64decode(encoded, validate=True)
    return str(spec.get(name, "")).encode("utf-8")


def _path(root: Path, value: str | bytes) -> Path:
    return root / os.fsdecode(value)


def _write_specs(root: Path, specifications: list[dict[str, Any]]) -> None:
    for specification in specifications:
        path = _path(root, _decode_spec(specification, "path"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_decode_spec(specification, "content"))


def _make_case(root: Path, case: dict[str, Any]) -> GitIgnorePolicy:
    root.mkdir()
    metadata = root / ".git"
    (metadata / "info").mkdir(parents=True)
    home = root.parent / "home"
    home.mkdir()
    _write_specs(root, case.get("files", []))
    _write_specs(home, case.get("home_files", []))
    for relative in case.get("directories", []):
        _path(root, relative).mkdir(parents=True, exist_ok=True)
    for symlink in case.get("symlinks", []):
        link = _path(root, _decode_spec(symlink, "path"))
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(symlink["target"], target_is_directory=bool(symlink.get("directory")))
    return GitIgnorePolicy(
        root,
        environment={
            "HOME": str(home),
            "USERPROFILE": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
        },
    )


def _isolated_git_environment(home: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_") and key not in {"HOME", "USERPROFILE", "XDG_CONFIG_HOME"}
    }
    environment.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
            "LANG": "C",
            "TZ": "UTC",
        }
    )
    return environment


def _run_git(root: Path, environment: dict[str, str], *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *arguments],
        env=environment,
        capture_output=True,
        check=True,
        timeout=30,
    )


def _make_native_case(root: Path, case: dict[str, Any]) -> tuple[Path, dict[str, str]]:
    root.mkdir()
    home = root.parent / "home"
    home.mkdir()
    environment = _isolated_git_environment(home)
    _run_git(root, environment, "init", "--initial-branch=master", "--quiet", "--template=")
    _write_specs(root, case.get("before_tracking", []))
    for tracked in case.get("track", []):
        _run_git(root, environment, "add", "--", tracked)
    _write_specs(root, case.get("files", []))
    _write_specs(home, case.get("home_files", []))
    for relative in case.get("directories", []):
        _path(root, relative).mkdir(parents=True, exist_ok=True)
    for symlink in case.get("symlinks", []):
        link = _path(root, _decode_spec(symlink, "path"))
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(symlink["target"], target_is_directory=bool(symlink.get("directory")))
    for name, value in case.get("config", {}).items():
        _run_git(root, environment, "config", name, str(value))
    if case.get("worktree"):
        _run_git(
            root,
            environment,
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--allow-empty",
            "--quiet",
            "-m",
            "fixture",
        )
        worktree = root.parent / "linked"
        _run_git(
            root,
            environment,
            "worktree",
            "add",
            "--quiet",
            "-b",
            "fixture-branch",
            str(worktree),
        )
        root = worktree
        _write_specs(root, case.get("worktree_files", []))
    return root, environment


def test_git_research_inventory_is_complete_and_classified() -> None:
    """Keep the imported research cases uniquely identified and routed to a coverage suite."""
    ids = [case["id"] for case in CASES]
    assert len(ids) == INVENTORY["case_count"] == 79
    assert len(ids) == len(set(ids))
    assert sum(case.get("expected_ignored") is not None for case in CASES) == 78
    assert sum(case.get("expected_ignored") is None for case in CASES) == 1
    assert all(case.get("target_area") and case.get("target_suite") for case in CASES)
    assert all(case["target_suite"] in TARGET_SUITES for case in CASES)
    assert all(case.get("evidence_status") for case in CASES)
    assert all(case.get("coverage_status") for case in CASES)
    assert INVENTORY["portable_coverage"]["passed_cases"] == 72


@pytest.mark.parametrize(
    "case",
    [
        case
        for case in CASES
        if case["id"] not in PORTABLE_EXCLUDED
        and case.get("expected_ignored") is not None
        and case["id"] != "git.non_utf8_path"
    ],
    ids=lambda case: case["id"],
)
def test_portable_git_policy_matches_imported_research_case(
    tmp_path: Path, case: dict[str, Any]
) -> None:
    """Check the portable evaluator against supported native Git research candidates."""
    policy = _make_case(tmp_path / "repo", case)
    query = os.fsdecode(_decode_spec(case, "query"))
    if case.get("cwd"):
        query = (Path(case["cwd"]) / query).as_posix()

    trace = policy.trace(query)

    assert trace.decision.ignored is case["expected_ignored"]
    if expected_source := case.get("expected_source"):
        assert trace.decision.source is not None
        assert trace.decision.source.endswith(expected_source)
    if expected_pattern := case.get("expected_pattern"):
        effective = next(match for match in trace.matches if match.effective)
        assert effective.pattern == expected_pattern


@pytest.mark.parametrize(
    "case_id",
    [
        "git.custom_config_excludes",
        "git.configured_case_insensitive",
        "git.worktree_common_excludes",
    ],
)
def test_native_git_policy_matches_configured_research_case(tmp_path: Path, case_id: str) -> None:
    """Check Git-owned config and common-worktree source discovery in the native policy."""
    case = next(case for case in CASES if case["id"] == case_id)
    root, environment = _make_native_case(tmp_path / "repo", case)
    query = os.fsdecode(_decode_spec(case, "query"))

    decision = GitStandardPolicy(root, environment=environment).explain(query)

    assert decision.ignored is case["expected_ignored"]


@pytest.mark.parametrize("case_id", ["git.tracked_default", "git.tracked_no_index"])
def test_native_policy_reports_rule_match_even_for_tracked_paths(
    tmp_path: Path, case_id: str
) -> None:
    """Keep tracked membership separate because GitStandardPolicy always asks --no-index."""
    case = next(case for case in CASES if case["id"] == case_id)
    root, environment = _make_native_case(tmp_path / "repo", case)
    query = os.fsdecode(_decode_spec(case, "query"))

    decision = GitStandardPolicy(root, environment=environment).explain(query)

    assert decision.ignored
    # The native handoff fixture without --no-index reports index membership as well as rules.
    if case_id == "git.tracked_default":
        assert case["expected_ignored"] is False
    else:
        assert case["expected_ignored"] is True


@pytest.mark.skipif(
    os.name != "posix" or sys.platform == "darwin", reason="requires Linux byte paths"
)
def test_portable_git_policy_matches_non_utf8_path_candidate(tmp_path: Path) -> None:
    """Exercise the byte-path case on Linux, where undecodable filenames are supported."""
    case = next(case for case in CASES if case["id"] == "git.non_utf8_path")
    policy = _make_case(tmp_path / "repo", case)
    query = os.fsdecode(_decode_spec(case, "query"))

    assert policy.is_ignored(query) is case["expected_ignored"]
