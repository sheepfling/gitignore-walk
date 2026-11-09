"""Subversion working-copy glob matching, independent of Python's fnmatch dialect."""

from __future__ import annotations

import re


def split_svn_property_patterns(value: str) -> tuple[str, ...]:
    """Split a working-copy ignore property on its native CR/LF delimiters only."""
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return tuple(pattern for pattern in normalized.split("\n") if pattern)


def matches_svn_glob(name: str, pattern: str) -> bool:
    """Match one Subversion status ignore pattern against a child basename.

    The working-copy status implementation uses APR glob matching. In the tested SVN profile,
    backslash quotes the next character and both ``!`` and ``^`` negate a bracket class. Python's
    :mod:`fnmatch` differs on those forms, so translate the small APR glob language explicitly.
    """
    return re.fullmatch(_translate_svn_glob(pattern), name, flags=re.DOTALL) is not None


def _translate_svn_glob(pattern: str) -> str:
    pieces = ["^"]
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "\\":
            index += 1
            if index < len(pattern):
                pieces.append(re.escape(pattern[index]))
            else:
                pieces.append(re.escape("\\"))
        elif character == "*":
            pieces.append(".*")
        elif character == "?":
            pieces.append(".")
        elif character == "[":
            translated, end = _translate_character_class(pattern, index)
            pieces.append(translated)
            index = end
        else:
            pieces.append(re.escape(character))
        index += 1
    pieces.append("$")
    return "".join(pieces)


def _translate_character_class(pattern: str, start: int) -> tuple[str, int]:
    """Translate a bracket class, or return a literal opening bracket if it is malformed."""
    end = start + 1
    if end < len(pattern) and pattern[end] in "!^":
        end += 1
    if end < len(pattern) and pattern[end] == "]":
        end += 1
    while end < len(pattern):
        if pattern[end] == "\\" and end + 1 < len(pattern):
            end += 2
            continue
        if pattern[end] == "]":
            break
        end += 1
    if end == len(pattern):
        return re.escape("["), start

    content = pattern[start + 1 : end]
    negated = content.startswith(("!", "^"))
    if negated:
        content = content[1:]
    translated_content: list[str] = []
    index = 0
    while index < len(content):
        character = content[index]
        if character == "\\" and index + 1 < len(content):
            index += 1
            escaped = content[index]
            translated_content.append("\\" + escaped if escaped in "^-]\\-" else escaped)
        elif character in "[^]\\":
            translated_content.append("\\" + character)
        else:
            translated_content.append(character)
        index += 1
    prefix = "^" if negated else ""
    return "[" + prefix + "".join(translated_content) + "]", end
