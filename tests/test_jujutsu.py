"""Native membership and walking checks for Jujutsu ignore policies."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Literal

import pytest

from gitignore_walk import IgnoreWalker, JujutsuPolicyConfig, select_policy


@pytest.mark.parametrize("topdown", [True, False])
def test_jujutsu_membership_walk_uses_saved_tree_without_mutation(
    tmp_path: Path,
    topdown: bool,
) -> None:
    executable = os.environ.get("GITIGNORE_WALK_JJ") or shutil.which("jj")
    if executable is None:
        pytest.skip("Jujutsu is not installed")

    root = tmp_path / "workspace"
    root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    environment = os.environ.copy()
    environment.update({"HOME": str(home), "USERPROFILE": str(home)})
    for key in ("JJ_CONFIG", "JJ_CONFIG_DIR", "JJ_CONFIG_PATH"):
        environment.pop(key, None)

    def jj(
        *arguments: str, ignore_working_copy: bool = False
    ) -> subprocess.CompletedProcess[bytes]:
        prefix = [executable]
        if ignore_working_copy:
            prefix.append("--ignore-working-copy")
        result = subprocess.run(
            [*prefix, *arguments],
            cwd=root,
            env=environment,
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        return result

    jj("git", "init", "--colocate")
    (root / ".gitignore").write_text("# membership fixture\n", encoding="utf-8")
    (root / "tracked.tmp").write_text("tracked\n", encoding="utf-8")
    (root / "clean.txt").write_text("clean\n", encoding="utf-8")
    tracked_in_ignored_directory = root / "cache" / "tracked.txt"
    tracked_in_ignored_directory.parent.mkdir()
    tracked_in_ignored_directory.write_text("tracked below ignored directory\n", encoding="utf-8")
    jj("status")
    (root / ".gitignore").write_text("*.tmp\ncache/\n", encoding="utf-8")
    broken_link = root / "broken-link"
    try:
        broken_link.symlink_to("missing-target.txt")
    except OSError:
        broken_link_created = False
    else:
        broken_link_created = True
    jj("status")
    (root / "ignored.tmp").write_text("ignored\n", encoding="utf-8")
    (root / "unknown.txt").write_text("unknown\n", encoding="utf-8")
    (root / "tracked.tmp").write_text("modified after the saved tree\n", encoding="utf-8")
    (root / "clean.txt").unlink()

    native_tree = jj(
        "file",
        "list",
        "--revision",
        "@",
        "--template",
        'path ++ "\\0"',
        ignore_working_copy=True,
    ).stdout
    native_versioned = {
        item.decode(errors="surrogateescape") for item in native_tree.split(b"\0") if item
    }
    expected_versioned = {".gitignore", "cache/tracked.txt", "tracked.tmp", "clean.txt"}
    if broken_link_created:
        expected_versioned.add("broken-link")
    assert native_versioned == expected_versioned
    operation_before = jj(
        "op", "log", "-n", "1", "-T", 'id ++ "\\n"', ignore_working_copy=True
    ).stdout

    selection = select_policy(
        root,
        JujutsuPolicyConfig(
            environment=environment,
            membership_aware=True,
            jujutsu_executable=executable,
        ),
    )
    policy = selection.policy
    if broken_link_created:
        assert policy.explain("broken-link").membership == "versioned"
        assert policy.trace("broken-link").decision.membership == "versioned"
        assert next(policy.iter_explain(["broken-link"])).membership == "versioned"
    decisions = policy.explain_many(
        [
            "tracked.tmp",
            "clean.txt",
            "cache/tracked.txt",
            "ignored.tmp",
            "unknown.txt",
            "absent.txt",
        ]
    )
    memberships = {
        decision.path.relative_to(root).as_posix(): decision.membership for decision in decisions
    }
    assert memberships == {
        "tracked.tmp": "versioned",
        "clean.txt": "versioned",
        "cache/tracked.txt": "versioned",
        "ignored.tmp": "unversioned",
        "unknown.txt": "unversioned",
        "absent.txt": None,
    }
    assert all(decision.ignored for decision in decisions if decision.path.name.endswith(".tmp"))

    walker = IgnoreWalker(root, policy=policy)

    def walked(selection_name: Literal["included", "ignored", "all"]) -> set[str]:
        return {
            path.relative_to(root).as_posix()
            for path in walker.iter_files(selection=selection_name, topdown=topdown)
        }

    assert walked("included") == {
        ".gitignore",
        "cache/tracked.txt",
        "tracked.tmp",
        "unknown.txt",
    }
    assert walked("ignored") == {"ignored.tmp"}
    assert walked("all") == {
        ".gitignore",
        "cache/tracked.txt",
        "ignored.tmp",
        "tracked.tmp",
        "unknown.txt",
    }
    operation_after = jj(
        "op", "log", "-n", "1", "-T", 'id ++ "\\n"', ignore_working_copy=True
    ).stdout
    assert operation_after == operation_before
