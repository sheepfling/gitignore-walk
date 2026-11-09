"""Discover and compile Mercurial ignore files and their include graph."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from ..._policy import IgnoreDiagnostic
from ._patterns import HgRule, compile_rule, parse_pattern_lines
from .errors import MercurialIgnoreError

_MAX_INCLUDE_DEPTH = 32
_MAX_SOURCE_COUNT = 256
_MAX_SOURCE_BYTES = 4 * 1024 * 1024
_MAX_TOTAL_BYTES = 32 * 1024 * 1024
_WINDOWS = os.name == "nt"


@dataclass(slots=True)
class _LoadState:
    rules: list[HgRule]
    diagnostics: list[IgnoreDiagnostic]
    active: set[Path]
    source_count: int = 0
    source_bytes: int = 0


@dataclass(frozen=True, slots=True)
class HgIgnoreSources:
    """Compiled rules and diagnostics discovered from Mercurial ignore sources."""

    rules: tuple[HgRule, ...]
    diagnostics: tuple[IgnoreDiagnostic, ...]
    complete: bool


def load_ignore_sources(
    workspace_root: Path,
    configured_sources: tuple[Path, ...] = (),
) -> HgIgnoreSources:
    """Load the workspace ``.hgignore`` and explicit extra ignore files."""
    state = _LoadState(rules=[], diagnostics=[], active=set())
    root_source = workspace_root / ".hgignore"
    if root_source.is_file():
        _load_source(root_source, workspace_root, workspace_root, state, depth=0)
    for configured in configured_sources:
        path = configured if configured.is_absolute() else workspace_root / configured
        _load_source(path, workspace_root, workspace_root, state, depth=0)
    incomplete = any(
        diagnostic.code in {"source-unavailable", "include-cycle", "source-limit"}
        for diagnostic in state.diagnostics
    )
    return HgIgnoreSources(tuple(state.rules), tuple(state.diagnostics), not incomplete)


def _load_source(
    source: Path,
    workspace_root: Path,
    matcher_root: Path,
    state: _LoadState,
    *,
    depth: int,
) -> None:
    if _WINDOWS and _has_symlink_component(source):
        state.diagnostics.append(
            IgnoreDiagnostic(
                code="source-unavailable",
                message="Mercurial on Windows skips ignore sources reached through symlinks.",
                source=str(source),
                severity="warning",
            )
        )
        return
    try:
        canonical = source.resolve()
    except (OSError, RuntimeError) as error:
        state.diagnostics.append(
            IgnoreDiagnostic(
                code="source-unavailable",
                message=f"Unable to resolve Mercurial ignore source: {error}",
                source=str(source),
            )
        )
        return
    if depth > _MAX_INCLUDE_DEPTH or state.source_count >= _MAX_SOURCE_COUNT:
        state.diagnostics.append(
            IgnoreDiagnostic(
                code="source-limit",
                message="Mercurial ignore source graph exceeded its configured limit.",
                source=str(source),
                severity="error",
            )
        )
        return
    if canonical in state.active:
        state.diagnostics.append(
            IgnoreDiagnostic(
                code="include-cycle",
                message="Mercurial ignore source contains an include cycle.",
                source=str(source),
                severity="error",
            )
        )
        return
    state.source_count += 1
    try:
        source_stat = canonical.stat()
    except OSError as error:
        state.diagnostics.append(
            IgnoreDiagnostic(
                code="source-unavailable",
                message=f"Unable to inspect Mercurial ignore source: {error}",
                source=str(source),
            )
        )
        return
    if not stat.S_ISREG(source_stat.st_mode):
        state.diagnostics.append(
            IgnoreDiagnostic(
                code="source-unavailable",
                message="Mercurial ignore source is not a regular file.",
                source=str(source),
                severity="warning",
            )
        )
        return
    byte_limit = min(_MAX_SOURCE_BYTES, _MAX_TOTAL_BYTES - state.source_bytes)
    if source_stat.st_size > byte_limit:
        state.diagnostics.append(
            IgnoreDiagnostic(
                code="source-limit",
                message="Mercurial ignore source exceeded its configured byte limit.",
                source=str(source),
                severity="error",
            )
        )
        return
    try:
        with canonical.open("rb") as stream:
            contents = stream.read(byte_limit + 1)
    except OSError as error:
        state.diagnostics.append(
            IgnoreDiagnostic(
                code="source-unavailable",
                message=f"Unable to read Mercurial ignore source: {error}",
                source=str(source),
                severity="warning",
            )
        )
        return
    if len(contents) > byte_limit:
        state.diagnostics.append(
            IgnoreDiagnostic(
                code="source-limit",
                message="Mercurial ignore source exceeded its configured byte limit.",
                source=str(source),
                severity="error",
            )
        )
        return
    state.source_bytes += len(contents)
    state.active.add(canonical)
    try:
        try:
            records = parse_pattern_lines(contents)
        except ValueError as error:
            raise MercurialIgnoreError(
                f"unable to parse Mercurial ignore source {source}: {error}",
                operation="parse",
                source=str(source),
            ) from error
        for record in records:
            if record.kind == "invalid-syntax":
                state.diagnostics.append(
                    IgnoreDiagnostic(
                        code="invalid-syntax",
                        message=(
                            f"Invalid Mercurial syntax {record.pattern!r}; "
                            "the previous syntax remains active."
                        ),
                        source=str(source),
                    )
                )
            elif record.kind == "rule":
                try:
                    rule = compile_rule(
                        source=canonical,
                        pattern=record.pattern,
                        line=record.line,
                        syntax=record.syntax,
                        matcher_root=matcher_root,
                    )
                except ValueError as error:
                    raise MercurialIgnoreError(
                        str(error),
                        operation="parse",
                        source=str(source),
                        line=record.line,
                    ) from error
                state.rules.append(rule)
            else:
                edge = Path(record.pattern)
                if record.kind == "include":
                    included_source = edge if edge.is_absolute() else workspace_root / edge
                    included_root = matcher_root
                else:
                    included_source = edge if edge.is_absolute() else canonical.parent / edge
                    included_root = included_source.parent
                _load_source(
                    included_source,
                    workspace_root,
                    included_root,
                    state,
                    depth=depth + 1,
                )
    finally:
        state.active.remove(canonical)


def _has_symlink_component(source: Path) -> bool:
    """Return whether a lexical source path crosses a symlink before resolution."""
    absolute = source.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return False
    return False
