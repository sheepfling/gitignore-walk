"""Small platform queries shared by package modules."""

from __future__ import annotations

import os


def is_windows() -> bool:
    """Return whether the current Python process runs on Windows."""
    return os.name == "nt"
