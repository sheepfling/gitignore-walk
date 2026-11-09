"""Mercurial-specific ignore-file records and matching expressions."""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

HgSyntax = Literal["regexp", "glob", "rootglob"]


@dataclass(frozen=True, slots=True)
class HgRule:
    """One compiled Mercurial ignore pattern and the directory it is rooted at."""

    source: str
    pattern: str
    line: int
    syntax: HgSyntax
    matcher_root: Path
    expression: re.Pattern[bytes]

    def matches(self, relative_path: str) -> bool:
        """Match one path relative to ``matcher_root`` using Mercurial regex semantics."""
        if os.name == "nt":
            # Mercurial 7.1.2 on Windows matches local paths using the active Windows code page;
            # the ignore source itself remains UTF-8 bytes. This differs from POSIX byte paths.
            path_bytes = relative_path.encode("mbcs", errors="replace")
        else:
            path_bytes = relative_path.encode("utf-8", errors="surrogateescape")
        return self.expression.match(path_bytes) is not None


@dataclass(frozen=True, slots=True)
class HgPatternRecord:
    """One parsed ignore line, either a rule or an include edge."""

    kind: Literal["rule", "include", "subinclude", "invalid-syntax"]
    syntax: HgSyntax
    pattern: str
    line: int


def parse_pattern_lines(contents: bytes) -> tuple[HgPatternRecord, ...]:
    """Parse Mercurial ignore-file bytes using its syntax-switch and comment rules."""
    syntax: HgSyntax = "regexp"
    records: list[HgPatternRecord] = []
    for line_number, raw_line in enumerate(contents.split(b"\n"), start=1):
        # Mercurial's matcher operates on filesystem bytes. ``surrogateescape`` preserves
        # undecodable bytes so they can round-trip through POSIX paths and regex strings.
        line = raw_line.decode("utf-8", errors="surrogateescape")
        line = _strip_comment(line)
        if line.endswith("\r"):
            line = line[:-1]
        if not line.strip():
            continue
        if line.startswith("syntax:"):
            value = line[7:].strip()
            if value in ("regexp", "re", "glob", "rootglob"):
                syntax = "regexp" if value in ("regexp", "re") else value
            else:
                records.append(HgPatternRecord("invalid-syntax", syntax, value, line_number))
            continue

        for prefix, selected in (
            ("regexp:", "regexp"),
            ("re:", "regexp"),
            ("glob:", "glob"),
            ("rootglob:", "rootglob"),
            ("include:", "include"),
            ("subinclude:", "subinclude"),
        ):
            if line.startswith(prefix):
                value = line[len(prefix) :]
                if selected in ("include", "subinclude"):
                    records.append(
                        HgPatternRecord(selected, syntax, value.rstrip(), line_number)  # type: ignore[arg-type]
                    )
                else:
                    rule_syntax: HgSyntax = selected  # type: ignore[assignment]
                    if rule_syntax in ("glob", "rootglob"):
                        value = value.rstrip()
                    records.append(HgPatternRecord("rule", rule_syntax, value, line_number))
                break
        else:
            pattern = line.rstrip() if syntax in ("glob", "rootglob") else line
            records.append(HgPatternRecord("rule", syntax, pattern, line_number))
    return tuple(records)


def compile_rule(
    *,
    source: Path,
    pattern: str,
    line: int,
    syntax: HgSyntax,
    matcher_root: Path,
) -> HgRule:
    """Compile one Mercurial regexp, unrooted glob, or rootglob rule."""
    if len(pattern.encode("utf-8", errors="surrogateescape")) > 20_000:
        raise ValueError(f"Mercurial pattern exceeds the 20000-byte limit at {source}:{line}")
    if syntax == "regexp":
        flags = re.match(r"^\(\?([aiLmsux]+)\)(.*)$", pattern)
        if flags is None:
            expression_text = pattern if pattern.startswith("^") else ".*" + pattern
        else:
            flag_text, expression_body = flags.groups()
            if not expression_body.startswith("^"):
                expression_body = ".*" + expression_body
            expression_text = f"(?{flag_text}:{expression_body})"
    else:
        expression_text = _glob_to_regex(pattern)
        if syntax == "glob":
            expression_text = "(?:|.*/)" + expression_text
    expression = expression_text.encode("utf-8", errors="surrogateescape")
    if len(expression) > 20_000:
        raise ValueError(
            f"compiled Mercurial pattern exceeds the 20000-byte limit at {source}:{line}"
        )
    try:
        compiled = re.compile(expression)
    except re.error as error:
        message = f"invalid Mercurial {syntax} pattern at {source}:{line}: {error}"
        raise ValueError(message) from error
    return HgRule(
        source=str(source),
        pattern=pattern,
        line=line,
        syntax=syntax,
        matcher_root=matcher_root,
        expression=compiled,
    )


