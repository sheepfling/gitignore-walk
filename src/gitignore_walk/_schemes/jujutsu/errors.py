"""Errors raised while querying Jujutsu working-copy state."""

from __future__ import annotations


class JujutsuIgnoreError(RuntimeError):
    """A Jujutsu native query failed or returned an invalid saved-tree path.

    Attributes:
        operation: Native operation that failed, such as ``"membership"``.
    """

    def __init__(self, message: str, *, operation: str) -> None:
        """Create an error with the native operation that failed."""
        super().__init__(message)
        self.operation = operation
