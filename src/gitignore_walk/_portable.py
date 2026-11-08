"""Repository Git-ignore parsing and policy evaluation."""

from __future__ import annotations

# Internal implementation modules share private policy hooks, not public APIs.
# pyright: reportPrivateUsage=false
import os
import stat
from abc import ABC, abstractmethod
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal, NamedTuple, cast

from ._environment import EnvVar
from ._ignore_file import DEFAULT_MATCHER
from ._ignore_file import GitIgnoreMatch as _PatternMatch
from ._ignore_file import match_gitignore_file as _match_loaded_ignore
from ._ignore_loader import load_gitignore as _load_gitignore
from ._ignore_protocols import GitIgnoreMatcher
from ._ignore_types import GitIgnoreFile as _LoadedIgnore
from ._util import is_windows
from .errors import GitIgnoreError

_DEFAULT_INITIAL_EXCLUDES: Final = (".git",)


@dataclass(frozen=True, slots=True)
class GitIgnoreDecision:
    """Explain one target's effective Git-ignore decision.

    Attributes:
        path: Resolved target path.
        ignored: Whether the effective rule excludes the target.
        source: Origin of the effective rule, or ``None`` when no rule matched.
        pattern: Text of the effective rule, or ``None`` when no rule matched.
        line: One-based line number of the rule, or ``None`` when unavailable.
    """

    path: Path
    ignored: bool
    source: str | None = None
    pattern: str | None = None
    line: int | None = None


@dataclass(frozen=True, slots=True)
class GitIgnoreTraceMatch:
    """One matching rule in an ignore-policy trace.

    Attributes:
        source: Origin of the ignore file containing the rule.
        pattern: Pattern text as written in the ignore file.
        line: One-based source line number.
        ignored: Whether this rule excludes the target.
        effective: Whether this rule determines the final policy decision.
    """

    source: str
    pattern: str
    line: int
    ignored: bool
    effective: bool


@dataclass(frozen=True, slots=True)
class GitIgnoreTrace:
    """Effective decision plus matching rules ordered from lowest to highest precedence.

    Attributes:
        decision: Final decision for the target.
        matches: Applicable matching rules in precedence order.
        complete: Whether the backend could enumerate every applicable matching rule.
    """

    decision: GitIgnoreDecision
    matches: tuple[GitIgnoreTraceMatch, ...]
    complete: bool = True


class GitIgnoreWalkEntry(NamedTuple):
    """One ``os.walk``-style row with names for each returned value.

    Attributes:
        directory: Directory represented by this row.
        dir_names: Included child directory names, mutable for top-down pruning.
        file_names: File names selected by the walk's policy.
    """

    directory: Path
    dir_names: list[str]
    file_names: list[str]


class _RepositoryMetadata(NamedTuple):
    root: Path
    common_dir: Path


class _WalkStackEntry(NamedTuple):
    directory: str
    names: list[str] | None
    files: list[str] | None