def _strip_comment(line: str) -> str:
    """Strip an unescaped comment and unescape a literal ``#``."""
    output: list[str] = []
    index = 0
    while index < len(line):
        if line[index] == "#":
            slashes = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                slashes += 1
                cursor -= 1
            if slashes % 2 == 0:
                break
            del output[-slashes:]
            output.extend("\\" for _ in range(slashes - 1))
            output.append("#")
            index += 1
            continue
        output.append(line[index])
        index += 1
    return "".join(output)


def _glob_to_regex(pattern: str) -> str:
    """Translate shell globs with Mercurial's brace and recursive-star extensions.

    ``fnmatch.translate`` supplies character classes and single-character matching. We replace
    star tokens with private markers first so ordinary stars can be kept within a path component,
    while ``**`` can cross separators.
    """
    alternatives: list[str] = []
    for expanded in _expand_braces(pattern):
        protected, replacements = _protect_glob_stars(expanded)
        translated = fnmatch.translate(protected)
        body = translated[len("(?s:") : -len(")\\Z")]
        for marker, expression in replacements.items():
            body = body.replace(re.escape(marker), expression)
        alternatives.append(f"(?:{body})")
    return "(?:" + "|".join(alternatives) + r")\Z"


def _expand_braces(pattern: str, *, depth: int = 0) -> tuple[str, ...]:
    """Expand comma-separated brace groups without changing escaped braces or classes."""
    if depth > 64:
        raise ValueError("Mercurial glob has too many nested brace alternatives")
    opening = _find_brace_open(pattern)
    if opening is None:
        return (pattern,)
    closing = _find_brace_close(pattern, opening)
    if closing is None:
        raise ValueError("unclosed brace alternative in Mercurial glob")
    choices = _split_brace_choices(pattern[opening + 1 : closing])
    if len(choices) < 2:
        raise ValueError("brace alternatives require at least two choices")
    expanded: list[str] = []
    for choice in choices:
        expanded.extend(
            _expand_braces(pattern[:opening] + choice + pattern[closing + 1 :], depth=depth + 1)
        )
        if len(expanded) > 1024:
            raise ValueError("Mercurial glob expands to too many brace alternatives")
    return tuple(expanded)


def _find_brace_open(pattern: str) -> int | None:
    escaped = False
    in_class = False
    for index, char in enumerate(pattern):
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "{" and not in_class:
            return index
    return None


def _find_brace_close(pattern: str, opening: int) -> int | None:
    depth = 0
    escaped = False
    in_class = False
    for index in range(opening, len(pattern)):
        char = pattern[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif not in_class and char == "{":
            depth += 1
        elif not in_class and char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _split_brace_choices(value: str) -> tuple[str, ...]:
    choices: list[str] = []
    start = 0
    depth = 0
    escaped = False
    in_class = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif not in_class and char == "{":
            depth += 1
        elif not in_class and char == "}":
            depth -= 1
        elif not in_class and depth == 0 and char == ",":
            choices.append(value[start:index])
            start = index + 1
    choices.append(value[start:])
    return tuple(choices)


def _protect_glob_stars(pattern: str) -> tuple[str, dict[str, str]]:
    protected: list[str] = []
    replacements: dict[str, str] = {}
    index = 0
    marker_number = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            index += 1
            if index < len(pattern):
                marker = f"\ue100{marker_number}\ue101"
                marker_number += 1
                replacements[marker] = re.escape(pattern[index])
                protected.append(marker)
            else:
                marker = f"\ue100{marker_number}\ue101"
                marker_number += 1
                replacements[marker] = re.escape("\\")
                protected.append(marker)
        elif char == "*":
            marker = f"\ue000{marker_number}\ue001"
            marker_number += 1
            end = index + 1
            while end < len(pattern) and pattern[end] == "*":
                end += 1
            if end - index >= 2:
                if end < len(pattern) and pattern[end] == "/":
                    replacements[marker] = "(?:.*/)?"
                    end += 1
                else:
                    replacements[marker] = ".*"
            else:
                replacements[marker] = "[^/]*"
            protected.append(marker)
            index = end
            continue
        else:
            protected.append(char)
        index += 1
    return "".join(protected), replacements
