"""Repository Git-ignore parsing and policy evaluation."""

from __future__ import annotations

# Internal implementation modules share private policy hooks, not public APIs.
# pyright: reportPrivateUsage=false
import os
from abc import abstractmethod
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Generic, NamedTuple, TypeVar

from ..._environment import EnvVar
from ..._policy import (
    IgnoreDecision,
    IgnorePolicy,
    IgnoreTrace,
    IgnoreTraceMatch,
    _IgnoreWalkSession,
)
from ..._util import is_windows
from ...errors import GitIgnoreError
from ._ignore_file import DEFAULT_MATCHER
from ._ignore_file import GitIgnoreMatch as _PatternMatch
from ._ignore_file import match_gitignore_file as _match_loaded_ignore
from ._ignore_loader import load_gitignore as _load_gitignore
from ._ignore_protocols import GitIgnoreMatcher
from ._ignore_types import GitIgnoreFile as _LoadedIgnore

_DEFAULT_INITIAL_EXCLUDES: Final = (".git",)
_Membership = TypeVar("_Membership")


class _RepositoryMetadata(NamedTuple):
    root: Path
    git_dir: Path
    common_dir: Path


class _GitIgnorePolicyBase(IgnorePolicy):
    """Shared Git-dialect implementation behind portable and native evaluators."""

    @property
    def scheme(self) -> str:
        """Identify Git's ignore dialect independently of its execution backend."""
        return "git"

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        initial_excludes: Sequence[str] = _DEFAULT_INITIAL_EXCLUDES,
        matcher: GitIgnoreMatcher[Any] | None = None,
    ) -> None:
        self.matcher = DEFAULT_MATCHER if matcher is None else matcher
        self.root = _resolve_root(root)
        self._initial_excludes: _LoadedIgnore[Any] = _LoadedIgnore(
            source="initial Git-ignore exclusions",
            spec=self.matcher.parse(initial_excludes, source="initial Git-ignore exclusions"),
            matcher=self.matcher,
        )

    @abstractmethod
    def _decisions(
        self, targets: Sequence[Path], snapshot: _IgnoreSnapshot
    ) -> Sequence[IgnoreDecision]:
        """Evaluate targets for one walk session."""

    def _walk_top(self, target: str | os.PathLike[str]) -> Path:
        return self.resolve_target(target)

    def can_prune_ignored_directory(self, target: Path, decision: IgnoreDecision) -> bool:
        """Apply Git's rule that an ignored directory cannot contain an unignored descendant."""
        return decision.ignored

    def _open_walk(self) -> _IgnoreWalkSession:
        return _GitIgnoreWalkSession(self)


