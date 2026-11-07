"""Repository Git-ignore parsing and policy evaluation."""

from __future__ import annotations

# Internal implementation modules share private policy hooks, not public APIs.
# pyright: reportPrivateUsage=false
import os
import stat
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple, Protocol, cast

from pathspec import GitIgnoreSpec
from pathspec.patterns.gitignore import GitIgnorePatternError


class GitIgnoreError(RuntimeError):
    """Raised when a repository ignore file cannot be interpreted safely."""


@dataclass(frozen=True, slots=True)
class GitIgnoreDecision:
    """Explain one target's effective Git-ignore decision."""

    path: Path
    ignored: bool
    source: str | None = None
    pattern: str | None = None
    line: int | None = None


class GitIgnoreWalkEntry(NamedTuple):
    """One ``os.walk``-style row with names for each returned value."""

    directory: Path
    dir_names: list[str]
    file_names: list[str]


@dataclass(frozen=True, slots=True)
class _LoadedIgnore:
    spec: GitIgnoreSpec
    source: str
    line_numbers: tuple[int | None, ...]


class _RepositoryMetadata(NamedTuple):
    root: Path
    common_dir: Path


class GitIgnorePolicy:
    """Evaluate repository ignore policy without invoking Git.

    The policy reads the conventional user-global ignore file when present, a discoverable
    repository ``info/exclude`` file, and applicable repository ``.gitignore`` files. It discovers
    a Git worktree by walking upward from ``root``; it does not need to invoke Git. Git config
    overrides and conditional includes are intentionally outside this portable scope.

    ``initial_excludes`` are applied as a hard baseline before those sources. A matching baseline
    exclusion remains ignored. They are useful for a caller's own transient or generated-file
    policy and are intentionally kept separate from ignore files.
    """

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        initial_excludes: Sequence[str] = (),
    ) -> None:
        self.root = _resolve_root(root)
        metadata = _find_repository_metadata(self.root)
        self._repository_root = self.root if metadata is None else metadata.root
        self._repository_excludes = (
            None if metadata is None else metadata.common_dir / "info" / "exclude"
        )
        self._global_excludes = _default_global_excludes_path()
        self._initial_excludes = _parse_loaded_ignore(
            initial_excludes,
            source="initial Git-ignore exclusions",
        )

    def is_ignored(self, target: str | os.PathLike[str]) -> bool:
        """Return whether one target is ignored by the configured policy."""

        return self.explain(target).ignored

    def explain(self, target: str | os.PathLike[str]) -> GitIgnoreDecision:
        """Return the effective decision and matching policy source for one target."""

        resolved_target = self.resolve_target(target)
        return self.decision(target=resolved_target, snapshot=_IgnoreSnapshot())

    def is_ignored_many(
        self,
        targets: Iterable[str | os.PathLike[str]],
    ) -> tuple[bool, ...]:
        """Return ignore decisions for multiple targets using one policy snapshot.

        Each invocation reads the current ignore files. All targets in one invocation share that
        snapshot, so a batch is internally consistent and does not repeatedly parse the same
        repository ``.gitignore`` files.
        """

        resolved_targets = tuple(self.resolve_target(target) for target in targets)
        snapshot = _IgnoreSnapshot()
        return tuple(
            self.decision(target=target, snapshot=snapshot).ignored for target in resolved_targets
        )

    def decision(self, *, target: Path, snapshot: _IgnoreSnapshot) -> GitIgnoreDecision:
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
    """Traverse a repository using a :class:`GitIgnorePolicy`."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        policy: GitIgnorePolicy | None = None,
        initial_excludes: Sequence[str] = (),
    ) -> None:
        resolved_root = _resolve_root(root)
        self.policy = policy or GitIgnorePolicy(resolved_root, initial_excludes=initial_excludes)
        if self.policy.root != resolved_root:
            raise ValueError("GitIgnoreWalker policy must use the same repository root")
        self.root = resolved_root

    def iter_files(
        self,
        top: str | os.PathLike[str] | None = None,
        *,
        topdown: bool = True,
        onerror: Callable[[OSError], object] | None = None,
        follow_links: bool = False,
        ignored: bool | None = None,
    ) -> Iterator[Path]:
        """Yield files from :meth:`walk` without exposing directory lists."""

        for directory, _, filenames in self.walk(
            top,
            topdown=topdown,
            onerror=onerror,
            follow_links=follow_links,
            ignored=ignored,
        ):
            yield from (directory / filename for filename in filenames)

    def walk(
        self,
        top: str | os.PathLike[str] | None = None,
        *,
        topdown: bool = True,
        onerror: Callable[[OSError], object] | None = None,
        follow_links: bool = False,
        ignored: bool | None = None,
    ) -> Iterator[GitIgnoreWalkEntry]:
        """Walk regular repository entries with an ``os.walk``-style result.

        ``ignored=None`` yields all regular files and directories. Set it to ``True`` or ``False``
        to yield only ignored or only unignored entries. Symlinks and special files are always
        omitted. ``follow_links=True`` is rejected to preserve the repository input-safety boundary.
        An ignored-only walk still traverses unignored directories to find ignored descendants.
        """

        if follow_links:
            raise ValueError("GitIgnoreWalker.walk does not follow symlinks")
        top_path = self.policy._walk_top(self.root if top is None else top)
        snapshot = _IgnoreSnapshot()
        for directory, dir_names, filenames in os.walk(
            top_path,
            topdown=topdown,
            onerror=onerror,
            followlinks=False,
        ):
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


def _default_global_excludes_path() -> Path | None:
    """Return Git's conventional XDG/home global-ignore path, without reading Git config."""

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / "git" / "ignore"
    try:
        return Path.home() / ".config" / "git" / "ignore"
    except (OSError, RuntimeError):
        return None


