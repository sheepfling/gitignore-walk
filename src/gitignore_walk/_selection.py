"""Typed policy configuration and eager, one-time resolver selection."""

from __future__ import annotations

# pyright: reportPrivateUsage=false
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, NoReturn, TypeAlias, TypeGuard, overload

from ._schemes.breezy import BreezyIgnorePolicy
from ._schemes.darcs import DarcsBoringPolicy
from ._schemes.fossil import FossilIgnorePolicy
from ._schemes.git import GitIgnorePolicy, GitStandardPolicy
from ._schemes.git.portable import _DEFAULT_INITIAL_EXCLUDES
from ._schemes.jujutsu import JujutsuIgnorePolicy
from ._schemes.mercurial import MercurialIgnorePolicy
from ._schemes.perforce import PerforceIgnorePolicy
from ._schemes.sapling import SaplingIgnorePolicy
from ._schemes.subversion import SubversionIgnorePolicy
from ._util import is_windows
from .errors import GitIgnoreError


@dataclass(frozen=True, slots=True)
class PortablePolicyConfig:
    """Request portable ignore evaluation.

    Attributes:
        initial_excludes: Hard baseline rules replacing the default ``(".git",)`` baseline.
        environment: Optional complete environment replacing the process environment. In portable
            mode, HOME/USERPROFILE and XDG_CONFIG_HOME locate the conventional global ignore file;
            other variables are not consulted.
    """

    mode: Literal["portable"] = field(default="portable", init=False)
    initial_excludes: Sequence[str] = _DEFAULT_INITIAL_EXCLUDES
    environment: Mapping[str, str] | None = None


@dataclass(frozen=True, slots=True)
class GitPolicyConfig:
    """Require native Git and propagate every Git execution or configuration failure.

    Attributes:
        initial_excludes: Hard baseline rules replacing the default ``(".git",)`` baseline.
        git_executable: Executable name or path used to invoke Git.
        environment: Optional complete environment replacing the process environment, not an
            overlay. It is passed to Git subprocesses; include PATH and any required Git settings.
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
        initial_excludes: Hard baseline rules replacing the default ``(".git",)`` baseline.
        git_executable: Executable name or path used to invoke Git.
        environment: Optional complete environment replacing the process environment, not an
            overlay. It is passed to Git subprocesses and supplies HOME/USERPROFILE and
            XDG_CONFIG_HOME for portable fallback; include PATH and any required Git settings.
        timeout: Maximum duration in seconds for each Git subprocess.
    """

    mode: Literal["prefer-git"] = field(default="prefer-git", init=False)
    initial_excludes: Sequence[str] = _DEFAULT_INITIAL_EXCLUDES
    git_executable: str = "git"
    environment: Mapping[str, str] | None = None
    timeout: float = 30.0


@dataclass(frozen=True, slots=True)
class MercurialPolicyConfig:
    """Request portable evaluation of Mercurial ignore rules.

    Attributes:
        ignore_files: Additional ignore files, such as files configured with Mercurial's
            ``ui.ignore`` setting. Relative paths are resolved from the Mercurial workspace root.
        read_client_config: Ask ``hg config`` to discover the effective ``ui.ignore`` files.
        hg_executable: Mercurial executable used for config discovery and membership queries.
        environment: Complete environment for Mercurial queries, or the current environment.
        timeout: Maximum duration in seconds for each Mercurial client query.
        initial_excludes: Walker baseline exclusions, defaulting to Mercurial's ``.hg`` metadata.
        membership_aware: Query native status to report known versioned or unversioned paths.
    """

    mode: Literal["mercurial"] = field(default="mercurial", init=False)
    ignore_files: Sequence[str | os.PathLike[str]] = ()
    read_client_config: bool = False
    hg_executable: str = "hg"
    environment: Mapping[str, str] | None = None
    timeout: float = 30.0
    initial_excludes: Sequence[str] = (".hg",)
    membership_aware: bool = False


