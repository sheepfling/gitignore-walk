"""Symbolic names for environment variables used by the package."""

from __future__ import annotations

from typing import Final


class EnvVar:
    """Registry of environment-variable names used by package code.

    Attributes:
        DEBIAN_FRONTEND: Suppresses interactive package-manager prompts in controlled subprocesses.
        GIT_AUTHOR_EMAIL, GIT_AUTHOR_NAME, GIT_COMMITTER_EMAIL, GIT_COMMITTER_NAME: Git identity.
        GIT_COMMON_DIR, GIT_DIR, GIT_INDEX_FILE, GIT_PREFIX, GIT_WORK_TREE: Ambient repository
            selection state, removed before native-policy Git queries.
        GIT_CONFIG_COUNT, GIT_CONFIG_KEY_0, GIT_CONFIG_VALUE_0: Git's command-environment config
            override mechanism.
        GIT_CONFIG_GLOBAL, GIT_CONFIG_NOSYSTEM, GIT_CONFIG_SYSTEM: Git config file controls.
        GIT_TERMINAL_PROMPT: Controls Git's terminal prompting.
        HOME, LOCALAPPDATA, USERPROFILE: User-home locations used by Git and Windows.
        PYTHONHOME, PYTHONPATH: Python runtime import and prefix configuration.
        TEMP, TMP, TMPDIR: Temporary-directory environment variables.
        UV_CACHE_DIR: Override for the UV package-cache location.
        XDG_CONFIG_HOME: User configuration root used for Git's XDG config lookup.
        GIT_PREFIX_FILTER: Prefix used to select Git-related variables in verification tooling.
    """

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
    GIT_PREFIX_FILTER: Final = "GIT_"
