"""Data records and matcher protocol shared by ignore parsing and policy code."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

from ._patterns import GitIgnorePattern

if TYPE_CHECKING:
    from ._ignore_protocols import GitIgnoreMatcher

__all__ = ["GitIgnoreFile", "GitIgnoreMatch", "GitIgnoreSpec"]


@dataclass(frozen=True, slots=True)
class GitIgnoreSpec:
    """The ordered patterns parsed from a single ignore file."""

    patterns: tuple[GitIgnorePattern, ...]
    _first_character_groups: Mapping[str, tuple[GitIgnorePattern, ...]] = field(
        init=False, repr=False, compare=False, hash=False
    )
    _fallback_patterns: tuple[GitIgnorePattern, ...] = field(
        init=False, repr=False, compare=False, hash=False
    )

    def __post_init__(self) -> None:
        groups: dict[str, list[GitIgnorePattern]] = {}
        fallback: list[GitIgnorePattern] = []
        for pattern in self.patterns:
            if pattern.first_literal is None:
                fallback.append(pattern)
            else:
                groups.setdefault(pattern.first_literal, []).append(pattern)
        object.__setattr__(
            self,
            "_first_character_groups",
            MappingProxyType({key: tuple(value) for key, value in groups.items()}),
        )
        object.__setattr__(self, "_fallback_patterns", tuple(fallback))

    def candidate_patterns(self, first_characters: Iterable[str]) -> tuple[GitIgnorePattern, ...]:
        """Return rules that could match candidates beginning with these characters."""
        candidates = list(self._fallback_patterns)
        for character in first_characters:
            candidates.extend(self._first_character_groups.get(character, ()))
        return tuple(candidates)


@dataclass(frozen=True, slots=True)
class GitIgnoreFile:
    """An ignore file's source and compiled rules."""

    source: str
    spec: object
    matcher: GitIgnoreMatcher


@dataclass(frozen=True, slots=True)
class GitIgnoreMatch:
    """The final matching rule from one ignore file."""

    ignored: bool
    source: str
    pattern: str
    line: int