@dataclass(frozen=True, slots=True)
class PerforcePolicyConfig:
    """Request portable P4IGNORE evaluation within a caller-selected traversal root.

    Attributes:
        p4ignore: Optional semicolon-delimited list overriding ``P4IGNORE`` from the environment.
            When neither is set, the evaluator checks `.p4ignore` and `p4ignore.txt`.
        environment: Optional complete environment replacing the process environment. The current
            evaluator reads ``P4IGNORE`` only unless ``read_client_config`` is enabled.
        read_client_config: Ask the P4 client for effective ``P4IGNORE`` settings at each target.
        discover_client_workspace: Ask a connected P4 client with ``p4 -ztag info`` for its root.
            The caller's root remains the traversal and target boundary.
        client_view_aware: Ask the configured client whether files are mapped in its view when
            walking. Requires ``discover_client_workspace=True``; this does not change P4IGNORE
            decisions or versioned membership. Directories remain traversable because unmapped
            directories can contain mapped descendants.
        p4_executable: P4 client used for optional ``p4 set`` and ``p4 -ztag info`` queries.
        timeout: Maximum duration in seconds for each P4 configuration, workspace, or client-view
            query.
        initial_excludes: Hard walker baseline exclusions, defaulting to none.
    """

    mode: Literal["perforce"] = field(default="perforce", init=False)
    p4ignore: str | None = None
    environment: Mapping[str, str] | None = None
    read_client_config: bool = False
    discover_client_workspace: bool = False
    client_view_aware: bool = False
    p4_executable: str = "p4"
    timeout: float = 30.0
    initial_excludes: Sequence[str] = ()


@dataclass(frozen=True, slots=True)
class SubversionPolicyConfig:
    """Request native discovery of Subversion working-copy ignore properties.

    Attributes:
        svn_executable: Subversion client used to discover working-copy properties.
        config_dir: Optional runtime configuration directory passed to the native client. Its
            ``config`` file overrides standard config sources; without it, standard system and
            per-user files are discovered from ``environment``.
        environment: Optional complete environment passed to ``svn``.
        timeout: Maximum duration in seconds for each Subversion command.
        membership_aware: Query native status to report whether each path is versioned.
        global_ignores: Additional runtime ``global-ignores`` patterns supplied by the caller.
        initial_excludes: Walker baseline exclusions, defaulting to Subversion's ``.svn`` metadata.
    """

    mode: Literal["subversion"] = field(default="subversion", init=False)
    svn_executable: str = "svn"
    config_dir: str | os.PathLike[str] | None = None
    environment: Mapping[str, str] | None = None
    timeout: float = 30.0
    membership_aware: bool = False
    global_ignores: Sequence[str] = ()
    initial_excludes: Sequence[str] = (".svn",)


@dataclass(frozen=True, slots=True)
class FossilPolicyConfig:
    """Request Fossil's effective ``ignore-glob`` setting for a checkout.

    Attributes:
        fossil_executable: Executable name or path used to query Fossil settings.
        environment: Optional complete environment passed to Fossil subprocesses.
        timeout: Maximum duration in seconds for each Fossil subprocess.
        membership_aware: Query Fossil's structured directory and status commands to report known
            file membership independently from ignore decisions.
        initial_excludes: Additional walker baseline exclusions.
    """

    mode: Literal["fossil"] = field(default="fossil", init=False)
    fossil_executable: str = "fossil"
    environment: Mapping[str, str] | None = None
    timeout: float = 30.0
    membership_aware: bool = False
    initial_excludes: Sequence[str] = ()


@dataclass(frozen=True, slots=True)
class BreezyPolicyConfig:
    """Request Breezy's native default and working-tree ignore rules.

    Attributes:
        brz_executable: Breezy client used to query built-in default rules.
        environment: Optional complete environment passed to Breezy and used to locate global
            ignore configuration. Include PATH when ``brz_executable`` is not absolute.
        global_ignore_file: Optional explicit user ignore file overriding standard discovery.
        timeout: Maximum duration for the native default-rule query.
        initial_excludes: Walker baseline exclusions, defaulting to Breezy's ``.bzr`` metadata.
    """

    mode: Literal["breezy"] = field(default="breezy", init=False)
    brz_executable: str = "brz"
    environment: Mapping[str, str] | None = None
    global_ignore_file: str | os.PathLike[str] | None = None
    timeout: float = 30.0
    initial_excludes: Sequence[str] = (".bzr",)


@dataclass(frozen=True, slots=True)
class DarcsPolicyConfig:
    """Request native, membership-aware Darcs boring-file decisions.

    Attributes:
        darcs_executable: Darcs client used to query add candidates and managed paths.
        environment: Optional complete environment passed to Darcs. It controls home-directory
            preference discovery as well as process settings.
        timeout: Maximum duration in seconds for each native query.
        initial_excludes: Walker baseline exclusions, defaulting to Darcs' ``_darcs`` metadata.
    """

    mode: Literal["darcs"] = field(default="darcs", init=False)
    darcs_executable: str = "darcs"
    environment: Mapping[str, str] | None = None
    timeout: float = 30.0
    initial_excludes: Sequence[str] = ("_darcs",)


