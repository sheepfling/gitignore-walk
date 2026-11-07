"""Protocols for pluggable ignore-rule parsing and matching backends."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from ._ignore_types import GitIgnoreMatch

__all__ = ["GitIgnoreMatcher"]


class GitIgnoreMatcher(Protocol):
    """Backend contract for compiling one ignore file and checking paths against it."""

    @property
    def name(self) -> str:
        """Return a stable display name for the selected backend."""

        ...

    def parse(self, lines: Iterable[str], *, source: str) -> object:
        """Compile the ordered rules from one ignore file."""

        ...

    def match(
        self,
        spec: object,
        relative: str,
        *,
        source: str,
        is_directory: bool,
    ) -> GitIgnoreMatch | None:
        """Return the final matching rule with its provenance, if any."""

        ...
