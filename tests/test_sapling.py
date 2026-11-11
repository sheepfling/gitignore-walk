"""Native membership and walking checks for Sapling ignore policies."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Literal

import pytest

from gitignore_walk import IgnoreWalker, SaplingPolicyConfig, select_policy


@pytest.mark.parametrize("topdown", [True, False])
def test_sapling_membership_walker_matches_native_status(
    tmp_path: Path,
    topdown: bool,
) -> None:
    executable = shutil.which("sl")
    if executable is None:
        pytest.skip("Sapling is not installed")

    root = tmp_path / "workspace"
    root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    hgrc = tmp_path / "hgrc"
    hgrc.write_text("", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "HGRCPATH": str(hgrc),
            "HGPLAIN": "1",
            "SLPLAIN": "1",
        }
    )

    def sl(*arguments: str) -> subprocess.CompletedProcess[bytes]:
        result = subprocess.run(
            [executable, *arguments],
            cwd=root,
            env=environment,
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        return result

    sl("init", str(root))
    (root / ".gitignore").write_text("*.tmp\ncache/\n", encoding="utf-8")
    for name in ("tracked.tmp", "clean.txt", "missing.tmp", "removed.tmp"):
        (root / name).write_text(f"{name}\n", encoding="utf-8")
    tracked_in_ignored_directory = root / "cache" / "tracked.txt"
    tracked_in_ignored_directory.parent.mkdir()
    tracked_in_ignored_directory.write_text("tracked below ignored directory\n", encoding="utf-8")
    sl(
        "add",
        ".gitignore",
        "tracked.tmp",
        "clean.txt",
        "missing.tmp",
        "removed.tmp",
        "cache/tracked.txt",
    )
    sl("commit", "-m", "membership fixture", "-u", "gitignore-walk test")
    broken_link = root / "broken-link"
    try:
        broken_link.symlink_to("missing-target.txt")
    except OSError:
        broken_link_created = False
    else:
        broken_link_created = True
        sl("add", "broken-link")
    (root / "tracked.tmp").write_text("modified\n", encoding="utf-8")
    (root / "missing.tmp").unlink()
    (root / "removed.tmp").unlink()
    sl("remove", "--after", "removed.tmp")
    (root / "added.tmp").write_text("added\n", encoding="utf-8")
    sl("add", "added.tmp")
    (root / "ignored.tmp").write_text("ignored\n", encoding="utf-8")
    (root / "unknown.txt").write_text("unknown\n", encoding="utf-8")

    native = sl("status", "--all", "--print0", "--root-relative").stdout
    native_records = {
        record[2:].decode(errors="surrogateescape"): record[:1].decode("ascii")
        for record in native.split(b"\0")
        if record and len(record) >= 3 and record[1:2] == b" "
    }
    assert native_records["tracked.tmp"] == "M"
    assert native_records["clean.txt"] == "C"
    assert native_records["missing.tmp"] == "!"
    assert native_records["removed.tmp"] == "R"
    assert native_records["added.tmp"] == "A"
    assert native_records["cache/tracked.txt"] == "C"
    if broken_link_created:
        assert native_records["broken-link"] == "A"
    assert native_records["ignored.tmp"] == "I"
    assert native_records["unknown.txt"] == "?"

    selection = select_policy(
        root,
        SaplingPolicyConfig(
            environment=environment,
            membership_aware=True,
            sapling_executable=executable,
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
            "missing.tmp",
            "removed.tmp",
            "added.tmp",
            "cache/tracked.txt",
            "ignored.tmp",
            "unknown.txt",
        ]
    )
    memberships = {
        decision.path.relative_to(root).as_posix(): decision.membership for decision in decisions
    }
    assert memberships == {
        "tracked.tmp": "versioned",
        "clean.txt": "versioned",
        "missing.tmp": "versioned",
        "removed.tmp": "versioned",
        "added.tmp": "versioned",
        "cache/tracked.txt": "versioned",
        "ignored.tmp": "unversioned",
        "unknown.txt": "unversioned",
    }
    assert all(decision.ignored for decision in decisions if decision.path.name.endswith(".tmp"))

    walker = IgnoreWalker(root, policy=policy)

    def walked(selection_name: Literal["included", "ignored", "all"]) -> set[str]:
        return {
            path.relative_to(root).as_posix()
            for path in walker.iter_files(selection=selection_name, topdown=topdown)
        }

    included = {
        ".gitignore",
        "cache/tracked.txt",
        "clean.txt",
        "tracked.tmp",
        "added.tmp",
        "unknown.txt",
    }
    assert walked("included") == included
    assert walked("ignored") == {"ignored.tmp"}
    assert walked("all") == included | {"ignored.tmp"}