@dataclass(frozen=True, slots=True)
class SaplingPolicyConfig:
    """Request portable evaluation of captured Sapling Git-ignore behavior.

    Attributes:
        environment: Optional complete environment used to locate the conventional XDG Git ignore
            file in Sapling `.git` storage mode. When ``read_git_config`` is enabled, it is also
            passed to Git; include PATH and any Git config environment variables it needs.
        global_excludes_file: Optional explicit path for a configured ``core.excludesFile``. This
            overrides both discovered config and the conventional XDG path in `.git` storage mode.
        read_git_config: Ask Git to resolve effective system/global/repository
            ``core.excludesFile`` values, including conditional includes.
            Requires the configured Git executable; when unset, evaluation stays client-independent.
        git_executable: Executable name or path used for optional global config discovery.
        git_config_timeout: Maximum duration in seconds for Git config discovery.
        initial_excludes: Optional hard baseline replacing the storage-mode default (`.sl` or
            `.git`).
    """

    mode: Literal["sapling"] = field(default="sapling", init=False)
    environment: Mapping[str, str] | None = None
    initial_excludes: Sequence[str] | None = None
    global_excludes_file: str | os.PathLike[str] | None = None
    read_git_config: bool = False
    git_executable: str = "git"
    git_config_timeout: float = 30.0


@dataclass(frozen=True, slots=True)
class JujutsuPolicyConfig:
    """Request read-only evaluation of captured Jujutsu Git-ignore behavior.

    Attributes:
        environment: Optional complete environment used to locate the conventional XDG Git ignore
            file. When ``read_git_config`` is enabled, it is also passed to Git; include PATH and
            any Git config environment variables it needs.
        global_excludes_file: Optional explicit path for a configured ``core.excludesFile``. This
            overrides both discovered config and the conventional XDG path.
        read_git_config: Ask Git to resolve effective system/global/repository
            ``core.excludesFile`` values, including conditional includes.
            Requires the configured Git executable; when unset, evaluation stays client-independent.
        git_executable: Executable name or path used for optional global config discovery.
        git_config_timeout: Maximum duration in seconds for Git config discovery.
        initial_excludes: Hard baseline exclusions, defaulting to Jujutsu's `.jj` metadata.
    """

    mode: Literal["jujutsu"] = field(default="jujutsu", init=False)
    environment: Mapping[str, str] | None = None
    initial_excludes: Sequence[str] = (".jj",)
    global_excludes_file: str | os.PathLike[str] | None = None
    read_git_config: bool = False
    git_executable: str = "git"
    git_config_timeout: float = 30.0


#: Discriminated configuration union accepted by :func:`select_policy`.
PolicyConfig: TypeAlias = (
    PortablePolicyConfig
    | GitPolicyConfig
    | PreferGitPolicyConfig
    | MercurialPolicyConfig
    | PerforcePolicyConfig
    | SubversionPolicyConfig
    | FossilPolicyConfig
    | BreezyPolicyConfig
    | DarcsPolicyConfig
    | SaplingPolicyConfig
    | JujutsuPolicyConfig
)


