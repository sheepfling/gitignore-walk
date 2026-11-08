"""Protocols for pluggable ignore-rule parsing and matching backends."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, TypeVar

__all__ = ["GitIgnoreMatcher"]

SpecT = TypeVar("SpecT")


@dataclass(frozen=True, slots=True)
class GitIgnoreMatch:
    """The final matching rule from one ignore file.

    Attributes:
        ignored: Whether the rule excludes the path; negation rules set this to ``False``.
        source: Human-readable origin of the ignore file.
        pattern: Pattern text as written in that file.
        line: One-based line number of the matching pattern.
        scope: Base path that determines the rule's effective path scope.
    """

    ignored: bool
    source: str
    pattern: str
    line: int
    scope: str | None = None


class GitIgnoreMatcher(Protocol[SpecT]):
    """Backend contract for compiling one ignore file and checking paths against it."""

    @property
    def name(self) -> str:
        """Return a stable display name for the selected backend."""

        ...

    def parse(self, lines: Iterable[str], *, source: str) -> SpecT:
        """Compile ordered rules from one ignore file into this backend's spec type."""

        ...

    def match(
        self,
        spec: SpecT,
        relative: str,
        *,
        source: str,
        is_directory: bool,
    ) -> GitIgnoreMatch | None:
        """Return the final matching rule and provenance, or ``None`` if none match."""

        ...
