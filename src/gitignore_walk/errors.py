"""Shared errors for portable and Git-native ignore policies."""

from __future__ import annotations


class GitIgnoreError(RuntimeError):
    """Raised when an ignore policy cannot be interpreted safely.

    Attributes:
        operation: Operation that failed, such as ``"read"`` or ``"parse"``.
        path: Filesystem path involved in the failure, when available.
        source: Human-readable ignore source involved in the failure, when available.
    """

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        path: str | None = None,
        source: str | None = None,
    ) -> None:
        """Create an error with optional operation, path, and source context."""
        super().__init__(message)
        self.operation = operation
        self.path = path
        self.source = source


class GitIgnoreParseError(GitIgnoreError):
    """Raised when an ignore source contains a malformed pattern.

    Attributes:
        source: Ignore source containing the invalid pattern.
        line: One-based line number of the invalid pattern.
        pattern: Original text of the invalid pattern.
        reason: Explanation of why the pattern is invalid.
    """

    def __init__(
        self,
        message: str,
        *,
        source: str,
        line: int,
        pattern: str,
        reason: str,
    ) -> None:
        """Create a parse error with source location and pattern details."""
        super().__init__(message, operation="parse", source=source)
        self.source = source
        self.line = line
        self.pattern = pattern
        self.reason = reason
