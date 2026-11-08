"""Data records and matcher protocol shared by ignore parsing and policy code."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Generic, TypeVar

from ._ignore_protocols import GitIgnoreMatch, GitIgnoreMatcher
from ._patterns import GitIgnorePattern

SpecT = TypeVar("SpecT")

__all__ = ["GitIgnoreFile", "GitIgnoreMatch", "GitIgnoreSpec"]


@dataclass(frozen=True, slots=True)
class GitIgnoreSpec:
    """The ordered patterns parsed from a single ignore file.

    Attributes:
        patterns: Parsed rules in source order. Matching uses their line numbers to preserve
            Git's last-match-wins behavior.
    """

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
class GitIgnoreFile(Generic[SpecT]):
    """An ignore file's provenance, backend-specific compiled rules, and matcher.

    Attributes:
        source: Human-readable description of the ignore-file origin.
        spec: Compiled rule set produced by ``matcher``; its type is preserved by this generic.
        matcher: Backend that compiled ``spec`` and can evaluate paths against it.
    """

    source: str
    spec: SpecT
    matcher: GitIgnoreMatcher[SpecT]