def _is_regular_directory(path: Path, *, onerror: Callable[[OSError], object] | None) -> bool:
    try:
        if path.is_symlink():
            return False
        return stat.S_ISDIR(path.stat().st_mode)
    except OSError as error:
        if onerror is not None:
            onerror(error)
            return False
        raise GitIgnoreError(f"unable to inspect Git-ignore walk entry: {path}: {error}") from error


def _is_regular_file(path: Path, *, onerror: Callable[[OSError], object] | None) -> bool:
    try:
        if path.is_symlink():
            return False
        return stat.S_ISREG(path.stat().st_mode) and path.is_file()
    except OSError as error:
        if onerror is not None:
            onerror(error)
            return False
        raise GitIgnoreError(f"unable to inspect Git-ignore walk entry: {path}: {error}") from error


def _new_ignore_specs() -> dict[tuple[Path, bool], object]:
    return {}


@dataclass(slots=True)
class _IgnoreSnapshot:
    """One consistent, per-operation view of repository ignore files."""

    specs: dict[tuple[Path, bool], object] = field(default_factory=_new_ignore_specs)

    def load(self, path: Path, *, allow_symlink: bool = False) -> _LoadedIgnore | None:
        key = path, allow_symlink
        if key not in self.specs:
            self.specs[key] = _load_gitignore(path, allow_symlink=allow_symlink)
        return cast(_LoadedIgnore | None, self.specs[key])


class _GitIgnorePattern(Protocol):
    include: bool | None
    pattern: str

    def match_file(self, file: str) -> bool:
        """Return whether this pattern matches a repository-relative path."""

        ...


@dataclass(frozen=True, slots=True)
class _PatternMatch:
    ignored: bool
    source: str
    pattern: str
    line: int | None


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
) -> _PatternMatch | None:
    """Return the effective ignore match for one target, if ignored."""

    directories = _ancestor_directories(root=root, target=target)
    ignored = False
    ignored_match: _PatternMatch | None = None
    for index, directory in enumerate(directories):
        if directory == root:
            continue
        if ignored:
            # Git cannot traverse an ignored parent to discover a later negation.
            continue
        decision = _gitignore_decision(
            roots=directories[:index],
            path=directory,
            is_directory=True,
            snapshot=snapshot,
            root=root,
            global_excludes=global_excludes,
            repository_excludes=repository_excludes,
        )
        if decision is not None:
            ignored = decision.ignored
            ignored_match = decision if ignored else None

    if ignored:
        return ignored_match
    decision = _gitignore_decision(
        roots=directories,
        path=target,
        is_directory=target.is_dir(),
        snapshot=snapshot,
        root=root,
        global_excludes=global_excludes,
        repository_excludes=repository_excludes,
    )
    return decision if decision is not None and decision.ignored else None


def _gitignore_decision(
    *,
    roots: Sequence[Path],
    path: Path,
    is_directory: bool,
    snapshot: _IgnoreSnapshot | None = None,
    root: Path,
    global_excludes: Path | None,
    repository_excludes: Path | None,
) -> _PatternMatch | None:
    """Return the highest-precedence matching decision for one path."""

    decision: _PatternMatch | None = None
    relative_to_root = path.relative_to(root).as_posix()
    for exclude_path in (global_excludes, repository_excludes):
        if exclude_path is None:
            continue
        loaded = (
            _load_gitignore(exclude_path, allow_symlink=True)
            if snapshot is None
            else snapshot.load(exclude_path, allow_symlink=True)
        )
        if loaded is not None:
            matched = _match_loaded_ignore(loaded, relative_to_root, is_directory=is_directory)
            if matched is not None:
                decision = matched
    for ignore_root in roots:
        ignore_path = ignore_root / ".gitignore"
        loaded = _load_gitignore(ignore_path) if snapshot is None else snapshot.load(ignore_path)
        if loaded is None:
            continue
        relative = path.relative_to(ignore_root).as_posix()
        matched = _match_loaded_ignore(loaded, relative, is_directory=is_directory)
        if matched is not None:
            decision = matched
    return decision


