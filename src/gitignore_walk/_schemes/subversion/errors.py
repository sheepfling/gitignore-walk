"""Errors raised by the Subversion ignore policy."""

from __future__ import annotations


class SubversionIgnoreError(RuntimeError):
    """Raised when Subversion workspace or ignore-property discovery fails.

    Attributes:
        operation: Native Subversion operation that failed.
        path: Working-copy path associated with the failed operation, when known.
    """

    def __init__(self, message: str, *, operation: str, path: str | None = None) -> None:
        """Create an error with the native operation and optional path context."""
        super().__init__(message)
        self.operation = operation
        self.path = path
