"""Subversion working-copy property policy backed by the native client."""

from .errors import SubversionIgnoreError
from .policy import SubversionIgnorePolicy

__all__ = ["SubversionIgnoreError", "SubversionIgnorePolicy"]