class IgnorePolicy(ABC):
    """Shared interface for portable and Git-backed ignore policies.

    Attributes:
        root: Resolved root that bounds every target handled by the policy.
        matcher: Backend used to parse and evaluate ignore rules.
    """

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        initial_excludes: Sequence[str] = _DEFAULT_INITIAL_EXCLUDES,
        matcher: GitIgnoreMatcher[Any] | None = None,
    ) -> None:
        """Set the policy root, baseline exclusions, and optional matcher backend."""
        self.matcher = DEFAULT_MATCHER if matcher is None else matcher
        self.root = _resolve_root(root)
        self._initial_excludes: _LoadedIgnore[Any] = _LoadedIgnore(
            source="initial Git-ignore exclusions",
            spec=self.matcher.parse(initial_excludes, source="initial Git-ignore exclusions"),
            matcher=self.matcher,
        )

    @abstractmethod
    def explain(self, target: str | os.PathLike[str]) -> GitIgnoreDecision:
        """Explain one target."""

    @abstractmethod
    def iter_explain(
        self, targets: Iterable[str | os.PathLike[str]], *, batch_size: int = 256
    ) -> Iterator[GitIgnoreDecision]:
        """Lazily explain targets in input order."""

    def explain_many(self, targets: Iterable[str | os.PathLike[str]]) -> list[GitIgnoreDecision]:
        """Explain targets in input order."""
        return list(self.iter_explain(targets))

    def trace(self, target: str | os.PathLike[str]) -> GitIgnoreTrace:
        """Return the decision and matching-rule trace for one target.

        Backends that cannot enumerate every matching rule return their winning rule with
        ``complete=False``.
        """
        decision = self.explain(target)
        matches = (
            ()
            if decision.source is None
            else (
                GitIgnoreTraceMatch(
                    source=decision.source,
                    pattern=decision.pattern or "",
                    line=decision.line or 0,
                    ignored=decision.ignored,
                    effective=True,
                ),
            )
        )
        return GitIgnoreTrace(decision=decision, matches=matches, complete=False)

    def is_ignored(self, target: str | os.PathLike[str]) -> bool:
        """Return whether one target is ignored by this policy."""
        return self.explain(target).ignored

    def is_ignored_many(self, targets: Iterable[str | os.PathLike[str]]) -> list[bool]:
        """Return ignore decisions in the same order as ``targets``."""
        return [decision.ignored for decision in self.explain_many(targets)]

    def iter_ignored(
        self, targets: Iterable[str | os.PathLike[str]], *, batch_size: int = 256
    ) -> Iterator[bool]:
        """Yield ignore decisions lazily in input order, querying bounded batches."""
        return (decision.ignored for decision in self.iter_explain(targets, batch_size=batch_size))

    @abstractmethod
    def resolve_target(self, target: str | os.PathLike[str]) -> Path:
        """Resolve a target inside the policy root."""

    def _walk_top(self, target: str | os.PathLike[str]) -> Path:
        return self.resolve_target(target)

    @abstractmethod
    def _decisions(
        self, targets: Sequence[Path], snapshot: _IgnoreSnapshot
    ) -> Sequence[GitIgnoreDecision]:
        """Evaluate walker targets."""


