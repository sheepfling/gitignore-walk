"""Git control probes imported from the VCS expansion research checkpoint."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from gitignore_walk import GitIgnorePolicy, GitStandardPolicy

CASE_FILE = Path(__file__).parent / "oracles" / "git" / "checkpoint_cases.json"
CASES: list[dict[str, Any]] = json.loads(CASE_FILE.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda item: item["id"])
def test_git_checkpoint_rule_match_candidates(tmp_path: Path, case: dict[str, Any]) -> None:
    """Check pattern matching separately from the native index-aware query."""
    root = tmp_path / "checkout"
    root.mkdir()
    (root / ".gitignore").write_text(case["rules"], encoding="utf-8")
    query = case["path"]
    target = root / query
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()

    policy = GitIgnorePolicy(root)

    assert policy.is_ignored(query) is case["expected_rule_match"]


def test_git_checkpoint_tracked_queries_separate_rule_match_from_index(
    tmp_path: Path,
) -> None:
    """Prove the two captured tracked-file outcomes with native Git and both library policies."""
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git is not installed")
    root = tmp_path / "checkout"
    root.mkdir()
    environment = dict(os.environ)

    def run(*arguments: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [git, "-C", str(root), *arguments],
            env=environment,
            capture_output=True,
            check=False,
        )

    assert run("init", "--quiet").returncode == 0
    tracked = root / "keep.tmp"
    tracked.write_text("fixture\n", encoding="utf-8")
    assert run("add", "keep.tmp").returncode == 0
    (root / ".gitignore").write_text("*.tmp\n", encoding="utf-8")

    native_default = run("check-ignore", "keep.tmp")
    native_no_index = run("check-ignore", "--no-index", "keep.tmp")
    portable = GitIgnorePolicy(root)
    native_policy = GitStandardPolicy(root)

    assert native_default.returncode == 1
    assert native_no_index.returncode == 0
    assert portable.is_ignored("keep.tmp")
    assert native_policy.is_ignored("keep.tmp")
