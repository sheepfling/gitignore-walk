"""Native membership-aware evaluation of Darcs boring-file candidate decisions."""

from __future__ import annotations

# Private walk-session hooks are shared by the built-in policies.
# pyright: reportPrivateUsage=false
import os
import subprocess
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import islice
from math import isfinite
from pathlib import Path

from ..._policy import (
    IgnoreDecision,
    IgnoreDiagnostic,
    IgnorePolicy,
    IgnoreTrace,
    _IgnoreWalkSession,
)
from .errors import DarcsBoringError

_DEFAULT_INITIAL_EXCLUDES = ("_darcs",)


@dataclass(frozen=True, slots=True)
class _DarcsInventory:
    """One native snapshot of candidate, managed, and diagnostic paths."""

    add_candidates: frozenset[str]
    managed_paths: frozenset[str]
    candidate_output_ambiguous: bool
    diagnostics: tuple[IgnoreDiagnostic, ...]


class _DarcsWalkSession:
    """Use one membership and candidate snapshot for an entire walker traversal."""

    def __init__(self, policy: DarcsBoringPolicy) -> None:
        self._policy = policy
        self._inventory: _DarcsInventory | None = None

    def resolve_target(self, target: str | os.PathLike[str]) -> Path:
        return self._policy.resolve_target(target)

    def walk_top(self, target: str | os.PathLike[str]) -> Path:
        return self.resolve_target(target)

    def explain_many(self, targets: Iterable[str | os.PathLike[str]]) -> list[IgnoreDecision]:
        paths = [self.resolve_target(target) for target in targets]
        if self._inventory is None:
            self._inventory = self._policy._load_inventory()
        return [self._policy._decision(path, self._inventory) for path in paths]

    def should_descend_directory(self, target: Path) -> bool:
        return self._policy.should_descend_directory(target)

    def can_prune_ignored_directory(self, target: Path, decision: IgnoreDecision) -> bool:
        return self._policy.can_prune_ignored_directory(target, decision)


