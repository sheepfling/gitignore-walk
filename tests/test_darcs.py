"""Native Darcs boring policy and conservative traversal tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from gitignore_walk import (
    DarcsBoringError,
    DarcsBoringPolicy,
    DarcsPolicyConfig,
    DarcsPolicySelection,
    IgnoreWalker,
    select_policy,
)
from gitignore_walk._schemes.darcs import policy as darcs_policy_module

DARCS_ORACLE_CASES = json.loads(
    (Path(__file__).parent / "oracles" / "darcs" / "cases.json").read_text(encoding="utf-8")
)["cases"]


def test_darcs_policy_uses_managed_and_add_candidate_inventories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[1:] == ["whatsnew", "--look-for-adds", "--summary"]:
            return subprocess.CompletedProcess(
                command, 0, "a ./new.txt\na ./cache/\n", "Warning: example\n"
            )
        if command[1:] == ["show", "files", "--null"]:
            return subprocess.CompletedProcess(command, 0, ".\0./tracked.tmp\0", "")
        raise AssertionError(command)

    monkeypatch.setattr(darcs_policy_module.subprocess, "run", run)
    policy = DarcsBoringPolicy(tmp_path, environment={})

    decisions = policy.explain_many(["new.txt", "tracked.tmp", "ignored.tmp", "cache"])

    assert [decision.ignored for decision in decisions] == [False, False, True, False]
    assert decisions[0].reason == "add-candidate"
    assert decisions[1].reason == "managed-path"
    assert decisions[2].reason == "boring-path"
    assert decisions[0].diagnostics[0].message == "Warning: example"
    assert calls == [
        ["darcs", "whatsnew", "--look-for-adds", "--summary"],
        ["darcs", "show", "files", "--null"],
    ]


def test_darcs_policy_accepts_no_changes_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if command[1] == "whatsnew":
            return subprocess.CompletedProcess(command, 1, "No changes!\n", "")
        return subprocess.CompletedProcess(command, 0, ".\0", "")

    monkeypatch.setattr(darcs_policy_module.subprocess, "run", run)
    policy = DarcsBoringPolicy(tmp_path, environment={})

    assert [decision.ignored for decision in policy.explain_many(["a", "b"])] == [True, True]
    assert calls == 2


def test_darcs_managed_inventory_uses_nul_path_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command[1] == "whatsnew":
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[1:] == ["show", "files", "--null"]:
            return subprocess.CompletedProcess(command, 0, ".\0./tracked\nname.tmp \0", "")
        raise AssertionError(command)

    monkeypatch.setattr(darcs_policy_module.subprocess, "run", run)
    policy = DarcsBoringPolicy(tmp_path, environment={})

    decision = policy.explain("tracked\nname.tmp ")

    assert decision.ignored is False
    assert decision.reason == "managed-path"


def test_darcs_ambiguous_candidate_output_uses_targeted_native_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[1:4] == ["whatsnew", "--look-for-adds", "--summary"]:
            return subprocess.CompletedProcess(command, 0, "a ./line\nbreak.txt\n", "")
        if command[1:] == ["show", "files", "--null"]:
            return subprocess.CompletedProcess(command, 0, ".\0", "")
        if command[1:] == ["add", "--dry-run", "--reserved-ok", "--", "line\nbreak.txt"]:
            return subprocess.CompletedProcess(command, 0, "Would add './line\nbreak.txt'\n", "")
        raise AssertionError(command)

    monkeypatch.setattr(darcs_policy_module.subprocess, "run", run)
    policy = DarcsBoringPolicy(tmp_path, environment={})

    decision = policy.explain("line\nbreak.txt")

    assert decision.ignored is False
    assert decision.reason == "add-candidate"
    assert decision.source == "darcs add --dry-run --reserved-ok"
    assert calls[-1] == [
        "darcs",
        "add",
        "--dry-run",
        "--reserved-ok",
        "--",
        "line\nbreak.txt",
    ]


def test_darcs_targeted_query_preserves_boring_decision_for_control_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command[1] == "whatsnew":
            return subprocess.CompletedProcess(command, 0, "a ./line\nbreak.tmp\n", "")
        if command[1:] == ["show", "files", "--null"]:
            return subprocess.CompletedProcess(command, 0, ".\0", "")
        if command[1] == "add":
            return subprocess.CompletedProcess(
                command, 2, "", "Would skip boring file ./line\nbreak.tmp\nNo files were added\n"
            )
        raise AssertionError(command)

    monkeypatch.setattr(darcs_policy_module.subprocess, "run", run)
    policy = DarcsBoringPolicy(tmp_path, environment={})

    decision = policy.explain("line\nbreak.tmp")

    assert decision.ignored is True
    assert decision.reason == "boring-path"


def test_darcs_policy_reports_native_command_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 2, "", "not a repository")

    monkeypatch.setattr(darcs_policy_module.subprocess, "run", run)
    policy = DarcsBoringPolicy(tmp_path, environment={})

    with pytest.raises(DarcsBoringError, match="candidate discovery failed") as error:
        policy.explain("a.tmp")

    assert error.value.operation == "whatsnew"


def test_darcs_selection_is_discriminated_and_native(tmp_path: Path) -> None:
    selection = select_policy(tmp_path, DarcsPolicyConfig(environment={}))

    assert isinstance(selection, DarcsPolicySelection)
    assert isinstance(selection.policy, DarcsBoringPolicy)
    assert selection.mode == "darcs"
    assert selection.backend == "darcs-native-candidates"


@pytest.mark.parametrize(
    "case",
    [
        case
        for case in DARCS_ORACLE_CASES
        if case["id"]
        in {
            "darcs.unicode-literal-match",
            "darcs.unicode-normalization-is-distinct",
            "darcs.posix-alpha-class-on-unicode",
            "darcs.posix-alpha-class-on-unicode-utf8-locale",
        }
    ],
    ids=lambda case: case["id"],
)
def test_native_darcs_policy_matches_captured_unicode_regex_cases(
    tmp_path: Path, case: dict[str, Any]
) -> None:
    executable = shutil.which("darcs")
    if executable is None:
        pytest.skip("native Darcs is not installed")
    root = tmp_path / "repository"
    root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    environment = {
        **os.environ,
        "HOME": str(home),
        "APPDATA": str(home),
        "DARCS_PAGER": "cat",
        "PAGER": "cat",
        "LC_ALL": case["setup"].get("locale", "C"),
    }
    initialized = subprocess.run(
        [executable, "init", "--repodir", str(root)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert initialized.returncode == 0, initialized.stderr
    boring = root / "_darcs" / "prefs" / "boring"
    boring.write_text(case["setup"]["local_boring"], encoding="utf-8")
    target = root / case["query"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()
    policy = DarcsBoringPolicy(root, darcs_executable=executable, environment=environment)

    assert policy.explain(case["query"]).ignored is case["expected_boring"]


@pytest.mark.parametrize("topdown", [True, False])
def test_native_darcs_walker_matches_membership_aware_boring_behavior(
    tmp_path: Path, topdown: bool
) -> None:
    executable = shutil.which("darcs")
    if executable is None:
        pytest.skip("native Darcs is not installed")
    root = tmp_path / "repository"
    root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    environment = {
        **os.environ,
        "HOME": str(home),
        "APPDATA": str(home),
        "DARCS_EMAIL": "Oracle <oracle@example.invalid>",
        "DARCS_PAGER": "cat",
        "PAGER": "cat",
        "LC_ALL": "C",
    }
    initialized = subprocess.run(
        [executable, "init", "--repodir", str(root)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert initialized.returncode == 0, initialized.stderr
    (root / "_darcs" / "prefs" / "boring").write_text("^cache(/|$)\n\\.tmp$\n", encoding="utf-8")
    (root / "cache").mkdir()
    (root / "cache" / "ignored.txt").write_text("ignored\n", encoding="utf-8")
    (root / "visible.txt").write_text("visible\n", encoding="utf-8")
    (root / "tracked.tmp").write_text("tracked\n", encoding="utf-8")
    (root / "trailing-space ").write_text("visible despite trailing space\n", encoding="utf-8")
    newline_name = "line\nbreak.txt"
    if os.name != "nt":
        (root / newline_name).write_text("visible with line break in its name\n", encoding="utf-8")
    managed_newline_name = "managed\nname.tmp"
    if os.name != "nt":
        (root / managed_newline_name).write_text(
            "managed despite boring suffix\n", encoding="utf-8"
        )
    added = subprocess.run(
        [executable, "add", "--boring", "tracked.tmp"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert added.returncode == 0, added.stderr
    if os.name != "nt":
        added = subprocess.run(
            [executable, "add", "--boring", "--reserved-ok", "--", managed_newline_name],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert added.returncode == 0, added.stderr

    policy = DarcsBoringPolicy(root, darcs_executable=executable, environment=environment)
    walker = IgnoreWalker(root, policy=policy)

    expected_files = {
        root / "visible.txt",
        root / "tracked.tmp",
        root / "trailing-space ",
    }
    if os.name != "nt":
        expected_files.add(root / newline_name)
        expected_files.add(root / managed_newline_name)
    assert set(walker.iter_files(topdown=topdown)) == expected_files
    ignored_files = {
        path.relative_to(root).as_posix()
        for path in walker.iter_files(topdown=topdown, selection="ignored")
        if "_darcs" not in path.relative_to(root).parts
    }
    assert ignored_files == {"cache/ignored.txt"}
    all_workspace_files = {
        path.relative_to(root).as_posix()
        for path in walker.iter_files(topdown=topdown, selection="all")
        if "_darcs" not in path.relative_to(root).parts
    }
    assert (
        all_workspace_files
        == {path.relative_to(root).as_posix() for path in expected_files} | ignored_files
    )
    assert policy.explain("tracked.tmp").ignored is False
    assert policy.explain("cache/ignored.txt").ignored is True


def test_native_darcs_policy_combines_local_global_and_configured_sources(
    tmp_path: Path,
) -> None:
    executable = shutil.which("darcs")
    if executable is None:
        pytest.skip("native Darcs is not installed")
    root = tmp_path / "repository"
    home = tmp_path / "home"
    root.mkdir()
    home.mkdir()
    environment = {
        **os.environ,
        "HOME": str(home),
        "APPDATA": str(home),
        "DARCS_PAGER": "cat",
        "PAGER": "cat",
        "LC_ALL": "C",
    }
    initialized = subprocess.run(
        [executable, "init", "--repodir", str(root)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert initialized.returncode == 0, initialized.stderr

    (root / "_darcs" / "prefs" / "boring").write_text("\\.local$\n", encoding="utf-8")
    global_boring = home / ".darcs" / "boring"
    global_boring.parent.mkdir()
    global_boring.write_text("\\.global$\n", encoding="utf-8")
    (root / "policy").write_text("\\.configured$\n", encoding="utf-8")
    added = subprocess.run(
        [executable, "add", "--boring", "policy"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert added.returncode == 0, added.stderr
    configured = subprocess.run(
        [executable, "setpref", "boringfile", "policy"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert configured.returncode == 0, configured.stderr

    policy = DarcsBoringPolicy(root, darcs_executable=executable, environment=environment)
    assert policy.explain("a.local").ignored is True
    assert policy.explain("a.global").ignored is True
    assert policy.explain("a.configured").ignored is True


@pytest.mark.parametrize("topdown", [True, False])
def test_native_darcs_walker_follows_nested_repository_add_candidates(
    tmp_path: Path, topdown: bool
) -> None:
    executable = shutil.which("darcs")
    if executable is None:
        pytest.skip("native Darcs is not installed")
    root = (tmp_path / "outer-repository").resolve()
    root.mkdir()
    nested = root / "nested"
    nested.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    environment = {
        **os.environ,
        "HOME": str(home),
        "APPDATA": str(home),
        "DARCS_PAGER": "cat",
        "PAGER": "cat",
        "LC_ALL": "C",
    }

    for repository in (root, nested):
        initialized = subprocess.run(
            [executable, "init", "--repodir", str(repository)],
            cwd=repository,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert initialized.returncode == 0, initialized.stderr
    (root / "outer.txt").write_text("outer candidate\n", encoding="utf-8")
    (nested / "inner.txt").write_text("nested candidate\n", encoding="utf-8")

    candidates = subprocess.run(
        [executable, "whatsnew", "--look-for-adds", "--summary"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert candidates.returncode == 0, candidates.stderr
    candidate_paths = {
        line[2:].strip().replace("\\", "/").removeprefix("./")
        for line in candidates.stdout.splitlines()
        if line.startswith("a ")
    }
    assert "nested/inner.txt" in candidate_paths

    policy = DarcsBoringPolicy(root, darcs_executable=executable, environment=environment)
    assert policy.explain("nested/inner.txt").ignored is False
    walker = IgnoreWalker(root, policy=policy)
    included = {path.relative_to(root).as_posix() for path in walker.iter_files(topdown=topdown)}
    assert included == {"nested/inner.txt", "outer.txt"}
