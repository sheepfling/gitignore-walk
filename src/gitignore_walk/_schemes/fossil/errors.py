"""Errors raised while discovering Fossil ignore settings."""

from __future__ import annotations


class FossilIgnoreError(RuntimeError):
    """Raised when Fossil workspace or effective setting discovery fails.

    Attributes:
        operation: Native Fossil operation that failed.
        path: Workspace path associated with the failure, when known.
    """

    def __init__(self, message: str, *, operation: str, path: str | None = None) -> None:
        """Create an error with the native operation and optional path context."""
        super().__init__(message)
        self.operation = operation
        self.path = path