class DarcsBoringPolicy(IgnorePolicy):
    """Use Darcs itself to classify managed, addable, and boring workspace paths.

    Darcs boring rules filter add candidates and are applied relative to current repository state.
    A path already managed by Darcs remains eligible even when its name matches a boring rule.
    This policy preserves that membership distinction by combining ``darcs show files`` with
    ``darcs whatsnew --look-for-adds --summary``; it does not reimplement Darcs' ERE dialect.
    Managed paths use Darcs' NUL-delimited output. If the line-oriented candidate summary is
    ambiguous, the policy asks Darcs about each requested path with ``add --dry-run --reserved-ok``.

    A native inventory is refreshed for each direct query or batch, then held stable for one
    ``IgnoreWalker`` traversal. Ignored directories are never pruned because Darcs evaluates each
    repository-relative path and a matching directory name alone does not prove that every
    descendant is boring.

    Attributes:
        root: Caller-selected Darcs repository boundary and target bound.
        scheme: Stable ``"darcs"`` identifier.
        workspace_root: The caller-selected repository boundary.
    """

    @property
    def scheme(self) -> str:
        """Return the stable identifier for Darcs boring-file behavior."""
        return "darcs"

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        darcs_executable: str = "darcs",
        environment: Mapping[str, str] | None = None,
        timeout: float = 30.0,
        initial_excludes: Sequence[str] = _DEFAULT_INITIAL_EXCLUDES,
    ) -> None:
        """Bind a repository root and native Darcs command settings."""
        try:
            self.root = Path(root).expanduser().resolve()
        except (OSError, RuntimeError) as error:
            raise ValueError(f"unable to resolve Darcs policy root: {error}") from error
        if not self.root.is_dir():
            raise ValueError(f"Darcs policy root must be a directory: {self.root}")
        if not darcs_executable:
            raise ValueError("Darcs executable must be a non-empty string")
        if not isfinite(timeout) or timeout <= 0:
            raise ValueError("Darcs command timeout must be finite and positive")
        self.workspace_root = self.root
        self._darcs_executable = darcs_executable
        self._environment = dict(os.environ if environment is None else environment)
        self._timeout = timeout
        self._initial_excludes = tuple(
            item.replace("\\", "/").strip("/") for item in initial_excludes
        )

    def resolve_target(self, target: str | os.PathLike[str]) -> Path:
        """Resolve a target and reject paths outside the selected Darcs repository."""
        path = Path(target).expanduser()
        if not path.is_absolute():
            path = self.root / path
        try:
            path = path.resolve()
        except (OSError, RuntimeError) as error:
            raise ValueError(f"unable to resolve Darcs target: {error}") from error
        if not path.is_relative_to(self.root):
            raise ValueError(f"target must be inside policy root: {path}")
        return path

    def explain(self, target: str | os.PathLike[str]) -> IgnoreDecision:
        """Explain one target using a fresh native Darcs inventory."""
        path = self.resolve_target(target)
        return self._decision(path, self._load_inventory())

    def explain_many(self, targets: Iterable[str | os.PathLike[str]]) -> list[IgnoreDecision]:
        """Explain an ordered batch using one native candidate and membership snapshot."""
        paths = [self.resolve_target(target) for target in targets]
        inventory = self._load_inventory()
        return [self._decision(path, inventory) for path in paths]

    def iter_explain(
        self,
        targets: Iterable[str | os.PathLike[str]],
        *,
        batch_size: int = 256,
    ) -> Iterator[IgnoreDecision]:
        """Lazily explain targets in batches, refreshing native state for each batch."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        iterator = iter(targets)
        while batch := list(islice(iterator, batch_size)):
            yield from self.explain_many(batch)

    def trace(self, target: str | os.PathLike[str]) -> IgnoreTrace:
        """Return the native decision without inventing a per-pattern trace."""
        return IgnoreTrace(
            decision=self.explain(target),
            matches=(),
            complete=False,
        )

    def can_prune_ignored_directory(self, target: Path, decision: IgnoreDecision) -> bool:
        """Keep ignored directories traversable because descendants are checked independently."""
        del target
        return decision.reason == "baseline-exclusion"

    def _open_walk(self) -> _IgnoreWalkSession:
        """Create a walk session that holds one native inventory snapshot."""
        return _DarcsWalkSession(self)

    def _load_inventory(self) -> _DarcsInventory:
        candidates = self._run(["whatsnew", "--look-for-adds", "--summary"], "whatsnew")
        if candidates.returncode not in (0, 1) or (
            candidates.returncode == 1 and candidates.stdout.strip() != "No changes!"
        ):
            detail = candidates.stderr.strip() or candidates.stdout.strip() or "unknown Darcs error"
            raise DarcsBoringError(
                f"Darcs add-candidate discovery failed: {detail}",
                operation="whatsnew",
            )
        managed = self._run(["show", "files", "--null"], "show-files")
        if managed.returncode != 0:
            detail = managed.stderr.strip() or managed.stdout.strip() or "unknown Darcs error"
            raise DarcsBoringError(
                f"Darcs managed-path discovery failed: {detail}",
                operation="show-files",
            )
        candidate_paths, candidate_output_ambiguous = _parse_candidate_output(candidates.stdout)
        managed_paths = frozenset(
            normalized
            for path in managed.stdout.split("\0")
            if (normalized := _normalize_repository_path(path)) not in (None, ".")
        )
        diagnostics = tuple(
            IgnoreDiagnostic(
                code="darcs.native-warning",
                message=line,
                source="darcs whatsnew --look-for-adds --summary",
            )
            for line in candidates.stderr.splitlines()
            if line.strip()
        )
        return _DarcsInventory(
            candidate_paths,
            managed_paths,
            candidate_output_ambiguous,
            diagnostics,
        )

    def _run(self, arguments: Sequence[str], operation: str) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                [self._darcs_executable, *arguments],
                cwd=self.root,
                env=self._environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise DarcsBoringError(
                f"Unable to query Darcs {operation}: {error}",
                operation=operation,
            ) from error
        return result

    def _decision(self, path: Path, inventory: _DarcsInventory) -> IgnoreDecision:
        relative = path.relative_to(self.root).as_posix()
        if relative == ".":
            return IgnoreDecision(
                path=path,
                ignored=False,
                scheme=self.scheme,
                reason="workspace-root",
                discovery_complete=True,
                diagnostics=inventory.diagnostics,
            )
        normalized = _normalize_repository_path(relative)
        baseline = _baseline_match(relative, self._initial_excludes)
        if baseline is not None:
            return IgnoreDecision(
                path=path,
                ignored=True,
                scheme=self.scheme,
                source="Darcs walker baseline",
                pattern=baseline,
                scope=".",
                reason="baseline-exclusion",
                discovery_complete=True,
                diagnostics=inventory.diagnostics,
            )
        if normalized in inventory.managed_paths:
            ignored = False
            source = "darcs show files"
            reason = "managed-path"
        elif inventory.candidate_output_ambiguous or _has_control_char(relative):
            if self._is_add_candidate(relative):
                ignored = False
                source = "darcs add --dry-run --reserved-ok"
                reason = "add-candidate"
            else:
                ignored = True
                source = "Darcs native boring rules"
                reason = "boring-path"
        elif normalized in inventory.add_candidates:
            ignored = False
            source = "darcs whatsnew --look-for-adds --summary"
            reason = "add-candidate"
        else:
            ignored = True
            source = "Darcs native boring rules"
            reason = "boring-path"
        return IgnoreDecision(
            path=path,
            ignored=ignored,
            scheme=self.scheme,
            source=source,
            scope=".",
            reason=reason,
            discovery_complete=True,
            diagnostics=inventory.diagnostics,
        )

    def _is_add_candidate(self, relative: str) -> bool:
        result = self._run(
            ["add", "--dry-run", "--reserved-ok", "--", relative],
            "add-candidate-query",
        )
        if result.returncode == 0:
            return True
        if "Would skip boring file" in result.stderr:
            return False
        if result.stderr.strip().endswith("No files were added"):
            return False
        detail = result.stderr.strip() or result.stdout.strip() or "unknown Darcs error"
        raise DarcsBoringError(
            f"Darcs add-candidate query failed: {detail}",
            operation="add-candidate-query",
        )


def _parse_candidate_output(output: str) -> tuple[frozenset[str], bool]:
    paths: set[str] = set()
    ambiguous = False
    for line in output.splitlines():
        if not line or line == "No changes!":
            continue
        if len(line) >= 2 and line[0].isalpha() and line[1] == " ":
            if line[0] != "a":
                continue
        else:
            ambiguous = True
            continue
        normalized = _normalize_repository_path(line[2:])
        if normalized is None:
            ambiguous = True
            continue
        paths.add(normalized)
    return frozenset(paths), ambiguous


def _normalize_repository_path(value: str) -> str | None:
    normalized = value.replace("\\", "/").removeprefix("./")
    if normalized.endswith("/"):
        normalized = normalized[:-1]
    if not normalized or normalized.startswith("/"):
        return None
    if any(part in ("", ".", "..") for part in normalized.split("/")):
        return None
    return normalized


def _has_control_char(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _baseline_match(relative: str, excludes: Sequence[str]) -> str | None:
    parts = relative.replace("\\", "/").split("/")
    for excluded in excludes:
        if any(part == excluded for part in parts):
            return excluded
    return None
