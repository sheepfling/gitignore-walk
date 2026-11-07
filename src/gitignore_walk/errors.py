"""Shared errors for portable and Git-native ignore policies."""

from __future__ import annotations


class GitIgnoreError(RuntimeError):
    """Raised when an ignore policy cannot be interpreted safely."""

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        path: str | None = None,
        source: str | None = None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.path = path
        self.source = source


class GitIgnoreParseError(GitIgnoreError):
    """Raised when an ignore source contains a malformed pattern."""

    def __init__(
        self,
        message: str,
        *,
        source: str,
        line: int,
        pattern: str,
        reason: str,
    ) -> None:
        super().__init__(message, operation="parse", source=source)
        self.source = source
        self.line = line
        self.pattern = pattern
        self.reason = reason
