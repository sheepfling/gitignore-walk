"""Local evaluation of Fossil's effective ``ignore-glob`` setting."""

from __future__ import annotations

# Private walk-session hooks are shared by the built-in policies.
# pyright: reportPrivateUsage=false
import json
import math
import os
import sqlite3
import subprocess
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from ..._policy import (
    IgnoreDecision,
    IgnorePolicy,
    IgnoreTrace,
    IgnoreTraceMatch,
    _IgnoreWalkSession,
)
from ..._util import is_nested_workspace_directory
from .errors import FossilIgnoreError

_WORKSPACE_MARKERS = (".fslckout", "_FOSSIL_")
_DEFAULT_INITIAL_EXCLUDES = _WORKSPACE_MARKERS
_EMPTY_PATHS: frozenset[Path] = frozenset()


class _FossilWalkSession:
    """Use stable Fossil setting and status snapshots for a directory walk."""

    def __init__(self, policy: FossilIgnorePolicy) -> None:
        self._policy = policy
        self._patterns = policy._load_patterns()
        self._status_paths = (
            policy._load_status_membership() if policy.membership_aware else _EMPTY_PATHS
        )

    def resolve_target(self, target: str | os.PathLike[str]) -> Path:
        return self._policy.resolve_target(target)

    def walk_top(self, target: str | os.PathLike[str]) -> Path:
        return self.resolve_target(target)

    def explain_many(self, targets: Iterable[str | os.PathLike[str]]) -> list[IgnoreDecision]:
        paths = tuple(targets)
        versioned_paths = (
            self._policy._load_membership(paths, self._status_paths)
            if self._policy.membership_aware
            else None
        )
        return [
            self._policy._explain_with_patterns(target, self._patterns, versioned_paths)
            for target in paths
        ]

    def should_descend_directory(self, target: Path) -> bool:
        return self._policy.should_descend_directory(target)

    def should_select_file(self, target: Path) -> bool:
        return self._policy.should_select_file(target)

    def can_prune_ignored_directory(self, target: Path, decision: IgnoreDecision) -> bool:
        return self._policy.can_prune_ignored_directory(target, decision)


