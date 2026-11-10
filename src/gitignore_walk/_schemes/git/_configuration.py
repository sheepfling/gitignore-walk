"""Read selected Git configuration values needed by Git-compatible policies."""

from __future__ import annotations

import math
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

from ...errors import GitIgnoreError


def resolve_core_excludes_file(
    root: Path,
    *,
    environment: Mapping[str, str] | None,
    git_executable: str,
    timeout: float,
    default_path: Path | None,
    git_dir: Path | None = None,
) -> Path | None:
    """Resolve the effective ``core.excludesFile`` through Git's config precedence.

    Git evaluates ordinary and conditional includes across system, global, and repository scopes.
    An unset key selects ``default_path``; an explicitly empty value disables the global source.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Git config timeout must be finite and positive")

    try:
        result = subprocess.run(
            [git_executable, "config", "--includes", "--path", "--get", "core.excludesFile"],
            cwd=root,
            env=_environment_with_git_dir(environment, git_dir),
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GitIgnoreError(
            f"unable to read Git core.excludesFile configuration: {error}",
            operation="configuration",
        ) from error

    if result.returncode == 1:
        return default_path
    if result.returncode != 0 or result.stderr:
        detail = os.fsdecode(result.stderr).strip() or f"exit status {result.returncode}"
        raise GitIgnoreError(
            f"Git core.excludesFile lookup failed: {detail}",
            operation="configuration",
        )

    value = result.stdout.removesuffix(b"\n").removesuffix(b"\r")
    if b"\n" in value or b"\r" in value:
        raise GitIgnoreError(
            "Git core.excludesFile resolved to a path containing a line break",
            operation="configuration",
        )
    if not value:
        return None
    return Path(os.fsdecode(value)).expanduser()


def _environment_with_git_dir(
    environment: Mapping[str, str] | None, git_dir: Path | None
) -> Mapping[str, str] | None:
    """Set optional Git repository context without overriding a caller-provided ``GIT_DIR``."""
    if git_dir is None:
        return environment
    result = dict(os.environ if environment is None else environment)
    result.setdefault("GIT_DIR", os.fspath(git_dir))
    return result
