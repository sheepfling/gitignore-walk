"""Shared errors for portable and Git-native ignore policies."""


class GitIgnoreError(RuntimeError):
    """Raised when an ignore policy cannot be interpreted safely."""
