"""Small, dependency-free parser and matcher for Git-ignore patterns."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import NamedTuple


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

    def matches(self, relative: str | os.PathLike[str], *, is_directory: bool) -> bool:
        """Return whether this rule matches a path relative to its ignore-file scope."""

        path = normalize_relative_path(relative)
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


class _CharacterClass(NamedTuple):
    expression: str
    end_index: int


def parse_pattern_line(line: str, *, source_line: int) -> GitIgnorePattern | None:
    """Parse one nonempty source line into a compiled pattern, if it is active."""

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
    literal_start = 0
    while index < len(pattern):
        char = pattern[index]
        if char not in "\\*?[":
            index += 1
            continue
        if literal_start < index:
            chunks.append(re.escape(pattern[literal_start:index]))
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
                chunks.append("(?:[\\s\\S]*/)?")
                end += 1
            elif count >= 2 and at_segment_start and end == len(pattern):
                chunks.append("[\\s\\S]*")
            else:
                chunks.append("[^/]*")
            index = end - 1
        elif char == "?":
            chunks.append("[^/]")
        elif char == "[":
            character_class = _character_class(pattern, index)
            chunks.append(character_class.expression)
            index = character_class.end_index
        index += 1
        literal_start = index
    if literal_start < len(pattern):
        chunks.append(re.escape(pattern[literal_start:]))
    chunks.append("$")
    return "".join(chunks)


def _character_class(pattern: str, start: int) -> _CharacterClass:
    content_start = start + 1
    negate = content_start < len(pattern) and pattern[content_start] in "!^"
    if negate:
        content_start += 1

    close = content_start
    if close < len(pattern) and pattern[close] == "]":
        close += 1
    while close < len(pattern):
        if pattern[close] == "\\" and close + 1 < len(pattern):
            close += 2
            continue
        if pattern[close] == "]":
            break
        close += 1
    if close >= len(pattern):
        return _CharacterClass(re.escape("["), start)

    content: list[str] = []
    index = content_start
    if index < close and pattern[index] == "]":
        content.append(r"\]")
        index += 1
    while index < close:
        char = pattern[index]
        if char == "\\" and index + 1 < close:
            content.append(re.escape(pattern[index + 1]))
            index += 2
            continue
        if char == "^" and not content and not negate:
            content.append(r"\^")
        elif char == "[":
            content.append(r"\[")
        else:
            content.append(char)
        index += 1
    return _CharacterClass(f"(?!/)[{'^' if negate else ''}{''.join(content)}]", close)


def normalize_relative_path(relative: str | os.PathLike[str]) -> str:
    value = os.fspath(relative)
    path = value.replace("\\", "/")
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise ValueError("path must be relative to the ignore-file scope")
    parts = path.split("/")
    if ".." in parts:
        raise ValueError("relative path cannot escape its ignore-file scope")
    return "/".join(part for part in parts if part and part != ".")
