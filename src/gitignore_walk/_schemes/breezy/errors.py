"""Errors raised while discovering and compiling Breezy ignore rules."""

from __future__ import annotations


class BreezyIgnoreError(RuntimeError):
    """Raised when Breezy defaults or ignore sources cannot be loaded.

    Attributes:
        operation: Breezy operation that failed.
        source: Ignore source associated with the failure, when known.
        line: One-based source line associated with the failure, when known.
    """

    def __init__(
        self,
        message: str,
        *,
        operation: str,
        source: str | None = None,
        line: int | None = None,
    ) -> None:
        """Create an error with operation and optional source context."""
        super().__init__(message)
        self.operation = operation
        self.source = source
        self.line = line
