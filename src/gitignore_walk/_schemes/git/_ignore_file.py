"""Parse one ignore file and combine its ordered pattern decisions."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Final, TypeVar

from ...errors import GitIgnoreParseError
from ._ignore_protocols import GitIgnoreMatcher
from ._ignore_types import GitIgnoreFile, GitIgnoreMatch, GitIgnoreSpec
from ._patterns import (
    GitIgnorePattern,
    GitIgnorePatternError,
    normalize_relative_path,
    parse_pattern_line,
)

SpecT = TypeVar("SpecT")

__all__ = [
    "DEFAULT_MATCHER",
    "GitIgnoreFile",
    "GitIgnoreMatch",
    "GitIgnoreMatcher",
    "GitIgnoreSpec",
    "RegexMatcher",
    "match_gitignore_file",
    "matches_gitignore",
    "parse_gitignore",
]


@dataclass(frozen=True, slots=True)
class RegexMatcher:
    """The bundled, supported Python-regex matcher and portable default.

    Attributes:
        name: Stable identifier reported for this matcher backend.
    """

    name: str = "regex"

    def parse(self, lines: Iterable[str], *, source: str) -> GitIgnoreSpec:
        """Parse ignore-file lines into the bundled :class:`GitIgnoreSpec`."""
        return parse_gitignore(lines, source=source)

    def match(
        self,
        spec: GitIgnoreSpec,
        relative: str,
        *,
        source: str,
        is_directory: bool,
    ) -> GitIgnoreMatch | None:
        """Return the last matching rule, including its decision and provenance."""
        pattern = _last_matching_pattern(spec, relative, is_directory=is_directory)
        if pattern is None:
            return None
        return GitIgnoreMatch(
            ignored=pattern.include,
            source=source,
            pattern=pattern.pattern,
            line=pattern.source_line,
        )


DEFAULT_MATCHER: Final = RegexMatcher()
"""Portable default matcher used when no backend is supplied."""


def parse_gitignore(lines: Iterable[str], *, source: str) -> GitIgnoreSpec:
    """Parse an ignore file and report malformed patterns with their source."""

    patterns: list[GitIgnorePattern] = []
    try:
        for source_line, line in enumerate(lines, start=1):
            pattern = parse_pattern_line(line, source_line=source_line)
            if pattern is not None:
                patterns.append(pattern)
    except GitIgnorePatternError as error:
        raise GitIgnoreParseError(
            f"invalid Git-ignore pattern in {source}: {error}",
            source=source,
            line=error.line,
            pattern=error.pattern,
            reason=error.reason,
        ) from error
    return GitIgnoreSpec(tuple(patterns))


def matches_gitignore(
    spec: GitIgnoreSpec,
    relative: str | os.PathLike[str],
    *,
    is_directory: bool,
) -> bool:
    """Return whether the final matching pattern in one file ignores a path."""

    matched = DEFAULT_MATCHER.match(
        spec,
        normalize_relative_path(relative),
        source="",
        is_directory=is_directory,
    )
    return matched is not None and matched.ignored


def match_gitignore_file(
    ignore_file: GitIgnoreFile[SpecT],
    relative: str | os.PathLike[str],
    *,
    is_directory: bool,
    scope: str | None = None,
) -> GitIgnoreMatch | None:
    """Combine a file's ordered rules and return its final matching rule."""

    match = ignore_file.matcher.match(
        ignore_file.spec,
        normalize_relative_path(relative),
        source=ignore_file.source,
        is_directory=is_directory,
    )
    return replace(match, scope=scope) if match is not None else None


def _last_matching_pattern(
    spec: GitIgnoreSpec,
    relative: str,
    *,
    is_directory: bool,
) -> GitIgnorePattern | None:
    """Return the last matching pattern in source order."""

    normalized = normalize_relative_path(relative)
    if not normalized:
        return None
    candidate_characters = {part[0] for part in normalized.split("/") if part}
    decision: GitIgnorePattern | None = None
    for pattern in spec.candidate_patterns(candidate_characters):
        if pattern.matches(normalized, is_directory=is_directory) and (
            decision is None or pattern.source_line > decision.source_line
        ):
            decision = pattern
    return decision