class GitIgnorePolicy(_GitIgnorePolicyBase):
    """Evaluate repository ignore policy without invoking Git.

    The policy reads the conventional user-global ignore file when present, a discoverable
    repository ``info/exclude`` file, and applicable repository ``.gitignore`` files. It discovers
    a Git worktree by walking upward from ``root``; it does not need to invoke Git. Git config
    overrides and conditional includes are intentionally outside this portable scope.
    An explicit ``environment`` supplies complete HOME/USERPROFILE and XDG_CONFIG_HOME
    locations for global ignores; omitted values never inherit ambient environment settings.

    ``initial_excludes`` are applied as a hard baseline before those sources and default to
    ``(".git",)``. Supplying a sequence replaces that default; use an empty sequence to remove it.
    A matching baseline exclusion remains ignored regardless of later ignore rules.
    """

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        initial_excludes: Sequence[str] = _DEFAULT_INITIAL_EXCLUDES,
        matcher: GitIgnoreMatcher[Any] | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        """Create a portable policy rooted at ``root`` with optional baseline rules and matcher."""
        super().__init__(root, initial_excludes=initial_excludes, matcher=matcher)
        metadata = _find_repository_metadata(self.root)
        self._repository_root = self.root if metadata is None else metadata.root
        self._repository_excludes = (
            None if metadata is None else metadata.common_dir / "info" / "exclude"
        )
        self._global_excludes = _default_global_excludes_path(environment)
        self._allow_symlinked_gitignore = False

    def explain(self, target: str | os.PathLike[str]) -> IgnoreDecision:
        """Return the effective decision and matching policy source for one target."""

        resolved_target = self.resolve_target(target)
        return self.decision(target=resolved_target, snapshot=_IgnoreSnapshot())

    def trace(self, target: str | os.PathLike[str]) -> IgnoreTrace:
        """Return matching source rules and identify the effective overlay."""
        resolved = self.resolve_target(target)
        snapshot = _IgnoreSnapshot()
        relative = resolved.relative_to(self.root).as_posix()
        matches: list[_PatternMatch] = []
        initial = _match_loaded_ignore(
            self._initial_excludes, relative, is_directory=resolved.is_dir(), scope="."
        )
        if initial is not None:
            matches.append(initial)
        matches.extend(
            _gitignore_path_matches(
                root=self._repository_root,
                target=resolved,
                snapshot=snapshot,
                global_excludes=self._global_excludes,
                repository_excludes=self._repository_excludes,
                matcher=self.matcher,
                allow_symlinked_gitignore=self._allow_symlinked_gitignore,
            )
        )
        effective_index = next(
            (
                i
                for i, match in enumerate(matches)
                if match.source == "initial Git-ignore exclusions" and match.ignored
            ),
            len(matches) - 1,
        )
        if matches:
            match = matches[effective_index]
            decision = _decision_from_match(path=resolved, match=match, scheme=self.scheme)
        else:
            decision = IgnoreDecision(
                path=resolved,
                ignored=False,
                scheme=self.scheme,
                reason="no-matching-rule",
                discovery_complete=True,
            )
        trace_matches = tuple(
            IgnoreTraceMatch(
                source=match.source,
                pattern=match.pattern,
                line=match.line,
                ignored=match.ignored,
                effective=index == effective_index,
                scheme=self.scheme,
                scope=match.scope,
                reason=(
                    "baseline-exclusion"
                    if match.source == "initial Git-ignore exclusions"
                    else "matched-rule"
                ),
            )
            for index, match in enumerate(matches)
        )
        return IgnoreTrace(decision, trace_matches)

    def iter_explain(
        self, targets: Iterable[str | os.PathLike[str]], *, batch_size: int = 256
    ) -> Iterator[IgnoreDecision]:
        """Lazily evaluate targets against a shared per-iteration ignore snapshot."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        snapshot = _IgnoreSnapshot()
        yield from (
            self.decision(target=self.resolve_target(target), snapshot=snapshot)
            for target in targets
        )

    def decision(self, *, target: Path, snapshot: _IgnoreSnapshot) -> IgnoreDecision:
        """Evaluate a resolved target using an existing per-operation ignore snapshot."""
        relative = target.relative_to(self.root).as_posix()
        initial_match = _match_loaded_ignore(
            self._initial_excludes,
            relative,
            is_directory=target.is_dir(),
            scope=".",
        )
        if initial_match is not None and initial_match.ignored:
            return _decision_from_match(path=target, match=initial_match, scheme=self.scheme)

        policy_match = _gitignore_path_decision(
            root=self._repository_root,
            target=target,
            snapshot=snapshot,
            global_excludes=self._global_excludes,
            repository_excludes=self._repository_excludes,
            matcher=self.matcher,
            allow_symlinked_gitignore=self._allow_symlinked_gitignore,
        )
        if policy_match is not None:
            return _decision_from_match(path=target, match=policy_match, scheme=self.scheme)
        if initial_match is not None:
            return _decision_from_match(path=target, match=initial_match, scheme=self.scheme)
        return IgnoreDecision(
            path=target,
            ignored=False,
            scheme=self.scheme,
            reason="no-matching-rule",
            discovery_complete=True,
        )

    def _decisions(
        self, targets: Sequence[Path], snapshot: _IgnoreSnapshot
    ) -> tuple[IgnoreDecision, ...]:
        return tuple(self.decision(target=target, snapshot=snapshot) for target in targets)

    def _walk_top(self, target: str | os.PathLike[str]) -> Path:
        return self.resolve_target(target)

    def resolve_target(self, target: str | os.PathLike[str]) -> Path:
        """Resolve a target through symlinks and reject paths outside this policy root."""
        target_path = Path(target).expanduser()
        if not target_path.is_absolute():
            target_path = self.root / target_path
        try:
            target_path = target_path.resolve()
        except (OSError, RuntimeError) as error:
            raise GitIgnoreError(f"unable to resolve Git-ignore target: {error}") from error
        if not target_path.is_relative_to(self.root):
            raise ValueError(f"target must be inside repository root: {target_path}")
        return target_path


def _resolve_root(root: str | os.PathLike[str]) -> Path:
    try:
        root_path = Path(root).expanduser().resolve()
        if not root_path.is_dir():
            raise ValueError(f"repository root must be a directory: {root_path}")
    except (OSError, RuntimeError) as error:
        raise GitIgnoreError(f"unable to resolve Git-ignore path: {error}") from error
    return root_path


# Used by Sapling and Jujutsu to retain native path identity during membership annotation.
def _lexical_target_path(  # pyright: ignore[reportUnusedFunction]
    root: Path, target: str | os.PathLike[str]
) -> Path:
    """Return a normalized absolute path without following symbolic links."""
    target_path = Path(target).expanduser()
    if not target_path.is_absolute():
        target_path = root / target_path
    return Path(os.path.abspath(target_path))


def _find_repository_metadata(start: Path) -> _RepositoryMetadata | None:
    """Find a worktree marker at ``start`` or an ancestor without invoking Git."""

    for candidate_root in (start, *start.parents):
        marker = candidate_root / ".git"
        if marker.is_dir():
            try:
                git_dir = marker.resolve()
            except (OSError, RuntimeError):
                continue
        elif marker.is_file():
            try:
                marker_line = marker.read_text(encoding="utf-8").splitlines()[0]
            except (OSError, UnicodeError, IndexError):
                continue
            prefix = "gitdir: "
            if not marker_line.startswith(prefix):
                continue
            git_dir = Path(marker_line[len(prefix) :])
            if not git_dir.is_absolute():
                git_dir = candidate_root / git_dir
            try:
                git_dir = git_dir.resolve()
            except (OSError, RuntimeError):
                continue
            if not git_dir.is_dir():
                continue
        else:
            continue

        common_dir_file = git_dir / "commondir"
        if common_dir_file.is_file():
            try:
                common_dir_value = common_dir_file.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError):
                common_dir_value = ""
            if common_dir_value:
                common_dir = Path(common_dir_value)
                if not common_dir.is_absolute():
                    common_dir = git_dir / common_dir
                try:
                    common_dir = common_dir.resolve()
                except (OSError, RuntimeError):
                    common_dir = git_dir
            else:
                common_dir = git_dir
        else:
            common_dir = git_dir
        return _RepositoryMetadata(candidate_root, git_dir, common_dir)
    return None


def _default_global_excludes_path(environment: Mapping[str, str] | None = None) -> Path | None:
    """Return Git's conventional XDG/home global-ignore path, without reading Git config."""

    if environment is not None:
        if xdg := environment.get(EnvVar.XDG_CONFIG_HOME):
            return Path(xdg) / "git" / "ignore"
        home = environment.get(EnvVar.HOME)
        if is_windows():
            home = home or environment.get(EnvVar.USERPROFILE)
        return Path(home) / ".config" / "git" / "ignore" if home else None
    xdg_config_home = os.environ.get(EnvVar.XDG_CONFIG_HOME)
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / "git" / "ignore"
    try:
        return Path.home() / ".config" / "git" / "ignore"
    except (OSError, RuntimeError):
        return None