@dataclass(frozen=True, slots=True)
class PortablePolicySelection:
    """Portable backend selection, either requested directly or chosen as fallback.

    Attributes:
        mode: Requested selection strategy.
        backend: Actual resolver selected; always ``"portable"`` for this variant.
        policy: Portable policy used for queries and traversal.
        fallback_reason: ``"git-executable-missing"`` when prefer-Git selected portable because
            Git could not be found; otherwise ``None``.
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


@dataclass(frozen=True, slots=True)
class MercurialPolicySelection:
    """Selection of the portable Mercurial ignore evaluator.

    Attributes:
        mode: Always ``"mercurial"`` for this scheme selection.
        backend: The Python implementation of Mercurial ignore semantics.
        policy: Policy used for queries and traversal.
        fallback_reason: Always ``None``; there is no cross-scheme fallback.
    """

    mode: Literal["mercurial"] = field(default="mercurial", init=False)
    backend: Literal["mercurial-python"] = field(default="mercurial-python", init=False)
    policy: MercurialIgnorePolicy
    fallback_reason: None = None


@dataclass(frozen=True, slots=True)
class PerforcePolicySelection:
    """Selection of the portable P4IGNORE evaluator.

    Attributes:
        mode: Always ``"perforce"`` for this scheme selection.
        backend: The local Python P4IGNORE evaluator.
        policy: Policy used for queries and traversal.
        fallback_reason: Always ``None``; there is no cross-scheme fallback.
    """

    mode: Literal["perforce"] = field(default="perforce", init=False)
    backend: Literal["perforce-python"] = field(default="perforce-python", init=False)
    policy: PerforceIgnorePolicy
    fallback_reason: None = None


@dataclass(frozen=True, slots=True)
class SubversionPolicySelection:
    """Selection of the native-property-discovery Subversion policy.

    Attributes:
        mode: Always ``"subversion"`` for this scheme selection.
        backend: The native Subversion property-discovery implementation.
        policy: Policy used for queries and traversal.
        fallback_reason: Always ``None``; there is no cross-scheme fallback.
    """

    mode: Literal["subversion"] = field(default="subversion", init=False)
    backend: Literal["subversion-native-properties"] = field(
        default="subversion-native-properties", init=False
    )
    policy: SubversionIgnorePolicy
    fallback_reason: None = None


@dataclass(frozen=True, slots=True)
class FossilPolicySelection:
    """Selection of the Fossil effective-setting policy.

    Attributes:
        mode: Always ``"fossil"`` for this scheme selection.
        backend: The Fossil client setting-discovery implementation.
        policy: Policy used for queries and traversal.
        fallback_reason: Always ``None``; there is no cross-scheme fallback.
    """

    mode: Literal["fossil"] = field(default="fossil", init=False)
    backend: Literal["fossil-effective-setting"] = field(
        default="fossil-effective-setting", init=False
    )
    policy: FossilIgnorePolicy
    fallback_reason: None = None


@dataclass(frozen=True, slots=True)
class BreezyPolicySelection:
    """Selection of the Breezy native-default and local-rule policy."""

    mode: Literal["breezy"] = field(default="breezy", init=False)
    backend: Literal["breezy-native-defaults"] = field(default="breezy-native-defaults", init=False)
    policy: BreezyIgnorePolicy
    fallback_reason: None = None


@dataclass(frozen=True, slots=True)
class DarcsPolicySelection:
    """Selection of the native, membership-aware Darcs candidate policy.

    Attributes:
        mode: Always ``"darcs"`` for this scheme selection.
        backend: Native add-candidate and managed-path inventory backend.
        policy: Policy used for queries and traversal.
        fallback_reason: Always ``None``; there is no cross-scheme fallback.
    """

    mode: Literal["darcs"] = field(default="darcs", init=False)
    backend: Literal["darcs-native-candidates"] = field(
        default="darcs-native-candidates", init=False
    )
    policy: DarcsBoringPolicy
    fallback_reason: None = None


@dataclass(frozen=True, slots=True)
class SaplingPolicySelection:
    """Selection of the read-only Sapling Git-ignore compatibility policy."""

    mode: Literal["sapling"] = field(default="sapling", init=False)
    backend: Literal["sapling-gitignore-portable"] = field(
        default="sapling-gitignore-portable", init=False
    )
    policy: SaplingIgnorePolicy
    fallback_reason: None = None


@dataclass(frozen=True, slots=True)
class JujutsuPolicySelection:
    """Selection of the read-only Jujutsu Git-ignore compatibility policy."""

    mode: Literal["jujutsu"] = field(default="jujutsu", init=False)
    backend: Literal["jujutsu-gitignore-portable"] = field(
        default="jujutsu-gitignore-portable", init=False
    )
    policy: JujutsuIgnorePolicy
    fallback_reason: None = None


#: Discriminated selection union; ``backend`` narrows ``policy`` to its concrete type.
PolicySelection: TypeAlias = (
    PortablePolicySelection
    | GitPolicySelection
    | MercurialPolicySelection
    | PerforcePolicySelection
    | SubversionPolicySelection
    | FossilPolicySelection
    | BreezyPolicySelection
    | DarcsPolicySelection
    | SaplingPolicySelection
    | JujutsuPolicySelection
)


def _executable_missing(
    executable: str, environment: Mapping[str, str], error: FileNotFoundError
) -> bool:
    # ENOENT can also mean an existing script's interpreter or binary's loader is
    # missing. Likewise, which() conflates absence with lack of execute permission.
    # Conservatively require every candidate to be absent, including dangling links.
    if is_windows():
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
    return isinstance(
        value,
        (
            PortablePolicyConfig,
            GitPolicyConfig,
            PreferGitPolicyConfig,
            MercurialPolicyConfig,
            PerforcePolicyConfig,
            SubversionPolicyConfig,
            FossilPolicyConfig,
            BreezyPolicyConfig,
            DarcsPolicyConfig,
            SaplingPolicyConfig,
            JujutsuPolicyConfig,
        ),
    )


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
) -> GitPolicySelection | PortablePolicySelection: ...


@overload
def select_policy(
    root: str | os.PathLike[str], config: MercurialPolicyConfig
) -> MercurialPolicySelection: ...


@overload
def select_policy(
    root: str | os.PathLike[str], config: PerforcePolicyConfig
) -> PerforcePolicySelection: ...


@overload
def select_policy(
    root: str | os.PathLike[str], config: SubversionPolicyConfig
) -> SubversionPolicySelection: ...


@overload
def select_policy(
    root: str | os.PathLike[str], config: FossilPolicyConfig
) -> FossilPolicySelection: ...


@overload
def select_policy(
    root: str | os.PathLike[str], config: BreezyPolicyConfig
) -> BreezyPolicySelection: ...


@overload
def select_policy(
    root: str | os.PathLike[str], config: DarcsPolicyConfig
) -> DarcsPolicySelection: ...


@overload
def select_policy(
    root: str | os.PathLike[str], config: SaplingPolicyConfig
) -> SaplingPolicySelection: ...


@overload
def select_policy(
    root: str | os.PathLike[str], config: JujutsuPolicyConfig
) -> JujutsuPolicySelection: ...


@overload
def select_policy(root: str | os.PathLike[str], config: PolicyConfig) -> PolicySelection: ...


def select_policy(
    root: str | os.PathLike[str], config: PolicyConfig | None = None
) -> PolicySelection:
    """Resolve one policy eagerly from a tagged config; never switch during a walk.

    Inspect the returned ``backend`` and ``fallback_reason`` to see whether prefer-Git selected
    the portable fallback. ``PreferGitPolicyConfig`` falls back only when Git's executable is
    confirmed absent.
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

    elif selected.mode == "mercurial":
        return MercurialPolicySelection(
            policy=MercurialIgnorePolicy(
                root,
                ignore_files=selected.ignore_files,
                read_client_config=selected.read_client_config,
                hg_executable=selected.hg_executable,
                environment=selected.environment,
                timeout=selected.timeout,
                initial_excludes=selected.initial_excludes,
                membership_aware=selected.membership_aware,
            )
        )

    elif selected.mode == "perforce":
        return PerforcePolicySelection(
            policy=PerforceIgnorePolicy(
                root,
                environment=selected.environment,
                p4ignore=selected.p4ignore,
                read_client_config=selected.read_client_config,
                discover_client_workspace=selected.discover_client_workspace,
                client_view_aware=selected.client_view_aware,
                p4_executable=selected.p4_executable,
                timeout=selected.timeout,
                initial_excludes=selected.initial_excludes,
            )
        )

    elif selected.mode == "subversion":
        return SubversionPolicySelection(
            policy=SubversionIgnorePolicy(
                root,
                svn_executable=selected.svn_executable,
                config_dir=selected.config_dir,
                environment=selected.environment,
                timeout=selected.timeout,
                membership_aware=selected.membership_aware,
                global_ignores=selected.global_ignores,
                initial_excludes=selected.initial_excludes,
            )
        )

    elif selected.mode == "fossil":
        return FossilPolicySelection(
            policy=FossilIgnorePolicy(
                root,
                fossil_executable=selected.fossil_executable,
                environment=selected.environment,
                timeout=selected.timeout,
                membership_aware=selected.membership_aware,
                initial_excludes=selected.initial_excludes,
            )
        )

    elif selected.mode == "breezy":
        return BreezyPolicySelection(
            policy=BreezyIgnorePolicy(
                root,
                brz_executable=selected.brz_executable,
                environment=selected.environment,
                global_ignore_file=selected.global_ignore_file,
                timeout=selected.timeout,
                initial_excludes=selected.initial_excludes,
            )
        )

    elif selected.mode == "darcs":
        return DarcsPolicySelection(
            policy=DarcsBoringPolicy(
                root,
                darcs_executable=selected.darcs_executable,
                environment=selected.environment,
                timeout=selected.timeout,
                initial_excludes=selected.initial_excludes,
            )
        )

    elif selected.mode == "sapling":
        return SaplingPolicySelection(
            policy=SaplingIgnorePolicy(
                root,
                environment=selected.environment,
                global_excludes_file=selected.global_excludes_file,
                read_git_config=selected.read_git_config,
                git_executable=selected.git_executable,
                git_config_timeout=selected.git_config_timeout,
                initial_excludes=selected.initial_excludes,
            )
        )

    elif selected.mode == "jujutsu":
        return JujutsuPolicySelection(
            policy=JujutsuIgnorePolicy(
                root,
                environment=selected.environment,
                global_excludes_file=selected.global_excludes_file,
                read_git_config=selected.read_git_config,
                git_executable=selected.git_executable,
                git_config_timeout=selected.git_config_timeout,
                initial_excludes=selected.initial_excludes,
            )
        )

    _assert_never(selected)
