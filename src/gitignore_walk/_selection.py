"""Explicit, one-time backend selection; never switch during a query or walk."""

from __future__ import annotations

# pyright: reportPrivateUsage=false
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ._git import GitStandardPolicy
from ._portable import _DEFAULT_INITIAL_EXCLUDES, GitIgnorePolicy, IgnorePolicy
from .errors import GitIgnoreError


@dataclass(frozen=True, slots=True)
class PolicySelection:
    """Selected policy and diagnostics, separate from query and traversal output."""

    policy: IgnorePolicy
    backend: Literal["portable", "git"]
    fallback_reason: Literal["git-executable-missing"] | None = None


def _executable_missing(
    executable: str, environment: Mapping[str, str], error: FileNotFoundError
) -> bool:
    # ENOENT can also mean an existing script's interpreter or binary's loader is
    # missing. Likewise, which() conflates absence with lack of execute permission.
    # Conservatively require every candidate to be absent, including dangling links.
    if os.name == "nt":
        # CreateProcess reports missing programs as ERROR_FILE_NOT_FOUND (2).
        # Missing DLLs (126), bad images (193), and access errors (5) must not fall
        # back. Also reject an identifiable existing executable or script.
        if getattr(error, "winerror", None) != 2:
            return False
        if shutil.which(executable, path=os.pathsep.join(os.get_exec_path(environment))):
            return False
        candidates = [Path(executable), Path(executable + ".exe")]
    elif os.path.dirname(executable):
        candidates = [Path(executable)]
    else:
        candidates = [Path(directory) / executable for directory in os.get_exec_path(environment)]
    for candidate in candidates:
        try:
            candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return False
        return False
    return True


def select_policy(
    root: str | os.PathLike[str],
    *,
    mode: Literal["portable", "git", "prefer-git"] = "portable",
    initial_excludes: Sequence[str] = _DEFAULT_INITIAL_EXCLUDES,
    git_executable: str = "git",
    environment: Mapping[str, str] | None = None,
    timeout: float = 30.0,
) -> PolicySelection:
    """Select eagerly; only prefer-git can fall back on confirmed missing Git.

    The environment is complete, not an overlay. Portable evaluation uses only its
    HOME/USERPROFILE and XDG_CONFIG_HOME locations, never Git configuration. The
    returned policy does not retry selection if subsequent operations fail.
    """
    if mode not in ("portable", "git", "prefer-git"):
        raise ValueError(f"unknown policy mode: {mode}")
    effective_environment = dict(os.environ if environment is None else environment)
    if mode != "portable":
        try:
            policy = GitStandardPolicy(
                root,
                initial_excludes=initial_excludes,
                git_executable=git_executable,
                environment=effective_environment,
                timeout=timeout,
            )
        except GitIgnoreError as error:
            if not (
                mode == "prefer-git"
                and isinstance(error.__cause__, FileNotFoundError)
                and _executable_missing(git_executable, effective_environment, error.__cause__)
            ):
                raise
        else:
            return PolicySelection(policy, "git")
    portable = GitIgnorePolicy(
        root,
        initial_excludes=initial_excludes,
        environment=None if environment is None else effective_environment,
    )
    return PolicySelection(
        portable, "portable", "git-executable-missing" if mode == "prefer-git" else None
    )