def _new_ignore_specs() -> dict[tuple[Path, bool], _LoadedIgnore[Any] | None]:
    return {}


@dataclass(slots=True)
class _IgnoreSnapshot:
    """One consistent, per-operation view of repository ignore files."""

    specs: dict[tuple[Path, bool], _LoadedIgnore[Any] | None] = field(
        default_factory=_new_ignore_specs
    )

    def load(
        self,
        path: Path,
        *,
        matcher: GitIgnoreMatcher[Any] = DEFAULT_MATCHER,
        allow_symlink: bool = False,
    ) -> _LoadedIgnore[Any] | None:
        key = path, allow_symlink
        if key not in self.specs:
            self.specs[key] = _load_gitignore(
                path,
                matcher=matcher,
                allow_symlink=allow_symlink,
            )
        return self.specs[key]


class _GitIgnoreWalkSession:
    """Bind one walk to a Git-policy snapshot and pruning semantics."""

    def __init__(self, policy: _GitIgnorePolicyBase) -> None:
        self._policy = policy
        self._snapshot = _IgnoreSnapshot()

    def resolve_target(self, target: str | os.PathLike[str]) -> Path:
        return self._policy.resolve_target(target)

    def walk_top(self, target: str | os.PathLike[str]) -> Path:
        return self._policy._walk_top(target)

    def explain_many(self, targets: Iterable[str | os.PathLike[str]]) -> list[IgnoreDecision]:
        resolved = tuple(self.resolve_target(target) for target in targets)
        return list(self._policy._decisions(resolved, self._snapshot))

    def should_descend_directory(self, target: Path) -> bool:
        return self._policy.should_descend_directory(target)

    def should_select_file(self, target: Path) -> bool:
        return self._policy.should_select_file(target)

    def can_prune_ignored_directory(self, target: Path, decision: IgnoreDecision) -> bool:
        return self._policy.can_prune_ignored_directory(target, decision)


