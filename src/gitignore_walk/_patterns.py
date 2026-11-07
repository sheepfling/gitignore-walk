"""Small, dependency-free parser and matcher for Git-ignore patterns."""

from __future__ import annotations

import re
from dataclasses import dataclass


class GitIgnorePatternError(ValueError):
    """Raised when a Git-ignore pattern cannot be compiled."""


@dataclass(frozen=True, slots=True)
class GitIgnorePattern:
    """One parsed pattern, retaining its source spelling and compiled expression."""

    include: bool
    pattern: str
    source_line: int
    directory_only: bool
    basename_only: bool
    expression: re.Pattern[str]

    def matches(self, relative: str, *, is_directory: bool) -> bool:
        """Return whether this rule matches a path relative to its ignore-file scope."""

        path = relative.replace("\\", "/").strip("/")
        if not path or path == ".":
            return False
        parts = path.split("/")
        for index, component in enumerate(parts):
            candidate_is_directory = index < len(parts) - 1 or is_directory
            if self.directory_only and not candidate_is_directory:
                continue
            candidate = component if self.basename_only else "/".join(parts[: index + 1])
            if self.expression.fullmatch(candidate):
                return True
        return False


@dataclass(frozen=True, slots=True)
class GitIgnoreSpec:
    """An ordered set of parsed patterns from one ignore file."""

    patterns: tuple[GitIgnorePattern, ...]


def parse_gitignore(lines: list[str] | tuple[str, ...]) -> GitIgnoreSpec:
    """Parse ignore-file lines into an ordered, immutable pattern specification."""

    patterns: list[GitIgnorePattern] = []
    for source_line, raw_line in enumerate(lines, start=1):
        parsed = _parse_line(raw_line, source_line=source_line)
        if parsed is not None:
            patterns.append(parsed)
    return GitIgnoreSpec(tuple(patterns))


def _parse_line(line: str, *, source_line: int) -> GitIgnorePattern | None:
    value = line.rstrip("\r\n")
    if not value or value.startswith("#"):
        return None

    negated = value.startswith("!")
    if negated:
        value = value[1:]
    if not value:
        return None

    value = _strip_unescaped_trailing_spaces(value)
    if not value:
        return None
    source_pattern = value

    anchored = value.startswith("/")
    if anchored:
        value = value[1:]
    directory_only = value.endswith("/") and not _is_escaped(value, len(value) - 1)
    if directory_only:
        value = value[:-1]
    if not value:
        return None

    basename_only = not anchored and "/" not in value
    try:
        expression = re.compile(_glob_to_regex(value))
    except re.error as error:
        raise GitIgnorePatternError(f"line {source_line}: {error}") from error
    return GitIgnorePattern(
        include=not negated,
        pattern=source_pattern,
        source_line=source_line,
        directory_only=directory_only,
        basename_only=basename_only,
        expression=expression,
    )


def _strip_unescaped_trailing_spaces(value: str) -> str:
    while value.endswith(" "):
        space_index = len(value) - 1
        if _is_escaped(value, space_index):
            value = value[:-2] + " "
            break
        value = value[:-1]
    return value


def _is_escaped(value: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and value[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def _glob_to_regex(pattern: str) -> str:
    chunks = ["^"]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            index += 1
            if index == len(pattern):
                chunks.append(re.escape("\\"))
            else:
                chunks.append(re.escape(pattern[index]))
        elif char == "*":
            end = index + 1
            while end < len(pattern) and pattern[end] == "*":
                end += 1
            count = end - index
            followed_by_slash = end < len(pattern) and pattern[end] == "/"
            at_segment_start = index == 0 or pattern[index - 1] == "/"
            if count >= 2 and at_segment_start and followed_by_slash:
                chunks.append("(?:.*/)?")
                end += 1
            elif count >= 2 and at_segment_start and end == len(pattern):
                chunks.append(".*")
            else:
                chunks.append("[^/]*")
            index = end - 1
        elif char == "?":
            chunks.append("[^/]")
        elif char == "[":
            class_expression, end = _character_class(pattern, index)
            chunks.append(class_expression)
            index = end
        else:
            chunks.append(re.escape(char))
        index += 1
    chunks.append("$")
    return "".join(chunks)


def _character_class(pattern: str, start: int) -> tuple[str, int]:
    end = start + 1
    if end < len(pattern) and pattern[end] in "!^":
        end += 1
    if end < len(pattern) and pattern[end] == "]":
        end += 1
    close = pattern.find("]", end)
    if close < 0:
        return re.escape("["), start

    content = pattern[start + 1 : close]
    negate = content.startswith("!")
    if negate:
        content = content[1:]
    if content.startswith("]"):
        content = r"\]" + content[1:]
    if content.startswith("^"):
        content = r"\^" + content[1:]
    escaped: list[str] = []
    index = 0
    while index < len(content):
        if content[index] == "\\" and index + 1 < len(content):
            escaped.append(re.escape(content[index + 1]))
            index += 2
            continue
        char = content[index]
        escaped.append(r"\]" if char == "]" else char)
        index += 1
    content = "".join(escaped)
    return f"(?!/)[{'^' if negate else ''}{content}]", close