def _load_gitignore(path: Path, *, allow_symlink: bool = False) -> _LoadedIgnore | None:
    """Load one ignore file, if present, following symlinks only when requested."""

    try:
        if not path.is_file() or (path.is_symlink() and not allow_symlink):
            return None
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise GitIgnoreError(f"unable to read Git-ignore source: {path}: {error}") from error
    if path.name == ".gitignore":
        source = f"repository .gitignore {path}"
    elif path.name == "exclude" and path.parent.name == "info":
        source = f"repository info/exclude {path}"
    else:
        source = f"user-global excludes {path}"
    return _parse_loaded_ignore(lines, source=source)


def _parse_loaded_ignore(lines: Sequence[str], *, source: str) -> _LoadedIgnore:
    spec = parse_gitignore(lines, source=source)
    return _LoadedIgnore(
        spec=spec,
        source=source,
        line_numbers=_pattern_line_numbers(lines=lines, spec=spec),
    )


def parse_gitignore(lines: Sequence[str], *, source: str) -> GitIgnoreSpec:
    """Parse Git-ignore patterns and convert invalid syntax to a CLI-safe error."""

    try:
        return GitIgnoreSpec.from_lines(lines)
    except Exception as error:
        if not isinstance(error, GitIgnorePatternError):
            detail = f"{type(error).__name__}: {error}"
        else:
            detail = str(error)
        raise GitIgnoreError(f"invalid Git-ignore pattern in {source}: {detail}") from error


def matches_gitignore(
    spec: GitIgnoreSpec,
    relative: str,
    *,
    is_directory: bool,
) -> bool:
    """Return the ordered Git-ignore decision for one repository-relative path."""

    matched = _last_gitignore_pattern(spec, relative, is_directory=is_directory)
    return matched is not None and matched[0].include is True


def _last_gitignore_pattern(
    spec: GitIgnoreSpec,
    relative: str,
    *,
    is_directory: bool,
) -> tuple[_GitIgnorePattern, int] | None:
    """Return the final matching pattern and index within one ignore file."""

    decision: tuple[_GitIgnorePattern, int] | None = None
    patterns = cast(Sequence[_GitIgnorePattern], cast(object, spec.patterns))
    for index, pattern in enumerate(patterns):
        if pattern.match_file(relative) or (
            is_directory
            and not _is_contents_only_pattern(pattern.pattern)
            and pattern.match_file(f"{relative}/")
        ):
            decision = pattern, index
    return decision


def _is_contents_only_pattern(pattern: str) -> bool:
    """Return whether a pattern applies below a directory, not to that directory itself."""

    return pattern.rstrip().endswith("/**")


def _match_loaded_ignore(
    loaded: _LoadedIgnore,
    relative: str,
    *,
    is_directory: bool,
) -> _PatternMatch | None:
    matched = _last_gitignore_pattern(loaded.spec, relative, is_directory=is_directory)
    if matched is None:
        return None
    pattern, index = matched
    if pattern.include is None:
        return None
    line = loaded.line_numbers[index] if index < len(loaded.line_numbers) else None
    return _PatternMatch(
        ignored=pattern.include,
        source=loaded.source,
        pattern=pattern.pattern,
        line=line,
    )


def _pattern_line_numbers(
    *,
    lines: Sequence[str],
    spec: GitIgnoreSpec,
) -> tuple[int | None, ...]:
    """Associate compiled patterns with their original one-based source lines."""

    line_numbers: list[int | None] = []
    cursor = 0
    patterns = cast(Sequence[_GitIgnorePattern], cast(object, spec.patterns))
    for pattern in patterns:
        line_number: int | None = None
        while cursor < len(lines):
            candidate_line = lines[cursor]
            candidate_number = cursor + 1
            cursor += 1
            if candidate_line == "":
                continue
            if candidate_line == pattern.pattern:
                line_number = candidate_number
                break
        line_numbers.append(line_number)
    return tuple(line_numbers)


def _decision_from_match(*, path: Path, match: _PatternMatch) -> GitIgnoreDecision:
    return GitIgnoreDecision(
        path=path,
        ignored=match.ignored,
        source=match.source,
        pattern=match.pattern,
        line=match.line,
    )

