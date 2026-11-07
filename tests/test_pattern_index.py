"""Tests for candidate grouping in the portable pattern matcher."""

from pathlib import Path

from gitignore_walk import GitIgnorePolicy


def test_candidate_groups_preserve_last_matching_rule_order(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("z*\n*.tmp\na*\nzoo.tmp\n", encoding="utf-8")
    decision = GitIgnorePolicy(tmp_path, initial_excludes=()).explain("zoo.tmp")
    assert (decision.ignored, decision.pattern, decision.line) == (True, "zoo.tmp", 4)
