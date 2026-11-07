"""Parse one ignore file and combine its ordered pattern decisions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ._errors import GitIgnoreError
from ._patterns import GitIgnorePattern, GitIgnorePatternError, parse_pattern_line


@dataclass(frozen=True, slots=True)
class GitIgnoreSpec:
    """The ordered patterns parsed from a single ignore file."""

    patterns: tuple[GitIgnorePattern, ...]


@dataclass(frozen=True, slots=True)
class GitIgnoreFile:
    """An ignore file's source and compiled rules."""

    source: str
    spec: GitIgnoreSpec


@dataclass(frozen=True, slots=True)
class GitIgnoreMatch:
    """The final matching rule from one ignore file."""

    ignored: bool
    source: str
    pattern: str
    line: int


def parse_gitignore(lines: Iterable[str], *, source: str) -> GitIgnoreSpec:
    """Parse an ignore file and report malformed patterns with their source."""

    patterns: list[GitIgnorePattern] = []
    try:
        for source_line, line in enumerate(lines, start=1):
            pattern = parse_pattern_line(line, source_line=source_line)
            if pattern is not None:
                patterns.append(pattern)
    except GitIgnorePatternError as error:
        raise GitIgnoreError(f"invalid Git-ignore pattern in {source}: {error}") from error
    return GitIgnoreSpec(tuple(patterns))


def load_gitignore(path: Path, *, allow_symlink: bool = False) -> GitIgnoreFile | None:
    """Load one ignore file, if present, following symlinks only when requested."""

    try:
        if not path.is_file() or (path.is_symlink() and not allow_symlink):
            return None
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise GitIgnoreError(f"unable to read Git-ignore source: {path}: {error}") from error

    if path.name == ".gitignore":
        source = f"repository .gitignore {path}"
    elif path.name == "exclude" and path.parent.name == "info":
        source = f"repository info/exclude {path}"
    else:
        source = f"user-global excludes {path}"
    return GitIgnoreFile(source=source, spec=parse_gitignore(lines, source=source))


def matches_gitignore(
    spec: GitIgnoreSpec,
    relative: str,
    *,
    is_directory: bool,
) -> bool:
    """Return whether the final matching pattern in one file ignores a path."""

    matched = _last_matching_pattern(spec, relative, is_directory=is_directory)
    return matched is not None and matched.include


def match_gitignore_file(
    ignore_file: GitIgnoreFile,
    relative: str,
    *,
    is_directory: bool,
) -> GitIgnoreMatch | None:
    """Combine a file's ordered rules and return its final matching rule."""

    pattern = _last_matching_pattern(ignore_file.spec, relative, is_directory=is_directory)
    if pattern is None:
        return None
    return GitIgnoreMatch(
        ignored=pattern.include,
        source=ignore_file.source,
        pattern=pattern.pattern,
        line=pattern.source_line,
    )


def _last_matching_pattern(
    spec: GitIgnoreSpec,
    relative: str,
    *,
    is_directory: bool,
) -> GitIgnorePattern | None:
    """Return the last matching pattern in source order."""

    decision: GitIgnorePattern | None = None
    for pattern in spec.patterns:
        if pattern.matches(relative, is_directory=is_directory):
            decision = pattern
    return decision
