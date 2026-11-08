"""Small package utilities shared by implementation modules."""

from __future__ import annotations

import os


def is_windows() -> bool:
    """Return whether the current Python process runs on Windows."""
    return os.name == "nt"
