"""Tests for candidate grouping in the portable pattern matcher."""

from pathlib import Path

from gitignore_walk import GitIgnorePolicy
from gitignore_walk._schemes.git._ignore_file import (
    DEFAULT_MATCHER,
    _last_matching_pattern,
    parse_gitignore,
)


def test_candidate_groups_preserve_last_matching_rule_order(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("z*\n*.tmp\na*\nzoo.tmp\n", encoding="utf-8")
    decision = GitIgnorePolicy(tmp_path, initial_excludes=()).explain("zoo.tmp")
    assert (decision.ignored, decision.pattern, decision.line) == (True, "zoo.tmp", 4)


def test_candidate_groups_match_full_scan_for_quirky_rules() -> None:
    rules = [
        r"\#literal",
        r"\!literal",
        r"\*literal",
        r"\?literal",
        r"\[literal",
        "[^a].txt",
        "[!0-4].txt",
        "[]a].txt",
        r"[a\]b].txt",
        "/root-only.txt",
        "nested/path.txt",
        "folder/",
        "a/**/b.txt",
        "**/generated/*.md",
        "?.txt",
        "foo\\ bar",
        "*.txt",
        "!keep.txt",
        "z-literal",
    ]
    targets = [
        "#literal",
        "!literal",
        "*literal",
        "?literal",
        "[literal",
        "b.txt",
        "a.txt",
        "5.txt",
        "].txt",
        "root-only.txt",
        "nested/root-only.txt",
        "nested/path.txt",
        "folder",
        "folder/file.txt",
        "a/b.txt",
        "a/x/y/b.txt",
        "generated/file.md",
        "deep/generated/file.md",
        "foo bar",
        "keep.txt",
        "z-literal",
        "é-file.txt",
        "line\nbreak.txt",
    ]
    spec = parse_gitignore(rules, source="quirky benchmark corpus")

    for target in targets:
        for is_directory in (False, True):
            expected = _last_matching_pattern(spec, target, is_directory=is_directory)
            actual = DEFAULT_MATCHER.match(
                spec,
                target,
                source="quirky benchmark corpus",
                is_directory=is_directory,
            )
            expected_result = (
                (expected.pattern, expected.source_line, expected.include) if expected else None
            )
            actual_result = (actual.pattern, actual.line, actual.ignored) if actual else None
            assert actual_result == expected_result, target