class FossilIgnorePolicy(IgnorePolicy):
    """Evaluate the effective Fossil ``ignore-glob`` setting for workspace paths.

    Fossil supplies the effective setting, including versioned-over-local-over-global precedence;
    this policy evaluates it locally using SQLite's ``GLOB`` operator. Patterns are full paths
    relative to the Fossil checkout root, and ``*`` can match directory separators. The policy
    implements the Fossil list separators and quote-delimited patterns. Fossil has no negation.
    Ignore matches describe exclusion rules, not whether a path is already tracked. The walker
    baseline omits the Fossil checkout marker files by default, and nested Fossil checkouts are
    traversal boundaries matching parent ``fossil extras`` behavior.

    Set ``membership_aware=True`` to query Fossil's structured checkout JSON and report known file
    membership independently from ignore decisions. Directory membership remains unknown because
    Fossil versions files, not directories.

    Attributes:
        root: Caller traversal root, bounded to this policy's targets.
        workspace_root: Discovered Fossil checkout root.
        scheme: Stable ``"fossil"`` identifier.
        membership_aware: Whether file membership is queried independently from ignore matches.
    """

    @property
    def scheme(self) -> str:
        """Return the stable identifier for Fossil ignore globs."""
        return "fossil"

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        fossil_executable: str = "fossil",
        environment: Mapping[str, str] | None = None,
        timeout: float = 30.0,
        initial_excludes: Sequence[str] | None = None,
        membership_aware: bool = False,
    ) -> None:
        """Bind a caller root to a Fossil checkout and load its effective ignore setting.

        ``initial_excludes`` defaults to the Fossil workspace markers so they are not yielded as
        ordinary included files. Pass an empty sequence to disable this walker baseline.

        ``membership_aware`` enables read-only membership queries through Fossil's JSON interface;
        directories and paths absent from native inventory and the local filesystem stay unknown.
        """
        try:
            self.root = Path(root).expanduser().resolve()
        except (OSError, RuntimeError) as error:
            raise ValueError(f"unable to resolve Fossil policy root: {error}") from error
        if not self.root.is_dir():
            raise ValueError(f"Fossil policy root must be a directory: {self.root}")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        self.fossil_executable = fossil_executable
        self.timeout = timeout
        self._environment = dict(os.environ if environment is None else environment)
        self.membership_aware = membership_aware
        excludes = _DEFAULT_INITIAL_EXCLUDES if initial_excludes is None else initial_excludes
        self._initial_excludes = tuple(item.replace("\\", "/").strip("/") for item in excludes)
        self.workspace_root = _find_workspace_root(self.root)
        self._load_patterns()

    def resolve_target(self, target: str | os.PathLike[str]) -> Path:
        """Resolve a target and reject paths outside the caller's traversal root."""
        path = Path(target).expanduser()
        if not path.is_absolute():
            path = self.root / path
        try:
            path = path.resolve()
        except (OSError, RuntimeError) as error:
            raise ValueError(f"unable to resolve Fossil target: {error}") from error
        if not path.is_relative_to(self.root):
            raise ValueError(f"target must be inside policy root: {path}")
        return path

    def should_descend_directory(self, target: Path) -> bool:
        """Stop at nested Fossil checkouts while allowing traversal into this checkout root."""
        return not is_nested_workspace_directory(target, self.workspace_root, _WORKSPACE_MARKERS)

    def explain(self, target: str | os.PathLike[str]) -> IgnoreDecision:
        """Explain whether Fossil's effective ignore setting matches one path."""
        versioned_paths = self._load_membership((target,)) if self.membership_aware else None
        return self._explain_with_patterns(target, self._load_patterns(), versioned_paths)

    def explain_many(self, targets: Iterable[str | os.PathLike[str]]) -> list[IgnoreDecision]:
        """Explain an ordered set of paths using one effective-setting snapshot."""
        paths = tuple(targets)
        patterns = self._load_patterns()
        status_paths = self._load_status_membership() if self.membership_aware else _EMPTY_PATHS
        versioned_paths = (
            self._load_membership(paths, status_paths) if self.membership_aware else None
        )
        return [self._explain_with_patterns(target, patterns, versioned_paths) for target in paths]

    def iter_explain(
        self, targets: Iterable[str | os.PathLike[str]], *, batch_size: int = 256
    ) -> Iterator[IgnoreDecision]:
        """Lazily explain paths using one stable effective-setting snapshot."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        patterns = self._load_patterns()
        status_paths = self._load_status_membership() if self.membership_aware else _EMPTY_PATHS
        for target in targets:
            versioned_paths = (
                self._load_membership((target,), status_paths) if self.membership_aware else None
            )
            yield self._explain_with_patterns(target, patterns, versioned_paths)

    def trace(self, target: str | os.PathLike[str]) -> IgnoreTrace:
        """Return all Fossil glob matches in setting order."""
        path = self.resolve_target(target)
        patterns = self._load_patterns()
        status_paths = self._load_status_membership() if self.membership_aware else _EMPTY_PATHS
        versioned_paths = (
            self._load_membership((path,), status_paths) if self.membership_aware else None
        )
        matches = self._matching_patterns(path, patterns)
        decision = self._decision(path, matches[0] if matches else None, versioned_paths)
        trace = tuple(
            IgnoreTraceMatch(
                source="effective Fossil ignore-glob setting",
                pattern=pattern,
                line=None,
                ignored=True,
                effective=index == 0,
                scheme=self.scheme,
                property_name="ignore-glob",
                scope=".",
                reason="matched-rule",
            )
            for index, pattern in enumerate(matches)
        )
        return IgnoreTrace(decision=decision, matches=trace, complete=True)

    def can_prune_ignored_directory(self, target: Path, decision: IgnoreDecision) -> bool:
        """Prune matched directories because Fossil ignore patterns have no negation."""
        del target
        return decision.ignored

    def _open_walk(self) -> _IgnoreWalkSession:
        """Create a walk session with a stable Fossil setting snapshot."""
        return _FossilWalkSession(self)

    def _load_patterns(self) -> tuple[str, ...]:
        """Ask Fossil for its effective setting and split its documented pattern list."""
        try:
            result = subprocess.run(
                [self.fossil_executable, "settings", "ignore-glob", "--value"],
                cwd=self.workspace_root,
                env=self._environment,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except OSError as error:
            raise FossilIgnoreError(
                f"Unable to run Fossil settings command: {error}",
                operation="settings",
                path=str(self.workspace_root),
            ) from error
        except subprocess.TimeoutExpired as error:
            raise FossilIgnoreError(
                f"Fossil settings command timed out after {self.timeout:g} seconds.",
                operation="settings",
                path=str(self.workspace_root),
            ) from error
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise FossilIgnoreError(
                f"Fossil settings command failed with exit code {result.returncode}: {detail}",
                operation="settings",
                path=str(self.workspace_root),
            )
        return _parse_glob_list(result.stdout.decode("utf-8", errors="replace"))

    def _load_membership(
        self,
        targets: Iterable[str | os.PathLike[str]],
        status_paths: frozenset[Path] | None = None,
    ) -> frozenset[Path]:
        """Read requested file membership from Fossil's structured checkout JSON commands."""
        versioned: set[Path] = set(status_paths or ())
        directories: set[str] = set()
        for target in targets:
            path = self.resolve_target(target)
            if path.is_dir():
                continue
            parent = path.parent
            if parent.is_dir():
                directories.add(parent.relative_to(self.workspace_root).as_posix())
        for directory in sorted(directories):
            payload = self._run_json(
                ["dir", "--checkin", "current", "--name", "/" if directory == "." else directory],
                operation="membership-directory",
            )
            entries_value = payload.get("entries")
            if entries_value is None:
                continue
            if not isinstance(entries_value, list):
                raise FossilIgnoreError(
                    "Fossil directory JSON did not contain an entries list.",
                    operation="membership-directory",
                    path=directory or ".",
                )
            entries = cast(list[dict[str, object]], entries_value)
            for entry in entries:
                name = entry.get("name")
                if not isinstance(name, str):
                    raise FossilIgnoreError(
                        "Fossil directory JSON contained an invalid entry.",
                        operation="membership-directory",
                        path=directory or ".",
                    )
                relative = f"{directory}/{name}" if directory else name
                entry_path = self._membership_path(relative, operation="membership-directory")
                if entry.get("isDir") is True:
                    continue
                versioned.add(entry_path)

        if status_paths is None:
            versioned.update(self._load_status_membership())
        return frozenset(versioned)

    def _load_status_membership(self) -> frozenset[Path]:
        """Read staged, missing, and otherwise changed paths from Fossil checkout status."""
        versioned: set[Path] = set()
        status = self._run_json(["status"], operation="membership-status")
        files_value = status.get("files", [])
        if not isinstance(files_value, list):
            raise FossilIgnoreError(
                "Fossil status JSON did not contain a files list.", operation="membership-status"
            )
        files = cast(list[dict[str, object]], files_value)
        for item in files:
            relative = item.get("name")
            if not isinstance(relative, str):
                raise FossilIgnoreError(
                    "Fossil status JSON contained an invalid file entry.",
                    operation="membership-status",
                )
            versioned.add(self._membership_path(relative, operation="membership-status"))
        return frozenset(versioned)

    def _membership_path(self, relative: str, *, operation: str) -> Path:
        """Resolve a client-reported relative path and reject checkout escapes."""
        relative_path = Path(relative)
        candidate = self.workspace_root / relative_path
        if (
            relative_path.is_absolute()
            or ".." in relative_path.parts
            or not candidate.is_relative_to(self.workspace_root)
        ):
            raise FossilIgnoreError(
                "Fossil returned a membership path outside the checkout.",
                operation=operation,
                path=relative,
            )
        return candidate

    def _run_json(self, arguments: Sequence[str], *, operation: str) -> dict[str, Any]:
        """Run a read-only Fossil JSON command and validate its response envelope."""
        try:
            result = subprocess.run(
                [self.fossil_executable, "json", *arguments],
                cwd=self.workspace_root,
                env=self._environment,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except OSError as error:
            raise FossilIgnoreError(
                f"Unable to run Fossil {operation} query: {error}",
                operation=operation,
                path=str(self.workspace_root),
            ) from error
        except subprocess.TimeoutExpired as error:
            raise FossilIgnoreError(
                f"Fossil {operation} query timed out after {self.timeout:g} seconds.",
                operation=operation,
                path=str(self.workspace_root),
            ) from error
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise FossilIgnoreError(
                f"Fossil {operation} query failed with exit code {result.returncode}: {detail}",
                operation=operation,
                path=str(self.workspace_root),
            )
        try:
            document: Any = json.loads(result.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FossilIgnoreError(
                f"Fossil {operation} query returned invalid JSON: {error}",
                operation=operation,
                path=str(self.workspace_root),
            ) from error
        payload: Any = (
            cast(dict[str, Any], document).get("payload") if isinstance(document, dict) else None
        )
        if not isinstance(payload, dict):
            raise FossilIgnoreError(
                f"Fossil {operation} JSON did not contain a payload object.",
                operation=operation,
                path=str(self.workspace_root),
            )
        return cast(dict[str, Any], payload)

    def _explain_with_patterns(
        self,
        target: str | os.PathLike[str],
        patterns: tuple[str, ...],
        versioned_paths: frozenset[Path] | None,
    ) -> IgnoreDecision:
        path = self.resolve_target(target)
        matches = self._matching_patterns(path, patterns)
        return self._decision(path, matches[0] if matches else None, versioned_paths)

    def _matching_patterns(self, target: Path, patterns: tuple[str, ...]) -> tuple[str, ...]:
        relative = target.relative_to(self.workspace_root).as_posix()
        baseline = target.relative_to(self.root).as_posix()
        if self._initial_excludes and any(
            _matches_glob(baseline, item) for item in self._initial_excludes
        ):
            return ()
        prefixes = _path_prefixes(relative)
        return _matching_patterns(prefixes, patterns)

    def _decision(
        self, path: Path, pattern: str | None, versioned_paths: frozenset[Path] | None = None
    ) -> IgnoreDecision:
        relative = path.relative_to(self.root).as_posix()
        baseline = next(
            (item for item in self._initial_excludes if _matches_glob(relative, item)), None
        )
        if baseline is not None:
            return IgnoreDecision(
                path=path,
                ignored=True,
                scheme=self.scheme,
                source="Fossil walker baseline",
                pattern=baseline,
                scope=".",
                reason="baseline-exclusion",
                discovery_complete=True,
            )
        membership = None
        if self.membership_aware and versioned_paths is not None and not path.is_dir():
            if path in versioned_paths:
                membership = "versioned"
            elif path.exists():
                membership = "unversioned"
        return IgnoreDecision(
            path=path,
            ignored=pattern is not None,
            scheme=self.scheme,
            source="effective Fossil ignore-glob setting" if pattern else None,
            pattern=pattern,
            property_name="ignore-glob" if pattern else None,
            scope="." if pattern else None,
            reason="matched-rule" if pattern else "no-matching-rule",
            discovery_complete=True,
            membership=membership,
        )


def _find_workspace_root(root: Path) -> Path:
    """Find the nearest ancestor containing Fossil's checkout marker."""
    for candidate in (root, *root.parents):
        if any((candidate / marker).exists() for marker in _WORKSPACE_MARKERS):
            return candidate
    raise ValueError(f"no Fossil checkout found at or above policy root: {root}")


def _parse_glob_list(value: str) -> tuple[str, ...]:
    """Split Fossil's ASCII whitespace/comma list while preserving quote-delimited patterns."""
    patterns: list[str] = []
    token: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(value):
        character = value[index]
        if quote is not None:
            if character == quote:
                patterns.append("".join(token))
                token.clear()
                quote = None
            else:
                token.append(character)
        elif character in "\"'" and not token:
            quote = character
        elif character == "," or character in "\t\n\v\f\r ":
            if token:
                patterns.append("".join(token))
                token.clear()
        else:
            token.append(character)
        index += 1
    if token:
        patterns.append("".join(token))
    elif quote is not None:
        patterns.append("")
    return tuple(pattern for pattern in patterns if pattern)


def _matches_glob(path: str, pattern: str) -> bool:
    """Apply SQLite's case-sensitive GLOB operator to one path and one pattern."""
    with sqlite3.connect(":memory:") as connection:
        result = connection.execute("SELECT ? GLOB ?", (path, pattern)).fetchone()
    return bool(result and result[0])


def _matching_patterns(paths: tuple[str, ...], patterns: tuple[str, ...]) -> tuple[str, ...]:
    """Return patterns matching any candidate path, preserving setting order."""
    if not paths or not patterns:
        return ()
    with sqlite3.connect(":memory:") as connection:
        return tuple(
            pattern
            for pattern in patterns
            if any(
                (row := connection.execute("SELECT ? GLOB ?", (path, pattern)).fetchone())
                and row[0]
                for path in paths
            )
        )


def _path_prefixes(path: str) -> tuple[str, ...]:
    """Return a path and its directory prefixes from most specific to least specific."""
    parts = path.split("/")
    return tuple("/".join(parts[:index]) for index in range(len(parts), 0, -1))