class GitIgnorePolicy(IgnorePolicy):
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

    def explain(self, target: str | os.PathLike[str]) -> GitIgnoreDecision:
        """Return the effective decision and matching policy source for one target."""

        resolved_target = self.resolve_target(target)
        return self.decision(target=resolved_target, snapshot=_IgnoreSnapshot())

    def trace(self, target: str | os.PathLike[str]) -> GitIgnoreTrace:
        """Return matching source rules and identify the effective overlay."""
        resolved = self.resolve_target(target)
        snapshot = _IgnoreSnapshot()
        relative = resolved.relative_to(self.root).as_posix()
        matches: list[_PatternMatch] = []
        initial = _match_loaded_ignore(
            self._initial_excludes, relative, is_directory=resolved.is_dir()
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
            decision = _decision_from_match(path=resolved, match=match)
        else:
            decision = GitIgnoreDecision(path=resolved, ignored=False)
        trace_matches = tuple(
            GitIgnoreTraceMatch(
                source=match.source,
                pattern=match.pattern,
                line=match.line,
                ignored=match.ignored,
                effective=index == effective_index,
            )
            for index, match in enumerate(matches)
        )
        return GitIgnoreTrace(decision, trace_matches)

    def iter_explain(
        self, targets: Iterable[str | os.PathLike[str]], *, batch_size: int = 256
    ) -> Iterator[GitIgnoreDecision]:
        """Lazily evaluate targets against a shared per-iteration ignore snapshot."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        snapshot = _IgnoreSnapshot()
        yield from (
            self.decision(target=self.resolve_target(target), snapshot=snapshot)
            for target in targets
        )

    def decision(self, *, target: Path, snapshot: _IgnoreSnapshot) -> GitIgnoreDecision:
        """Evaluate a resolved target using an existing per-operation ignore snapshot."""
        relative = target.relative_to(self.root).as_posix()
        initial_match = _match_loaded_ignore(
            self._initial_excludes,
            relative,
            is_directory=target.is_dir(),
        )
        if initial_match is not None and initial_match.ignored:
            return _decision_from_match(path=target, match=initial_match)

        policy_match = _gitignore_path_decision(
            root=self._repository_root,
            target=target,
            snapshot=snapshot,
            global_excludes=self._global_excludes,
            repository_excludes=self._repository_excludes,
            matcher=self.matcher,
        )
        if policy_match is not None:
            return _decision_from_match(path=target, match=policy_match)
        if initial_match is not None:
            return _decision_from_match(path=target, match=initial_match)
        return GitIgnoreDecision(path=target, ignored=False)

    def _decisions(
        self, targets: Sequence[Path], snapshot: _IgnoreSnapshot
    ) -> tuple[GitIgnoreDecision, ...]:
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


class GitIgnoreWalker:
    """Traverse a root using the supplied policy or an automatically created portable policy.

    Attributes:
        root: Resolved traversal root.
        policy: Policy used to decide which entries are ignored.
    """

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        policy: IgnorePolicy | None = None,
        initial_excludes: Sequence[str] | None = None,
        matcher: GitIgnoreMatcher[Any] | None = None,
    ) -> None:
        """Bind a root to a policy, or create a portable policy for that root."""
        resolved_root = _resolve_root(root)
        if policy is not None and (matcher is not None or initial_excludes is not None):
            raise ValueError("configure matcher and initial_excludes on the supplied policy")
        if policy is None:
            policy = GitIgnorePolicy(
                resolved_root,
                initial_excludes=(
                    _DEFAULT_INITIAL_EXCLUDES if initial_excludes is None else initial_excludes
                ),
                matcher=matcher,
            )
        self.policy = policy
        if self.policy.root != resolved_root:
            raise ValueError("GitIgnoreWalker policy must use the same repository root")
        self.root = resolved_root

    def iter_files(
        self,
        top: str | os.PathLike[str] | None = None,
        *,
        topdown: bool = True,
        onerror: Callable[[OSError], object] | None = None,
        selection: Literal["included", "ignored", "all"] = "included",
    ) -> Iterator[Path]:
        """Yield files from :meth:`walk` without exposing directory lists."""

        for directory, _, filenames in self.walk(
            top,
            topdown=topdown,
            onerror=onerror,
            selection=selection,
        ):
            yield from (directory / filename for filename in filenames)

    def walk(
        self,
        top: str | os.PathLike[str] | None = None,
        *,
        topdown: bool = True,
        onerror: Callable[[OSError], object] | None = None,
        selection: Literal["included", "ignored", "all"] = "included",
    ) -> Iterator[GitIgnoreWalkEntry]:
        """Walk regular repository entries with an ``os.walk``-style result.

        Select included entries by default, ignored entries with ``selection="ignored"``, or both
        with ``selection="all"``. Symlinks and special files are always omitted. An ignored-only
        walk still traverses unignored directories to find ignored descendants.
        """

        if selection not in ("included", "ignored", "all"):
            raise ValueError(f"unknown walk selection: {selection!r}")
        ignored = None if selection == "all" else selection == "ignored"
        top_path = self.policy._walk_top(self.root if top is None else top)
        snapshot = _IgnoreSnapshot()
        if (
            ignored is False
            and top_path != self.root
            and self.policy._decisions((top_path,), snapshot)[0].ignored
        ):
            return

        def included_directories(parent_directory: str, child_names: list[str]) -> list[str]:
            parent_path = Path(parent_directory)
            regular_children = [
                name
                for name in child_names
                if _is_regular_directory(parent_path / name, onerror=onerror)
            ]
            child_paths = [
                self.policy.resolve_target(parent_path / name) for name in regular_children
            ]
            child_decisions = self.policy._decisions(child_paths, snapshot)
            return [
                name
                for name, decision in zip(regular_children, child_decisions, strict=True)
                if not decision.ignored
            ]

        entries = (
            _walk_pruned_bottom_up(
                top_path, onerror=onerror, included_directories=included_directories
            )
            if not topdown and ignored is False
            else os.walk(top_path, topdown=topdown, onerror=onerror, followlinks=False)
        )
        for directory, dir_names, filenames in entries:
            current = Path(directory)
            safe_dir_names = [
                name for name in dir_names if _is_regular_directory(current / name, onerror=onerror)
            ]
            safe_filenames = [
                name for name in filenames if _is_regular_file(current / name, onerror=onerror)
            ]
            dir_names[:] = safe_dir_names

            if ignored is None:
                yield GitIgnoreWalkEntry(current, dir_names, safe_filenames)
                continue

            paths = tuple(
                self.policy.resolve_target(current / name)
                for name in (*safe_dir_names, *safe_filenames)
            )
            decisions = self.policy._decisions(paths, snapshot)
            directory_decisions = decisions[: len(safe_dir_names)]
            file_decisions = decisions[len(safe_dir_names) :]
            matching_dirs = [
                name
                for name, decision in zip(safe_dir_names, directory_decisions, strict=True)
                if decision.ignored is ignored
            ]
            matching_files = [
                name
                for name, decision in zip(safe_filenames, file_decisions, strict=True)
                if decision.ignored is ignored
            ]
            if not ignored:
                # An ignored parent cannot contain an unignored descendant under Git's traversal
                # rules, so unignored walks can prune those directories safely.
                dir_names[:] = matching_dirs
                yield GitIgnoreWalkEntry(current, dir_names, matching_files)
                continue
            yield GitIgnoreWalkEntry(current, matching_dirs, matching_files)


def _walk_pruned_bottom_up(
    top: Path,
    *,
    onerror: Callable[[OSError], object] | None,
    included_directories: Callable[[str, list[str]], list[str]],
) -> Iterator[tuple[str, list[str], list[str]]]:
    """Yield bottom-up rows while pruning excluded directories before descent."""
    stack = [_WalkStackEntry(os.fspath(top), None, None)]
    while stack:
        directory, names, files = stack.pop()
        if names is not None and files is not None:
            yield directory, names, files
            continue
        walk = cast(
            Generator[tuple[str, list[str], list[str]], None, None],
            os.walk(directory, topdown=True, onerror=onerror, followlinks=False),
        )
        try:
            _, names, files = next(walk)
        except StopIteration:
            continue
        finally:
            walk.close()
        names[:] = included_directories(directory, names)
        stack.append(_WalkStackEntry(directory, names, files))
        for name in reversed(names):
            child = os.path.join(directory, name)
            if not os.path.islink(child):
                stack.append(_WalkStackEntry(child, None, None))


def _resolve_root(root: str | os.PathLike[str]) -> Path:
    try:
        root_path = Path(root).expanduser().resolve()
        if not root_path.is_dir():
            raise ValueError(f"repository root must be a directory: {root_path}")
    except (OSError, RuntimeError) as error:
        raise GitIgnoreError(f"unable to resolve Git-ignore path: {error}") from error
    return root_path


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
        return _RepositoryMetadata(candidate_root, common_dir)
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


def _is_regular_directory(path: Path, *, onerror: Callable[[OSError], object] | None) -> bool:
    return _is_regular_entry(path, kind="directory", onerror=onerror)


def _is_regular_file(path: Path, *, onerror: Callable[[OSError], object] | None) -> bool:
    return _is_regular_entry(path, kind="file", onerror=onerror)


def _is_regular_entry(
    path: Path,
    *,
    kind: Literal["directory", "file"],
    onerror: Callable[[OSError], object] | None,
) -> bool:
    try:
        if path.is_symlink():
            return False
        mode = path.stat().st_mode
        if kind == "directory":
            return stat.S_ISDIR(mode)
        return stat.S_ISREG(mode) and path.is_file()
    except OSError as error:
        if onerror is not None:
            onerror(error)
            return False
        raise GitIgnoreError(f"unable to inspect Git-ignore walk entry: {path}: {error}") from error


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
) -> _PatternMatch | None:
    """Return the effective ignore match for one target, if ignored."""
    matches = _gitignore_path_matches(
        root=root,
        target=target,
        snapshot=snapshot,
        global_excludes=global_excludes,
        repository_excludes=repository_excludes,
        matcher=matcher,
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
            matched = _match_loaded_ignore(loaded, relative_to_root, is_directory=is_directory)
            if matched is not None:
                matches.append(matched)
    for ignore_root in roots:
        loaded = (
            _load_gitignore(ignore_root / ".gitignore", matcher=matcher)
            if snapshot is None
            else snapshot.load(ignore_root / ".gitignore", matcher=matcher)
        )
        if loaded is not None:
            matched = _match_loaded_ignore(
                loaded, path.relative_to(ignore_root).as_posix(), is_directory=is_directory
            )
            if matched is not None:
                matches.append(matched)
    return matches


def _decision_from_match(*, path: Path, match: _PatternMatch) -> GitIgnoreDecision:
    return GitIgnoreDecision(
        path=path,
        ignored=match.ignored,
        source=match.source,
        pattern=match.pattern,
        line=match.line,
    )
