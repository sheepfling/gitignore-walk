"""Errors raised while querying Sapling working-copy state."""

from __future__ import annotations


class SaplingIgnoreError(RuntimeError):
    """A Sapling native query failed or returned an unsupported result.

    Attributes:
        operation: Native operation that failed, such as ``"membership"``.
    """

    def __init__(self, message: str, *, operation: str) -> None:
        """Create an error with the native operation that failed."""
        super().__init__(message)
        self.operation = operation
