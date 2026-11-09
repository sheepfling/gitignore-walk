"""Scheme-neutral directory traversal driven by an ignore policy."""

from __future__ import annotations

# Internal built-in policy session hook; this is not a third-party plugin API.
# pyright: reportPrivateUsage=false
import os
import stat
from collections.abc import Callable, Generator, Iterator, Sequence
from pathlib import Path
from typing import Any, Literal, NamedTuple, cast

from ._policy import IgnorePolicy, IgnoreWalkEntry
from ._schemes.git._ignore_protocols import GitIgnoreMatcher
from ._schemes.git.portable import (
    _DEFAULT_INITIAL_EXCLUDES,
    GitIgnorePolicy,
    _resolve_root,
)
from .errors import GitIgnoreError


class _WalkStackEntry(NamedTuple):
    directory: str
    names: list[str] | None
    files: list[str] | None


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
        raise GitIgnoreError(f"unable to inspect ignore-walk entry: {path}: {error}") from error


class IgnoreWalker:
    """Traverse a root with a supplied policy or the default portable Git-ignore policy.

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
        if policy is not None and (matcher is not None or initial_excludes is not None):
            raise ValueError("configure matcher and initial_excludes on the supplied policy")
        if policy is None:
            resolved_root = _resolve_root(root)
            policy = GitIgnorePolicy(
                resolved_root,
                initial_excludes=(
                    _DEFAULT_INITIAL_EXCLUDES if initial_excludes is None else initial_excludes
                ),
                matcher=matcher,
            )
        else:
            try:
                resolved_root = Path(root).expanduser().resolve()
            except (OSError, RuntimeError) as error:
                raise ValueError(f"unable to resolve traversal root: {error}") from error
            if not resolved_root.is_dir():
                raise ValueError(f"traversal root must be a directory: {resolved_root}")
        self.policy = policy
        if self.policy.root != resolved_root:
            raise ValueError("IgnoreWalker policy must use the same traversal root")
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
    ) -> Iterator[IgnoreWalkEntry]:
        """Walk regular entries using this policy's evaluation and pruning rules.

        Select included entries by default, ignored entries with ``selection="ignored"``, or both
        with ``selection="all"``. Symlinks and special files are always omitted. An ignored-only
        walk still traverses unignored directories to find ignored descendants. For included walks,
        ``dir_names`` may include ignored directories when the policy cannot safely prune them.
        """

        if selection not in ("included", "ignored", "all"):
            raise ValueError(f"unknown walk selection: {selection!r}")
        ignored = None if selection == "all" else selection == "ignored"
        session = self.policy._open_walk()
        top_path = session.walk_top(self.root if top is None else top)
        if top_path != self.root and not session.should_descend_directory(top_path):
            return
        if ignored is False and top_path != self.root and top_path.is_dir():
            top_decision = session.explain_many((top_path,))[0]
            if top_decision.ignored and session.can_prune_ignored_directory(top_path, top_decision):
                return

        def traversable_directories(
            parent_directory: str,
            child_names: list[str],
            *,
            prune_ignored: bool = True,
        ) -> list[str]:
            parent_path = Path(parent_directory)
            regular_children = [
                name
                for name in child_names
                if _is_regular_directory(parent_path / name, onerror=onerror)
            ]
            child_paths = [session.resolve_target(parent_path / name) for name in regular_children]
            descendable = [
                (name, path)
                for name, path in zip(regular_children, child_paths, strict=True)
                if session.should_descend_directory(path)
            ]
            regular_children = [name for name, _ in descendable]
            child_paths = [path for _, path in descendable]
            if not prune_ignored:
                return regular_children
            child_decisions = session.explain_many(child_paths)
            return [
                name
                for name, child_path, decision in zip(
                    regular_children, child_paths, child_decisions, strict=True
                )
                if not decision.ignored
                or not session.can_prune_ignored_directory(child_path, decision)
            ]

        if topdown:
            entries = os.walk(top_path, topdown=True, onerror=onerror, followlinks=False)
        else:
            entries = _walk_pruned_bottom_up(
                top_path,
                onerror=onerror,
                traversable_directories=lambda parent, names: traversable_directories(
                    parent, names, prune_ignored=ignored is False
                ),
            )
        for directory, dir_names, filenames in entries:
            current = Path(directory)
            safe_dir_names = [
                name
                for name in dir_names
                if _is_regular_directory(current / name, onerror=onerror)
                and session.should_descend_directory(session.resolve_target(current / name))
            ]
            safe_filenames = [
                name for name in filenames if _is_regular_file(current / name, onerror=onerror)
            ]
            dir_names[:] = safe_dir_names

            if ignored is None:
                yield IgnoreWalkEntry(current, dir_names, safe_filenames)
                continue

            paths = tuple(
                session.resolve_target(current / name)
                for name in (*safe_dir_names, *safe_filenames)
            )
            decisions = session.explain_many(paths)
            directory_decisions = decisions[: len(safe_dir_names)]
            file_decisions = decisions[len(safe_dir_names) :]
            matching_files = [
                name
                for name, decision in zip(safe_filenames, file_decisions, strict=True)
                if decision.ignored is ignored
            ]
            if not ignored:
                traversable_dirs = [
                    name
                    for name, path, decision in zip(
                        safe_dir_names,
                        paths[: len(safe_dir_names)],
                        directory_decisions,
                        strict=True,
                    )
                    if not decision.ignored
                    or not session.can_prune_ignored_directory(path, decision)
                ]
                dir_names[:] = traversable_dirs
                yield IgnoreWalkEntry(current, dir_names, matching_files)
                continue

            matching_dirs = [
                name
                for name, decision in zip(safe_dir_names, directory_decisions, strict=True)
                if decision.ignored
            ]
            yield IgnoreWalkEntry(current, matching_dirs, matching_files)


def _walk_pruned_bottom_up(
    top: Path,
    *,
    onerror: Callable[[OSError], object] | None,
    traversable_directories: Callable[[str, list[str]], list[str]],
) -> Iterator[tuple[str, list[str], list[str]]]:
    """Yield bottom-up rows while pruning only directories the policy marks safe."""
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
        names[:] = traversable_directories(directory, names)
        stack.append(_WalkStackEntry(directory, names, files))
        for name in reversed(names):
            child = os.path.join(directory, name)
            if not os.path.islink(child):
                stack.append(_WalkStackEntry(child, None, None))
