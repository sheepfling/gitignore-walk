"""Local evaluation of Fossil's effective ``ignore-glob`` setting."""

from __future__ import annotations

# Private walk-session hooks are shared by the built-in policies.
# pyright: reportPrivateUsage=false
import math
import os
import sqlite3
import subprocess
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path

from ..._policy import (
    IgnoreDecision,
    IgnorePolicy,
    IgnoreTrace,
    IgnoreTraceMatch,
    _IgnoreWalkSession,
)
from .errors import FossilIgnoreError

_WORKSPACE_MARKERS = (".fslckout", "_FOSSIL_")
_DEFAULT_INITIAL_EXCLUDES = _WORKSPACE_MARKERS


class _FossilWalkSession:
    """Use one stable effective-setting snapshot for a directory walk."""

    def __init__(self, policy: FossilIgnorePolicy) -> None:
        self._policy = policy
        self._patterns = policy._load_patterns()

    def resolve_target(self, target: str | os.PathLike[str]) -> Path:
        return self._policy.resolve_target(target)

    def walk_top(self, target: str | os.PathLike[str]) -> Path:
        return self.resolve_target(target)

    def explain_many(self, targets: Iterable[str | os.PathLike[str]]) -> list[IgnoreDecision]:
        return [self._policy._explain_with_patterns(target, self._patterns) for target in targets]

    def should_descend_directory(self, target: Path) -> bool:
        return self._policy.should_descend_directory(target)

    def can_prune_ignored_directory(self, target: Path, decision: IgnoreDecision) -> bool:
        return self._policy.can_prune_ignored_directory(target, decision)


class FossilIgnorePolicy(IgnorePolicy):
    """Evaluate the effective Fossil ``ignore-glob`` setting for workspace paths.

    Fossil supplies the effective setting, including versioned-over-local-over-global precedence;
    this policy evaluates it locally using SQLite's ``GLOB`` operator. Patterns are full paths
    relative to the Fossil checkout root, and ``*`` can match directory separators. The policy
    implements the Fossil list separators and quote-delimited patterns. Fossil has no negation.
    Ignore matches describe exclusion rules, not whether a path is already tracked. The walker
    baseline omits the Fossil checkout marker files by default.

    Attributes:
        root: Caller traversal root, bounded to this policy's targets.
        workspace_root: Discovered Fossil checkout root.
        scheme: Stable ``"fossil"`` identifier.
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
    ) -> None:
        """Bind a caller root to a Fossil checkout and load its effective ignore setting.

        ``initial_excludes`` defaults to the Fossil workspace markers so they are not yielded as
        ordinary included files. Pass an empty sequence to disable this walker baseline.
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

    def explain(self, target: str | os.PathLike[str]) -> IgnoreDecision:
        """Explain whether Fossil's effective ignore setting matches one path."""
        return self._explain_with_patterns(target, self._load_patterns())

    def explain_many(self, targets: Iterable[str | os.PathLike[str]]) -> list[IgnoreDecision]:
        """Explain an ordered set of paths using one effective-setting snapshot."""
        patterns = self._load_patterns()
        return [self._explain_with_patterns(target, patterns) for target in targets]

    def iter_explain(
        self, targets: Iterable[str | os.PathLike[str]], *, batch_size: int = 256
    ) -> Iterator[IgnoreDecision]:
        """Lazily explain paths using one stable effective-setting snapshot."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        patterns = self._load_patterns()
        for target in targets:
            yield self._explain_with_patterns(target, patterns)

    def trace(self, target: str | os.PathLike[str]) -> IgnoreTrace:
        """Return all Fossil glob matches in setting order."""
        path = self.resolve_target(target)
        patterns = self._load_patterns()
        matches = self._matching_patterns(path, patterns)
        decision = self._decision(path, matches[0] if matches else None)
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

    def _explain_with_patterns(
        self, target: str | os.PathLike[str], patterns: tuple[str, ...]
    ) -> IgnoreDecision:
        path = self.resolve_target(target)
        matches = self._matching_patterns(path, patterns)
        return self._decision(path, matches[0] if matches else None)

    def _matching_patterns(self, target: Path, patterns: tuple[str, ...]) -> tuple[str, ...]:
        relative = target.relative_to(self.workspace_root).as_posix()
        baseline = target.relative_to(self.root).as_posix()
        if self._initial_excludes and any(
            _matches_glob(baseline, item) for item in self._initial_excludes
        ):
            return ()
        prefixes = _path_prefixes(relative)
        return _matching_patterns(prefixes, patterns)

    def _decision(self, path: Path, pattern: str | None) -> IgnoreDecision:
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
