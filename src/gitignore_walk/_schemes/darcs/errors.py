"""Errors raised while querying Darcs boring-file candidate state."""

from __future__ import annotations


class DarcsBoringError(RuntimeError):
    """Raised when Darcs cannot provide a reliable boring-file inventory.

    Attributes:
        operation: Native operation that failed, such as ``"whatsnew"`` or ``"show-files"``.
    """

    def __init__(self, message: str, *, operation: str) -> None:
        """Create an error with the failed native operation."""
        super().__init__(message)
        self.operation = operation
