"""Scheme-neutral decision models and policy interface."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, NamedTuple, Protocol, TypeAlias


@dataclass(frozen=True, slots=True)
class IgnoreDiagnostic:
    """A non-fatal discovery or evaluation diagnostic attached to a decision.

    Attributes:
        code: Stable, policy-defined diagnostic identifier.
        message: Human-readable description of the issue.
        source: Source associated with the diagnostic, when known.
        severity: Diagnostic importance, independent of whether the decision is ignored.
    """

    code: str
    message: str
    source: str | None = None
    severity: Literal["info", "warning", "error"] = "warning"


@dataclass(frozen=True, slots=True)
class IgnoreDecision:
    """Explain one target's effective ignore decision.

    Attributes:
        path: Resolved target path.
        ignored: Whether the effective rule excludes the target.
        scheme: Stable identifier of the ignore dialect, when known.
        source: Identifier for the file, property, or configuration containing the rule.
        pattern: Matched rule text or expression, or ``None`` when no rule matched.
        line: One-based source line when available; property-based rules may omit it.
        property_name: Name of a property that supplied the rule, when applicable.
        scope: Effective source scope, when the policy can represent it.
        reason: Policy-defined reason for the decision, such as ``matched-rule``.
        discovery_complete: Whether the policy found all applicable ignore sources.
        diagnostics: Non-fatal discovery or evaluation issues.
    """

    path: Path
    ignored: bool
    scheme: str = field(kw_only=True)
    source: str | None = None
    pattern: str | None = None
    line: int | None = None
    property_name: str | None = None
    scope: str | None = None
    reason: str | None = None
    discovery_complete: bool = field(kw_only=True)
    diagnostics: tuple[IgnoreDiagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class IgnoreTraceMatch:
    """One matching rule in an ignore-policy trace.

    Attributes:
        source: Identifier for the file, property, or configuration containing the rule.
        pattern: Rule text or expression as represented by the policy.
        line: One-based source line when available; property-based rules may omit it.
        scheme: Stable identifier of the ignore dialect, when known.
        property_name: Name of a property that supplied the rule, when applicable.
        scope: Effective source scope, when the policy can represent it.
        reason: Policy-defined reason this rule affected the result.
        ignored: Whether this rule excludes the target.
        effective: Whether this rule determines the final policy decision.
    """

    source: str
    pattern: str
    line: int | None
    ignored: bool
    effective: bool
    scheme: str = field(kw_only=True)
    property_name: str | None = None
    scope: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class IgnoreTrace:
    """Effective decision plus matching rules ordered by precedence.

    Attributes:
        decision: Final decision for the target.
        matches: Applicable matching rules in precedence order.
        complete: Whether the backend could enumerate every applicable matching rule.
    """

    decision: IgnoreDecision
    matches: tuple[IgnoreTraceMatch, ...]
    complete: bool = True


class IgnoreWalkEntry(NamedTuple):
    """One ``os.walk``-style row with names for each returned value.

    Attributes:
        directory: Directory represented by this row.
        dir_names: Traversal candidates, mutable for top-down pruning. A policy may include
            ignored directories here when it cannot safely prune them.
        file_names: File names selected by the walk's policy.
    """

    directory: Path
    dir_names: list[str]
    file_names: list[str]


_Target: TypeAlias = str | os.PathLike[str]


class _IgnoreWalkSession(Protocol):
    """One walk's policy evaluation and safe-pruning operations."""

    def resolve_target(self, target: _Target) -> Path: ...

    def walk_top(self, target: _Target) -> Path: ...

    def explain_many(self, targets: Iterable[_Target]) -> list[IgnoreDecision]: ...

    def can_prune_ignored_directory(self, target: Path, decision: IgnoreDecision) -> bool: ...


class _DefaultIgnoreWalkSession:
    """Live, conservative session used by policies without a snapshot implementation."""

    def __init__(self, policy: IgnorePolicy) -> None:
        self._policy = policy

    def resolve_target(self, target: _Target) -> Path:
        return self._policy.resolve_target(target)

    def walk_top(self, target: _Target) -> Path:
        return self.resolve_target(target)

    def explain_many(self, targets: Iterable[_Target]) -> list[IgnoreDecision]:
        return self._policy.explain_many(targets)

    def can_prune_ignored_directory(self, target: Path, decision: IgnoreDecision) -> bool:
        return self._policy.can_prune_ignored_directory(target, decision)


class IgnorePolicy(ABC):
    """Scheme-neutral interface for policies used by :class:`IgnoreWalker`.

    Subclasses provide target resolution and decision evaluation. The default walk session uses
    live decisions and conservatively descends into ignored directories unless the policy confirms
    pruning is safe.

    Attributes:
        root: Resolved root that bounds every target handled by the policy.
        scheme: Stable identifier for the ignore dialect implemented by the policy.
    """

    root: Path

    @property
    @abstractmethod
    def scheme(self) -> str:
        """Return the stable identifier for this policy's ignore dialect."""

    @abstractmethod
    def explain(self, target: _Target) -> IgnoreDecision:
        """Explain one target."""

    @abstractmethod
    def iter_explain(
        self, targets: Iterable[_Target], *, batch_size: int = 256
    ) -> Iterator[IgnoreDecision]:
        """Lazily explain targets in input order."""

    @abstractmethod
    def resolve_target(self, target: _Target) -> Path:
        """Resolve a target according to this policy's path rules."""

    def explain_many(self, targets: Iterable[_Target]) -> list[IgnoreDecision]:
        """Explain targets in input order."""
        return list(self.iter_explain(targets))

    def trace(self, target: _Target) -> IgnoreTrace:
        """Return the decision and matching-rule trace for one target.

        Policies that cannot enumerate every matching rule return their winning rule with
        ``complete=False``.
        """
        decision = self.explain(target)
        matches = (
            ()
            if decision.source is None
            else (
                IgnoreTraceMatch(
                    source=decision.source,
                    pattern=decision.pattern or "",
                    line=decision.line,
                    ignored=decision.ignored,
                    effective=True,
                    scheme=decision.scheme,
                    property_name=decision.property_name,
                    scope=decision.scope,
                    reason=decision.reason,
                ),
            )
        )
        return IgnoreTrace(decision=decision, matches=matches, complete=False)

    def is_ignored(self, target: _Target) -> bool:
        """Return whether one target is ignored by this policy."""
        return self.explain(target).ignored

    def is_ignored_many(self, targets: Iterable[_Target]) -> list[bool]:
        """Return ignore decisions in the same order as ``targets``."""
        return [decision.ignored for decision in self.explain_many(targets)]

    def iter_ignored(self, targets: Iterable[_Target], *, batch_size: int = 256) -> Iterator[bool]:
        """Yield ignore decisions lazily in input order, querying bounded batches."""
        return (decision.ignored for decision in self.iter_explain(targets, batch_size=batch_size))

    def can_prune_ignored_directory(self, target: Path, decision: IgnoreDecision) -> bool:
        """Return whether an ignored directory can be skipped without missing included descendants.

        The conservative default is ``False``. Implementations should return ``True`` only when
        their rule semantics guarantee that no descendant can be included by a more specific rule.
        """
        return False

    def _open_walk(self) -> _IgnoreWalkSession:
        """Create the policy evaluation session used for one traversal."""
        return _DefaultIgnoreWalkSession(self)