# Imported by the Sapling and Jujutsu adapters as their private walk-session implementation.
class _GitIgnoreMembershipWalkSession(  # pyright: ignore[reportUnusedClass]
    _GitIgnoreWalkSession, Generic[_Membership]
):
    """Add one stable scheme-specific membership snapshot to a Git-dialect walk."""

    def __init__(
        self,
        policy: _GitIgnorePolicyBase,
        membership: _Membership | None,
        annotate: Callable[
            [IgnoreDecision, _Membership | None, str | os.PathLike[str]], IgnoreDecision
        ],
    ) -> None:
        super().__init__(policy)
        self._membership = membership
        self._annotate = annotate

    def explain_many(self, targets: Iterable[str | os.PathLike[str]]) -> list[IgnoreDecision]:
        requested = tuple(targets)
        decisions = super().explain_many(requested)
        return [
            self._annotate(decision, self._membership, target)
            for decision, target in zip(decisions, requested, strict=True)
        ]


def _ancestor_directories(*, root: Path, target: Path) -> tuple[Path, ...]:
    """Return target-parent directories from the repository root outward."""

    directories: list[Path] = []
    current = target.parent
    while current.is_relative_to(root):
        directories.append(current)
        if current == root:
            break
        current = current.parent
    directories.reverse()
    return tuple(directories)


def is_gitignored(
    root: str | os.PathLike[str],
    target: str | os.PathLike[str],
) -> bool:
    """Return whether ``target`` is ignored by the portable policy rooted at ``root``.

    ``root`` and ``target`` may be strings or path-like objects. Relative targets are interpreted
    relative to ``root``. When an enclosing Git worktree is found, its applicable ancestor
    ``.gitignore`` files and ``info/exclude`` are considered along with the conventional user-global
    ignore file. The target must be inside ``root``; passing an outside path
    raises :class:`ValueError`.
    Ignore-file read and parse failures raise :class:`GitIgnoreError`.
    """

    return GitIgnorePolicy(root).is_ignored(target)


