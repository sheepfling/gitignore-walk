"""Canonical names for environment variables used by the package and tooling."""

from typing import Final

class EnvVar:
    """Symbolic registry for environment variables read or written here."""

    # Git process configuration and identity, used by the native policy and its fixtures.
    DEBIAN_FRONTEND: Final = "DEBIAN_FRONTEND"
    GIT_AUTHOR_EMAIL: Final = "GIT_AUTHOR_EMAIL"
    GIT_AUTHOR_NAME: Final = "GIT_AUTHOR_NAME"
    GIT_COMMITTER_EMAIL: Final = "GIT_COMMITTER_EMAIL"
    GIT_COMMITTER_NAME: Final = "GIT_COMMITTER_NAME"
    GIT_COMMON_DIR: Final = "GIT_COMMON_DIR"
    GIT_CONFIG_COUNT: Final = "GIT_CONFIG_COUNT"
    GIT_CONFIG_GLOBAL: Final = "GIT_CONFIG_GLOBAL"
    GIT_CONFIG_KEY_0: Final = "GIT_CONFIG_KEY_0"
    GIT_CONFIG_NOSYSTEM: Final = "GIT_CONFIG_NOSYSTEM"
    GIT_CONFIG_SYSTEM: Final = "GIT_CONFIG_SYSTEM"
    GIT_CONFIG_VALUE_0: Final = "GIT_CONFIG_VALUE_0"
    GIT_DIR: Final = "GIT_DIR"
    GIT_INDEX_FILE: Final = "GIT_INDEX_FILE"
    GIT_PREFIX: Final = "GIT_PREFIX"
    GIT_TERMINAL_PROMPT: Final = "GIT_TERMINAL_PROMPT"
    GIT_WORK_TREE: Final = "GIT_WORK_TREE"

    # User locations used by Git and Windows temporary-directory discovery.
    HOME: Final = "HOME"
    LOCALAPPDATA: Final = "LOCALAPPDATA"
    PYTHONHOME: Final = "PYTHONHOME"
    PYTHONPATH: Final = "PYTHONPATH"
    TEMP: Final = "TEMP"
    TMP: Final = "TMP"
    TMPDIR: Final = "TMPDIR"
    USERPROFILE: Final = "USERPROFILE"
    UV_CACHE_DIR: Final = "UV_CACHE_DIR"
    XDG_CONFIG_HOME: Final = "XDG_CONFIG_HOME"

    # Python runtime and verification-tool settings.
    # GIT_ is a prefix filter used to isolate Git-related environment variables in tests.
    GIT_PREFIX_FILTER: Final = "GIT_"
