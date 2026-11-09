"""Errors raised while loading and evaluating Mercurial ignore sources."""

from __future__ import annotations


class MercurialIgnoreError(RuntimeError):
    """A Mercurial ignore source could not be represented safely.

    Attributes:
        operation: Operation that failed, such as ``"read"``, ``"parse"``, or ``"config"``.
        source: Source path associated with the error, when known.
        line: One-based source line associated with the error, when known.
    """

    def __init__(
        self,
        message: str,
        *,
        operation: str,
        source: str | None = None,
        line: int | None = None,
    ) -> None:
        """Create an error with optional source and line context."""
        super().__init__(message)
        self.operation = operation
        self.source = source
        self.line = line
