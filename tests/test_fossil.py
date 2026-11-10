"""Behavioral tests for the Fossil ignore-glob policy."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from gitignore_walk import FossilIgnorePolicy, FossilPolicyConfig, IgnoreWalker, select_policy
from gitignore_walk._schemes.fossil.policy import _matches_glob, _parse_glob_list


def test_fossil_glob_list_uses_quotes_and_separators() -> None:
    assert _parse_glob_list('"two words.tmp",*.bak other') == (
        "two words.tmp",
        "*.bak",
        "other",
    )
    assert _parse_glob_list('"a"b') == ("a", "b")
    assert _parse_glob_list('"unterminated') == ("unterminated",)
    assert _parse_glob_list("a,,b") == ("a", "b")
    assert _parse_glob_list("# comment\n*.tmp") == ("#", "comment", "*.tmp")
    assert _parse_glob_list("#literal") == ("#literal",)
    assert _parse_glob_list(r"\#literal") == (r"\#literal",)


def test_fossil_glob_list_splits_only_ascii_separators() -> None:
    separators = ("\u0085", "\u001c", "\u2028", "\u2029", "\u00a0")
    for separator in separators:
        pattern = f"one{separator}two"
        assert _parse_glob_list(pattern) == (pattern,)
        assert _parse_glob_list(f"{separator}name") == (f"{separator}name",)
        assert _parse_glob_list(f"name{separator}") == (f"name{separator}",)


@pytest.mark.parametrize(
    ("setting", "target", "expected"),
    [
        ("#literal", "#literal", True),
        (r"\#literal", "#literal", False),
        (r"\#literal", r"\#literal", True),
    ],
)
def test_fossil_hash_is_pattern_data_not_a_comment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    setting: str,
    target: str,
    expected: bool,
) -> None:
    if os.name == "nt" and "\\" in target:
        pytest.skip("Windows paths cannot represent a POSIX filename containing backslash")
    root = tmp_path / "checkout"
    root.mkdir()
    (root / ".fslckout").touch()

    def captured_setting(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        assert command[1:] == ["settings", "ignore-glob", "--value"]
        return subprocess.CompletedProcess(command, 0, setting.encode(), b"")

    monkeypatch.setattr("gitignore_walk._schemes.fossil.policy.subprocess.run", captured_setting)
    policy = FossilIgnorePolicy(root, environment={"PATH": ""})

    assert policy.explain(target).ignored is expected


@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [
        ("a/b.tmp", "*.tmp", True),
        ("a/foo", "foo", False),
        ("two words.tmp", "two words.tmp", True),
        ("b", "[^a]", True),
        ("keep.tmp", "!keep.tmp", False),
    ],
)
def test_fossil_globs_match_native_observations(path: str, pattern: str, expected: bool) -> None:
    assert _matches_glob(path, pattern) is expected


def test_fossil_policy_uses_effective_setting_and_prunes_ignored_directories(
    tmp_path: Path,
) -> None:
    fossil = shutil.which("fossil")
    if fossil is None:
        pytest.skip("Fossil is not installed")
    checkout = tmp_path / "checkout"
    repository = tmp_path / "repository.fossil"
    home = tmp_path / "home"
    home.mkdir()
    environment = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "USER": "pytest",
        "PATH": str(Path(fossil).parent),
        "LC_ALL": "C",
    }

    def run(*arguments: str, cwd: Path = tmp_path) -> None:
        result = subprocess.run(
            [fossil, *arguments],
            cwd=cwd,
            env=environment,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")

    run("init", "--admin-user", "pytest", str(repository))
    run("open", "--nosync", "--workdir", str(checkout), str(repository))
    run("settings", "ignore-glob", "*.tmp", "--global", cwd=checkout)
    global_policy = FossilIgnorePolicy(checkout, fossil_executable=fossil, environment=environment)
    assert global_policy.explain("global.tmp").ignored

    run("settings", "ignore-glob", "*.bak", cwd=checkout)
    local_policy = FossilIgnorePolicy(checkout, fossil_executable=fossil, environment=environment)
    assert local_policy.explain("local.bak").ignored
    assert local_policy.explain("global.tmp").ignored is False

    run("settings", "ignore-glob", "*.tmp", cwd=checkout)
    settings_file = checkout / ".fossil-settings" / "ignore-glob"
    settings_file.parent.mkdir()
    settings_file.write_text("cache\n", encoding="utf-8")
    run("add", "--dotfiles", ".fossil-settings/ignore-glob", cwd=checkout)
    run("commit", "--no-warnings", "-m", "version ignore setting", cwd=checkout)
    settings_file.with_name("ignore-glob.no-warn").touch()
    (checkout / "cache").mkdir()
    (checkout / "cache" / "nested.tmp").write_text("ignored\n", encoding="utf-8")
    (checkout / "not-ignored.tmp").write_text("local value overridden\n", encoding="utf-8")
    (checkout / "visible.txt").write_text("visible\n", encoding="utf-8")

    policy = FossilIgnorePolicy(checkout, fossil_executable=fossil, environment=environment)
    assert policy.scheme == "fossil"
    assert policy.explain("cache/nested.tmp").ignored
    assert policy.explain("not-ignored.tmp").ignored is False
    assert policy.explain("visible.txt").ignored is False
    assert policy.can_prune_ignored_directory(checkout / "cache", policy.explain("cache"))
    selected_files = set(IgnoreWalker(checkout, policy=policy).iter_files())
    assert checkout / "cache" / "nested.tmp" not in selected_files
    assert checkout / "visible.txt" in selected_files

    selection = select_policy(checkout, FossilPolicyConfig(environment=environment))
    assert selection.backend == "fossil-effective-setting"
    assert selection.policy.scheme == "fossil"
    assert checkout / ".fslckout" not in set(
        IgnoreWalker(checkout, policy=selection.policy).iter_files()
    )
    without_marker_baseline = select_policy(
        checkout, FossilPolicyConfig(environment=environment, initial_excludes=())
    )
    assert checkout / ".fslckout" in set(
        IgnoreWalker(checkout, policy=without_marker_baseline.policy).iter_files()
    )


@pytest.mark.parametrize("topdown", [True, False], ids=["topdown", "bottomup"])
def test_fossil_membership_uses_native_json_without_changing_ignore_decisions(
    tmp_path: Path, topdown: bool
) -> None:
    fossil = shutil.which("fossil")
    if fossil is None:
        pytest.skip("Fossil is not installed")
    checkout = tmp_path / "checkout"
    repository = tmp_path / "repository.fossil"
    home = tmp_path / "home"
    home.mkdir()
    environment = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "USER": "pytest",
        "PATH": str(Path(fossil).parent),
        "LC_ALL": "C",
    }

    def run(*arguments: str, cwd: Path = tmp_path) -> subprocess.CompletedProcess[bytes]:
        result = subprocess.run(
            [fossil, *arguments],
            cwd=cwd,
            env=environment,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        return result

    run("init", "--admin-user", "pytest", str(repository))
    run("open", "--nosync", "--workdir", str(checkout), str(repository))
    run("settings", "ignore-glob", "*.tmp", cwd=checkout)
    (checkout / "nested").mkdir()
    (checkout / "tracked.tmp").write_text("tracked despite ignore\n", encoding="utf-8")
    (checkout / "nested" / "versioned.txt").write_text("nested\n", encoding="utf-8")
    (checkout / "deleted.tmp").write_text("will be removed\n", encoding="utf-8")
    (checkout / "modified.tmp").write_text("before edit\n", encoding="utf-8")
    (checkout / "moved.tmp").write_text("will be renamed\n", encoding="utf-8")
    run(
        "add",
        "--force",
        "tracked.tmp",
        "nested/versioned.txt",
        "deleted.tmp",
        "modified.tmp",
        "moved.tmp",
        cwd=checkout,
    )
    run("commit", "--no-warnings", "-m", "membership fixture", cwd=checkout)
    (checkout / "added.tmp").write_text("scheduled despite ignore\n", encoding="utf-8")
    run("add", "--force", "added.tmp", cwd=checkout)
    (checkout / "deleted.tmp").unlink()
    (checkout / "modified.tmp").write_text("after edit\n", encoding="utf-8")
    run("mv", "moved.tmp", "renamed.tmp", cwd=checkout)
    (checkout / "loose.tmp").write_text("unversioned and ignored\n", encoding="utf-8")
    (checkout / "visible.txt").write_text("unversioned and visible\n", encoding="utf-8")
    (checkout / "unversioned-dir").mkdir()
    (checkout / "unversioned-dir" / "nested.tmp").write_text(
        "nested unversioned and ignored\n", encoding="utf-8"
    )

    root_entries = json.loads(
        run("json", "dir", "--checkin", "current", "--name", "/", cwd=checkout).stdout
    )["payload"]["entries"]
    nested_entries = json.loads(
        run("json", "dir", "--checkin", "current", "--name", "nested", cwd=checkout).stdout
    )["payload"]["entries"]
    status_files = json.loads(run("json", "status", cwd=checkout).stdout)["payload"]["files"]
    assert {entry["name"] for entry in root_entries} == {
        "nested",
        "tracked.tmp",
        "deleted.tmp",
        "modified.tmp",
        "moved.tmp",
    }
    assert {entry["name"] for entry in nested_entries} == {"versioned.txt"}
    assert {entry["name"] for entry in status_files} == {
        "added.tmp",
        "deleted.tmp",
        "modified.tmp",
        "renamed.tmp",
    }
    statuses = {item["name"]: item["status"] for item in status_files}
    assert statuses["added.tmp"] == "new"
    assert statuses["deleted.tmp"] == "missing"
    assert statuses["modified.tmp"] == "edited"
    assert statuses["renamed.tmp"] == ["missing", "renamed"]

    policy = FossilIgnorePolicy(
        checkout,
        fossil_executable=fossil,
        environment=environment,
        membership_aware=True,
    )
    decisions = policy.explain_many(
        (
            "tracked.tmp",
            "added.tmp",
            "loose.tmp",
            "unversioned-dir/nested.tmp",
            "visible.txt",
            "nested/versioned.txt",
            "nested",
            "deleted.tmp",
            "modified.tmp",
            "renamed.tmp",
            "missing.tmp",
        )
    )

    assert [(decision.ignored, decision.membership) for decision in decisions] == [
        (True, "versioned"),
        (True, "versioned"),
        (True, "unversioned"),
        (True, "unversioned"),
        (False, "unversioned"),
        (False, "versioned"),
        (False, None),
        (True, "versioned"),
        (True, "versioned"),
        (True, "versioned"),
        (True, None),
    ]
    selection = select_policy(
        checkout, FossilPolicyConfig(environment=environment, membership_aware=True)
    )
    assert selection.policy.explain("tracked.tmp").membership == "versioned"

    walker = IgnoreWalker(checkout, policy=selection.policy)

    def walked(selection_name: str) -> set[str]:
        return {
            path.relative_to(checkout).as_posix()
            for path in walker.iter_files(selection=selection_name, topdown=topdown)
        }

    assert walked("included") == {
        "added.tmp",
        "modified.tmp",
        "moved.tmp",
        "nested/versioned.txt",
        "tracked.tmp",
        "visible.txt",
    }
    assert walked("ignored") == {".fslckout", "loose.tmp", "unversioned-dir/nested.tmp"}
    assert walked("all") == {
        "added.tmp",
        ".fslckout",
        "loose.tmp",
        "modified.tmp",
        "moved.tmp",
        "nested/versioned.txt",
        "tracked.tmp",
        "unversioned-dir/nested.tmp",
        "visible.txt",
    }
