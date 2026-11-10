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
) -> Path | None:
    """Resolve configured ``core.excludesFile`` with Git, preserving scope and empty cases.

    The global value overrides the system value. If neither is set, select ``default_path``. An
    explicitly empty value disables the global ignore source. Other values are expanded and
    returned by Git's ``--path`` option.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Git config timeout must be finite and positive")

    system_found, system_path = _read_scoped_core_excludes_file(
        root,
        scope="--system",
        environment=environment,
        git_executable=git_executable,
        timeout=timeout,
    )
    global_found, global_path = _read_scoped_core_excludes_file(
        root,
        scope="--global",
        environment=environment,
        git_executable=git_executable,
        timeout=timeout,
    )
    if global_found:
        return global_path
    if system_found:
        return system_path
    return default_path


def _read_scoped_core_excludes_file(
    root: Path,
    *,
    scope: str,
    environment: Mapping[str, str] | None,
    git_executable: str,
    timeout: float,
) -> tuple[bool, Path | None]:
    """Return whether a scope sets the key and its expanded path, if nonempty."""
    try:
        result = subprocess.run(
            [
                git_executable,
                "config",
                scope,
                "--includes",
                "--path",
                "--get",
                "core.excludesFile",
            ],
            cwd=root,
            env=None if environment is None else dict(environment),
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GitIgnoreError(
            f"unable to read Git {scope[2:]} core.excludesFile configuration: {error}",
            operation="configuration",
        ) from error

    if result.returncode == 1:
        return False, None
    if result.returncode != 0 or result.stderr:
        detail = os.fsdecode(result.stderr).strip() or f"exit status {result.returncode}"
        raise GitIgnoreError(
            f"Git {scope[2:]} core.excludesFile lookup failed: {detail}",
            operation="configuration",
        )

    value = result.stdout.removesuffix(b"\n").removesuffix(b"\r")
    if b"\n" in value or b"\r" in value:
        raise GitIgnoreError(
            f"Git {scope[2:]} core.excludesFile resolved to a path containing a line break",
            operation="configuration",
        )
    if not value:
        return True, None
    return True, Path(os.fsdecode(value)).expanduser()
