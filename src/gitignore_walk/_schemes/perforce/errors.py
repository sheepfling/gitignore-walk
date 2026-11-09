"""Errors raised while loading or evaluating Perforce ignore files."""

from __future__ import annotations


class PerforceIgnoreError(RuntimeError):
    """Raised when a configured Perforce ignore source cannot be read safely.

    Attributes:
        operation: Failed operation, such as ``"read"``, ``"parse"``, ``"config"``, or
            ``"workspace"``.
        source: Ignore source associated with the failure.
        line: One-based source line when a pattern failed to compile.
    """

    def __init__(
        self,
        message: str,
        *,
        operation: str,
        source: str | None = None,
        line: int | None = None,
    ) -> None:
        """Create a Perforce error with operation and optional source context."""
        super().__init__(message)
        self.operation = operation
        self.source = source
        self.line = line
