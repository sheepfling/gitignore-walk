"""Typed policy configuration and eager, one-time resolver selection."""

from __future__ import annotations

# pyright: reportPrivateUsage=false
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, NoReturn, TypeAlias, TypeGuard, overload

from ._git import GitStandardPolicy
from ._portable import _DEFAULT_INITIAL_EXCLUDES, GitIgnorePolicy
from .errors import GitIgnoreError


@dataclass(frozen=True, slots=True)
class PortablePolicyConfig:
    """Request portable ignore evaluation.

    Attributes:
        initial_excludes: Hard baseline rules applied before ignore-file sources.
        environment: Optional complete environment used to locate conventional global ignores.
    """

    mode: Literal["portable"] = field(default="portable", init=False)
    initial_excludes: Sequence[str] = _DEFAULT_INITIAL_EXCLUDES
    environment: Mapping[str, str] | None = None


@dataclass(frozen=True, slots=True)
class GitPolicyConfig:
    """Require native Git and propagate every Git execution or configuration failure.

    Attributes:
        initial_excludes: Hard baseline rules applied before invoking Git.
        git_executable: Executable name or path used to invoke Git.
        environment: Optional complete environment for Git subprocesses.
        timeout: Maximum duration in seconds for each Git subprocess.
    """

    mode: Literal["git"] = field(default="git", init=False)
    initial_excludes: Sequence[str] = _DEFAULT_INITIAL_EXCLUDES
    git_executable: str = "git"
    environment: Mapping[str, str] | None = None
    timeout: float = 30.0


@dataclass(frozen=True, slots=True)
class PreferGitPolicyConfig:
    """Prefer native Git and allow fallback only when its executable is absent.

    Attributes:
        initial_excludes: Hard baseline rules applied before either resolver.
        git_executable: Executable name or path used to invoke Git.
        environment: Optional complete environment for Git and portable fallback.
        timeout: Maximum duration in seconds for each Git subprocess.
    """

    mode: Literal["prefer-git"] = field(default="prefer-git", init=False)
    initial_excludes: Sequence[str] = _DEFAULT_INITIAL_EXCLUDES
    git_executable: str = "git"
    environment: Mapping[str, str] | None = None
    timeout: float = 30.0


#: Discriminated configuration union accepted by :func:`select_policy`.
PolicyConfig: TypeAlias = PortablePolicyConfig | GitPolicyConfig | PreferGitPolicyConfig


@dataclass(frozen=True, slots=True)
class PortablePolicySelection:
    """Portable backend selection, either requested directly or chosen as fallback.

    Attributes:
        mode: Requested selection strategy.
        backend: Actual resolver selected; always ``"portable"`` for this variant.
        policy: Portable policy used for queries and traversal.
        fallback_reason: Why Git was unavailable, or ``None`` for portable mode.
    """

    mode: Literal["portable", "prefer-git"]
    backend: Literal["portable"] = field(default="portable", init=False)
    policy: GitIgnorePolicy
    fallback_reason: Literal["git-executable-missing"] | None = None


@dataclass(frozen=True, slots=True)
class GitPolicySelection:
    """Native Git backend selection, either required or chosen by preference.

    Attributes:
        mode: Requested selection strategy.
        backend: Actual resolver selected; always ``"git"`` for this variant.
        policy: Git-backed policy used for queries and traversal.
        fallback_reason: Always ``None`` because native Git was selected.
    """

    mode: Literal["git", "prefer-git"]
    backend: Literal["git"] = field(default="git", init=False)
    policy: GitStandardPolicy
    fallback_reason: None = None


#: Discriminated selection union; ``backend`` narrows ``policy`` to its concrete type.
PolicySelection: TypeAlias = PortablePolicySelection | GitPolicySelection


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


def _is_policy_config(value: object) -> TypeGuard[PolicyConfig]:
    """Return whether a dynamically supplied value is a supported policy config."""
    return isinstance(value, (PortablePolicyConfig, GitPolicyConfig, PreferGitPolicyConfig))


def _assert_never(value: NoReturn) -> NoReturn:
    """Fail if the typed config switch does not handle a newly added variant."""
    raise AssertionError(f"unhandled policy configuration: {value!r}")


@overload
def select_policy(root: str | os.PathLike[str], config: None = None) -> PortablePolicySelection: ...


@overload
def select_policy(
    root: str | os.PathLike[str], config: PortablePolicyConfig
) -> PortablePolicySelection: ...


@overload
def select_policy(root: str | os.PathLike[str], config: GitPolicyConfig) -> GitPolicySelection: ...


@overload
def select_policy(
    root: str | os.PathLike[str], config: PreferGitPolicyConfig
) -> PolicySelection: ...


@overload
def select_policy(root: str | os.PathLike[str], config: PolicyConfig) -> PolicySelection: ...


def select_policy(
    root: str | os.PathLike[str], config: PolicyConfig | None = None
) -> PolicySelection:
    """Resolve one policy eagerly from a tagged config; never switch during a walk.

    ``PreferGitPolicyConfig`` falls back only when Git's executable is confirmed absent.
    Permissions, timeouts, invalid repositories, malformed configuration, missing
    interpreters/loaders, and later subprocess failures remain errors. The returned
    selection keeps the requested ``mode`` distinct from the resolved ``backend``.
    """
    selected: object = PortablePolicyConfig() if config is None else config
    if not _is_policy_config(selected):
        raise TypeError(f"unsupported policy configuration: {type(selected).__name__}")

    if selected.mode == "portable":
        return PortablePolicySelection(
            mode=selected.mode,
            policy=GitIgnorePolicy(
                root,
                initial_excludes=selected.initial_excludes,
                environment=selected.environment,
            ),
        )

    elif selected.mode == "git":
        return GitPolicySelection(
            mode=selected.mode,
            policy=GitStandardPolicy(
                root,
                initial_excludes=selected.initial_excludes,
                git_executable=selected.git_executable,
                environment=selected.environment,
                timeout=selected.timeout,
            ),
        )

    elif selected.mode == "prefer-git":
        effective_environment = dict(
            os.environ if selected.environment is None else selected.environment
        )
        try:
            policy = GitStandardPolicy(
                root,
                initial_excludes=selected.initial_excludes,
                git_executable=selected.git_executable,
                environment=effective_environment,
                timeout=selected.timeout,
            )
        except GitIgnoreError as error:
            cause = error.__cause__
            if not (
                isinstance(cause, FileNotFoundError)
                and _executable_missing(selected.git_executable, effective_environment, cause)
            ):
                raise
        else:
            return GitPolicySelection(mode=selected.mode, policy=policy)

        return PortablePolicySelection(
            mode=selected.mode,
            policy=GitIgnorePolicy(
                root,
                initial_excludes=selected.initial_excludes,
                environment=selected.environment,
            ),
            fallback_reason="git-executable-missing",
        )

    _assert_never(selected)
