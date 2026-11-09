"""Small, dependency-free parser and matcher for Git-ignore patterns."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NamedTuple


class _PatternSyntax:
    """Named symbols for the Git-ignore syntax markers handled by this parser."""

    COMMENT: Final = "#"
    NEGATION: Final = "!"
    ANCHOR: Final = "/"
    SEPARATOR: Final = "/"
    ESCAPE: Final = "\\"
    STAR: Final = "*"
    QUESTION: Final = "?"
    CLASS_START: Final = "["
    CLASS_END: Final = "]"
    CLASS_NEGATION: Final = "^"
    SPACE: Final = " "


class GitIgnorePatternError(ValueError):
    """Raised when a Git-ignore pattern cannot be compiled."""

    def __init__(self, message: str, *, line: int, pattern: str, reason: str) -> None:
        super().__init__(message)
        self.line = line
        self.pattern = pattern
        self.reason = reason


@dataclass(frozen=True, slots=True)
class GitIgnorePattern:
    """One parsed pattern, retaining its source spelling and compiled expression."""

    include: bool
    pattern: str
    source_line: int
    directory_only: bool
    basename_only: bool
    expression: re.Pattern[bytes]
    first_literal: str | None = None

    def matches(self, relative: str | os.PathLike[str], *, is_directory: bool) -> bool:
        """Return whether this rule matches a path relative to its ignore-file scope."""

        path = normalize_relative_path(relative)
        if not path or path == ".":
            return False
        parts = path.split(_PatternSyntax.SEPARATOR)
        for index, component in enumerate(parts):
            candidate_is_directory = index < len(parts) - 1 or is_directory
            if self.directory_only and not candidate_is_directory:
                continue
            candidate = (
                component
                if self.basename_only
                else _PatternSyntax.SEPARATOR.join(parts[: index + 1])
            )
            if self.expression.fullmatch(os.fsencode(candidate)):
                return True
        return False


class _CharacterClass(NamedTuple):
    expression: str
    end_index: int


def parse_pattern_line(line: str, *, source_line: int) -> GitIgnorePattern | None:
    """Parse one nonempty source line into a compiled pattern, if it is active."""

    value = line.rstrip("\r\n")
    if not value or value.startswith(_PatternSyntax.COMMENT):
        return None

    negated = value.startswith(_PatternSyntax.NEGATION)
    if negated:
        value = value[1:]
    if not value:
        return None

    value = _strip_unescaped_trailing_spaces(value)
    if not value:
        return None
    source_pattern = f"{_PatternSyntax.NEGATION if negated else ''}{value}"

    anchored = value.startswith(_PatternSyntax.ANCHOR)
    if anchored:
        value = value[1:]
    directory_only = value.endswith(_PatternSyntax.SEPARATOR) and not _is_escaped(
        value, len(value) - 1
    )
    if directory_only:
        value = value[:-1]
    if not value:
        return None

    basename_only = not anchored and _PatternSyntax.SEPARATOR not in value
    try:
        expression = re.compile(_glob_to_regex(value).encode("utf-8", errors="surrogateescape"))
    except re.error as error:
        raise GitIgnorePatternError(
            f"line {source_line}: {error}",
            line=source_line,
            pattern=source_pattern,
            reason=str(error),
        ) from error
    return GitIgnorePattern(
        include=not negated,
        pattern=source_pattern,
        source_line=source_line,
        directory_only=directory_only,
        basename_only=basename_only,
        expression=expression,
        first_literal=_first_literal(value),
    )


def _first_literal(pattern: str) -> str | None:
    """Return a mandatory first character, or None when a glob can match anything."""
    if not pattern:
        return None
    if pattern[0] == _PatternSyntax.ESCAPE:
        return pattern[1] if len(pattern) > 1 else _PatternSyntax.ESCAPE
    if pattern[0] in (_PatternSyntax.STAR, _PatternSyntax.QUESTION, _PatternSyntax.CLASS_START):
        return None
    return pattern[0]


def _strip_unescaped_trailing_spaces(value: str) -> str:
    while value.endswith(_PatternSyntax.SPACE):
        space_index = len(value) - 1
        if _is_escaped(value, space_index):
            value = value[:-2] + " "
            break
        value = value[:-1]
    return value


def _is_escaped(value: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and value[index] == _PatternSyntax.ESCAPE:
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


_begin_escape_group: Final = frozenset(
    {
        _PatternSyntax.ESCAPE,
        _PatternSyntax.STAR,
        _PatternSyntax.QUESTION,
        _PatternSyntax.CLASS_START,
    }
)


def _glob_to_regex(pattern: str) -> str:
    chunks = ["^"]
    index = 0
    literal_start = 0
    while index < len(pattern):
        char = pattern[index]
        if char not in _begin_escape_group:
            index += 1
            continue
        if literal_start < index:
            chunks.append(re.escape(pattern[literal_start:index]))
        if char == _PatternSyntax.ESCAPE:
            index += 1
            if index == len(pattern):
                chunks.append("(?!)")
            else:
                chunks.append(re.escape(pattern[index]))
        elif char == _PatternSyntax.STAR:
            end = index + 1
            while end < len(pattern) and pattern[end] == _PatternSyntax.STAR:
                end += 1
            count = end - index
            followed_by_slash = end < len(pattern) and pattern[end] == _PatternSyntax.SEPARATOR
            at_segment_start = index == 0 or pattern[index - 1] == _PatternSyntax.SEPARATOR
            if count >= 2 and at_segment_start and followed_by_slash:
                chunks.append("(?:[\\s\\S]*/)?")
                end += 1
            elif count >= 2 and at_segment_start and end == len(pattern):
                chunks.append("[\\s\\S]*")
            else:
                chunks.append("[^/]*")
            index = end - 1
        elif char == _PatternSyntax.QUESTION:
            chunks.append("[^/]")
        elif char == _PatternSyntax.CLASS_START:
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
    negate = content_start < len(pattern) and pattern[content_start] in (
        _PatternSyntax.NEGATION,
        _PatternSyntax.CLASS_NEGATION,
    )
    if negate:
        content_start += 1

    close = content_start
    if close < len(pattern) and pattern[close] == _PatternSyntax.CLASS_END:
        close += 1
    while close < len(pattern):
        if pattern[close] == _PatternSyntax.ESCAPE and close + 1 < len(pattern):
            close += 2
            continue
        if pattern[close] == _PatternSyntax.CLASS_END:
            break
        close += 1
    if close >= len(pattern):
        return _CharacterClass(r"(?!)", len(pattern) - 1)

    content: list[str] = []
    index = content_start
    if index < close and pattern[index] == _PatternSyntax.CLASS_END:
        content.append(r"\]")
        index += 1
    while index < close:
        char = pattern[index]
        if char == _PatternSyntax.ESCAPE and index + 1 < close:
            content.append(re.escape(pattern[index + 1]))
            index += 2
            continue
        if char == _PatternSyntax.CLASS_NEGATION and not content and not negate:
            content.append(r"\^")
        elif char == _PatternSyntax.CLASS_START:
            content.append(r"\[")
        else:
            content.append(char)
        index += 1
    return _CharacterClass(f"(?!/)[{'^' if negate else ''}{''.join(content)}]", close)


def normalize_relative_path(relative: str | os.PathLike[str]) -> str:
    """Normalize a relative ignore candidate to slash-separated form.

    Empty paths stay empty. Absolute paths, drive-qualified paths, and parent traversal are
    rejected so matching cannot escape the caller's policy root.
    """
    value = os.fspath(Path(relative))
    if os.sep == _PatternSyntax.ESCAPE:
        value = value.replace(_PatternSyntax.ESCAPE, _PatternSyntax.SEPARATOR)
    path = value
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise ValueError("path must be relative to the ignore-file scope")
    parts = path.split(_PatternSyntax.SEPARATOR)
    if ".." in parts:
        raise ValueError("relative path cannot escape its ignore-file scope")
    return _PatternSyntax.SEPARATOR.join(part for part in parts if part and part != ".")
