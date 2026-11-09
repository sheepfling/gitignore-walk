"""Behavioral tests for the Fossil ignore-glob policy."""

from __future__ import annotations

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