def _gitignore_path_decision(
    *,
    root: Path,
    target: Path,
    snapshot: _IgnoreSnapshot | None = None,
    global_excludes: Path | None = None,
    repository_excludes: Path | None = None,
    matcher: GitIgnoreMatcher[Any] = DEFAULT_MATCHER,
    allow_symlinked_gitignore: bool = False,
) -> _PatternMatch | None:
    """Return the effective ignore match for one target, if ignored."""
    matches = _gitignore_path_matches(
        root=root,
        target=target,
        snapshot=snapshot,
        global_excludes=global_excludes,
        repository_excludes=repository_excludes,
        matcher=matcher,
        allow_symlinked_gitignore=allow_symlinked_gitignore,
    )
    if not matches:
        return None
    final = matches[-1]
    return final if final.ignored else None


def _gitignore_path_matches(
    *,
    root: Path,
    target: Path,
    snapshot: _IgnoreSnapshot | None,
    global_excludes: Path | None,
    repository_excludes: Path | None,
    matcher: GitIgnoreMatcher[Any],
    allow_symlinked_gitignore: bool,
) -> list[_PatternMatch]:
    """Collect each applicable source's final matching rule in precedence order."""
    directories = _ancestor_directories(root=root, target=target)
    matches: list[_PatternMatch] = []
    for index, directory in enumerate(directories):
        if directory == root:
            continue
        matches.extend(
            _gitignore_matches_for_path(
                roots=directories[:index],
                path=directory,
                is_directory=True,
                snapshot=snapshot,
                root=root,
                global_excludes=global_excludes,
                repository_excludes=repository_excludes,
                matcher=matcher,
                allow_symlinked_gitignore=allow_symlinked_gitignore,
            )
        )
        if matches and matches[-1].ignored:
            return matches
    matches.extend(
        _gitignore_matches_for_path(
            roots=directories,
            path=target,
            is_directory=target.is_dir(),
            snapshot=snapshot,
            root=root,
            global_excludes=global_excludes,
            repository_excludes=repository_excludes,
            matcher=matcher,
            allow_symlinked_gitignore=allow_symlinked_gitignore,
        )
    )
    return matches


def _gitignore_matches_for_path(
    *,
    roots: Sequence[Path],
    path: Path,
    is_directory: bool,
    snapshot: _IgnoreSnapshot | None,
    root: Path,
    global_excludes: Path | None,
    repository_excludes: Path | None,
    matcher: GitIgnoreMatcher[Any],
    allow_symlinked_gitignore: bool,
) -> list[_PatternMatch]:
    matches: list[_PatternMatch] = []
    relative_to_root = path.relative_to(root).as_posix()
    for exclude_path in (global_excludes, repository_excludes):
        if exclude_path is None:
            continue
        loaded = (
            _load_gitignore(exclude_path, matcher=matcher, allow_symlink=True)
            if snapshot is None
            else snapshot.load(exclude_path, matcher=matcher, allow_symlink=True)
        )
        if loaded is not None:
            matched = _match_loaded_ignore(
                loaded, relative_to_root, is_directory=is_directory, scope="."
            )
            if matched is not None:
                matches.append(matched)
    for ignore_root in roots:
        loaded = (
            _load_gitignore(
                ignore_root / ".gitignore",
                matcher=matcher,
                allow_symlink=allow_symlinked_gitignore,
            )
            if snapshot is None
            else snapshot.load(
                ignore_root / ".gitignore",
                matcher=matcher,
                allow_symlink=allow_symlinked_gitignore,
            )
        )
        if loaded is not None:
            matched = _match_loaded_ignore(
                loaded,
                path.relative_to(ignore_root).as_posix(),
                is_directory=is_directory,
                scope=ignore_root.relative_to(root).as_posix() or ".",
            )
            if matched is not None:
                matches.append(matched)
    return matches


def _decision_from_match(
    *, path: Path, match: _PatternMatch, scheme: str = "git"
) -> IgnoreDecision:
    return IgnoreDecision(
        path=path,
        ignored=match.ignored,
        scheme=scheme,
        source=match.source,
        pattern=match.pattern,
        line=match.line,
        scope=match.scope,
        reason=(
            "baseline-exclusion"
            if match.source == "initial Git-ignore exclusions"
            else "matched-rule"
        ),
        discovery_complete=True,
    )
