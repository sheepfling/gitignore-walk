"""Native Subversion property discovery with local glob evaluation."""

from __future__ import annotations

# Private walk-session hooks are shared by the built-in policies.
# pyright: reportPrivateUsage=false
import math
import os
import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import islice
from pathlib import Path

from ..._policy import (
    IgnoreDecision,
    IgnoreDiagnostic,
    IgnorePolicy,
    IgnoreTrace,
    IgnoreTraceMatch,
    _IgnoreWalkSession,
)
from ._config import load_runtime_global_ignores
from ._glob import matches_svn_glob, split_svn_property_patterns
from .errors import SubversionIgnoreError

_DEFAULT_INITIAL_EXCLUDES = (".svn",)
_DEFAULT_GLOBAL_IGNORES = (
    "*.o",
    "*.lo",
    "*.la",
    "*.al",
    ".libs",
    "*.so",
    "*.so.[0-9]*",
    "*.a",
    "*.pyc",
    "*.pyo",
    "__pycache__",
    "*.rej",
    "*~",
    "#*#",
    ".#*",
    ".*.swp",
    ".DS_Store",
    "[Tt]humbs.db",
)
_IGNORE_PROPERTY = "svn:ignore"
_GLOBAL_IGNORE_PROPERTY = "svn:global-ignores"


@dataclass(frozen=True, slots=True)
class _SvnRule:
    """One native-discovered Subversion glob and its versioned property source."""

    source: str
    scope: str
    property_name: str
    pattern: str


@dataclass(frozen=True, slots=True)
class _SvnPropertySnapshot:
    """All supported directory properties observed in one working-copy query."""

    workspace_root: Path
    rules: tuple[_SvnRule, ...]
    excluded_roots: frozenset[Path] = frozenset()
    discovery_complete: bool = True
    diagnostics: tuple[IgnoreDiagnostic, ...] = ()


class _SubversionWalkSession:
    """Keep property and external-root snapshots stable for one filesystem walk."""

    def __init__(self, policy: SubversionIgnorePolicy) -> None:
        self._policy = policy
        self._snapshot = policy._load_snapshot()
        self._external_roots = policy._load_external_roots()
        self._external_snapshots = tuple(
            policy._load_snapshot(workspace_root=root) for root in sorted(self._external_roots)
        )

    def resolve_target(self, target: str | os.PathLike[str]) -> Path:
        return self._policy.resolve_target(target)

    def walk_top(self, target: str | os.PathLike[str]) -> Path:
        path = self.resolve_target(target)
        if path.is_symlink():
            raise ValueError("Subversion walks cannot start at a symlink")
        return path

    def explain_many(self, targets: Iterable[str | os.PathLike[str]]) -> list[IgnoreDecision]:
        snapshots = (self._snapshot, *self._external_snapshots)
        return [self._policy._explain_with_snapshots(target, snapshots) for target in targets]

    def should_descend_directory(self, target: Path) -> bool:
        return self._policy._should_descend_directory(
            target, self._external_roots, self._snapshot.excluded_roots
        )

    def can_prune_ignored_directory(self, target: Path, decision: IgnoreDecision) -> bool:
        return self._policy.can_prune_ignored_directory(target, decision)


class SubversionIgnorePolicy(IgnorePolicy):
    """Evaluate versioned Subversion ignore properties in a working copy.

    The native ``svn`` client discovers versioned directory properties. This policy evaluates
    ``svn:ignore`` (direct children only) and inherited ``svn:global-ignores`` rules locally with
    case-sensitive shell-style filename globs. It applies Subversion's built-in
    ``global-ignores`` defaults. If ``config_dir`` is supplied and its ``config`` file defines
    ``[miscellany] global-ignores``, those patterns replace the built-in set. Without an explicit
    ``config_dir``, system and per-user config files are read from standard locations using the
    supplied environment. On Windows, machine Registry values, machine INI files, user Registry
    values, and user INI files are read in that precedence order; inaccessible Registry sources are
    reported as incomplete. Ignore decisions describe rule matches, not whether paths are already
    versioned. It never prunes ignored directories, because it does not query versioned membership.

    Attributes:
        root: Caller traversal root, bounded to this policy's targets.
        workspace_root: Discovered Subversion working-copy root.
        scheme: Stable ``"subversion"`` identifier.
        config_dir: Optional explicit Subversion runtime config directory.
    """

    @property
    def scheme(self) -> str:
        """Return the stable identifier for Subversion ignore properties."""
        return "subversion"

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        svn_executable: str = "svn",
        config_dir: str | os.PathLike[str] | None = None,
        environment: Mapping[str, str] | None = None,
        timeout: float = 30.0,
        global_ignores: Sequence[str] = (),
        initial_excludes: Sequence[str] = _DEFAULT_INITIAL_EXCLUDES,
    ) -> None:
        """Bind a caller root to a working copy and load its ignore rules.

        When provided, ``config_dir`` is passed to every native command and the
        ``[miscellany] global-ignores`` value in ``config_dir/config`` is read explicitly.
        """
        try:
            self.root = Path(root).expanduser().resolve()
        except (OSError, RuntimeError) as error:
            raise ValueError(f"unable to resolve Subversion policy root: {error}") from error
        if not self.root.is_dir():
            raise ValueError(f"Subversion policy root must be a directory: {self.root}")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        self.svn_executable = svn_executable
        try:
            self.config_dir = (
                Path(config_dir).expanduser().resolve() if config_dir is not None else None
            )
        except (OSError, RuntimeError) as error:
            raise ValueError(f"unable to resolve Subversion config directory: {error}") from error
        self.timeout = timeout
        self._environment = dict(os.environ if environment is None else environment)
        self._global_ignores = tuple(global_ignores)
        self._initial_excludes = tuple(
            path.replace("\\", "/").strip("/") for path in initial_excludes
        )
        marker = _find_working_copy_marker(self.root)
        info = self._run(("info", "--xml", "--depth", "empty", "."), cwd=marker)
        try:
            document = ET.fromstring(info)
        except ET.ParseError as error:
            raise SubversionIgnoreError(
                f"Subversion returned invalid working-copy metadata: {error}",
                operation="info",
                path=str(marker),
            ) from error
        root_node = document.find("./entry/wc-info/wcroot-abspath")
        if root_node is None or not root_node.text:
            raise SubversionIgnoreError(
                "Subversion did not report a working-copy root.",
                operation="info",
                path=str(marker),
            )
        try:
            self.workspace_root = Path(root_node.text).resolve()
        except (OSError, RuntimeError) as error:
            raise SubversionIgnoreError(
                f"Unable to resolve Subversion working-copy root: {error}",
                operation="info",
                path=root_node.text,
            ) from error
        if not self.root.is_relative_to(self.workspace_root):
            raise ValueError("Subversion policy root must be inside its working copy")
        self._load_snapshot()

    def resolve_target(self, target: str | os.PathLike[str]) -> Path:
        """Resolve a target and reject paths outside the caller's root."""
        path = Path(target).expanduser()
        if not path.is_absolute():
            path = self.root / path
        try:
            path = path.resolve()
        except (OSError, RuntimeError) as error:
            raise ValueError(f"unable to resolve Subversion target: {error}") from error
        if not path.is_relative_to(self.root):
            raise ValueError(f"target must be inside policy root: {path}")
        return path

    def explain(self, target: str | os.PathLike[str]) -> IgnoreDecision:
        """Explain one target using a fresh native property snapshot."""
        return self.explain_many((target,))[0]

    def explain_many(self, targets: Iterable[str | os.PathLike[str]]) -> list[IgnoreDecision]:
        """Explain an ordered set of targets against one native property snapshot."""
        materialized = list(targets)
        snapshot = self._load_snapshot()
        nested_markers = self._nested_working_copy_markers(materialized)
        external_roots: frozenset[Path] = (
            self._load_external_roots() if nested_markers else frozenset()
        )
        external_snapshots = tuple(
            self._load_snapshot(workspace_root=root)
            for root in sorted(external_roots)
            if root in nested_markers
            and any(self.resolve_target(target).is_relative_to(root) for target in materialized)
        )
        snapshots = (snapshot, *external_snapshots)
        return [self._explain_with_snapshots(target, snapshots) for target in materialized]

    def iter_explain(
        self, targets: Iterable[str | os.PathLike[str]], *, batch_size: int = 256
    ) -> Iterator[IgnoreDecision]:
        """Lazily explain targets in bounded batches, refreshing properties between batches."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        iterator = iter(targets)
        while batch := list(islice(iterator, batch_size)):
            yield from self.explain_many(batch)

    def trace(self, target: str | os.PathLike[str]) -> IgnoreTrace:
        """Return every matched property/configuration rule in deterministic order."""
        path = self.resolve_target(target)
        snapshot = self._load_snapshot()
        nested_markers = self._nested_working_copy_markers((path,))
        external_roots: frozenset[Path] = (
            self._load_external_roots() if nested_markers else frozenset()
        )
        external_snapshots = tuple(
            self._load_snapshot(workspace_root=root)
            for root in sorted(external_roots)
            if root in nested_markers and path.is_relative_to(root)
        )
        snapshots = (snapshot, *external_snapshots)
        matches = self._matching_rules_from_snapshots(path, snapshots)
        decision_snapshot = max(
            (item for item in snapshots if path.is_relative_to(item.workspace_root)),
            key=lambda item: len(item.workspace_root.parts),
        )
        decision = self._decision(path, matches[0] if matches else None, decision_snapshot)
        trace = tuple(
            IgnoreTraceMatch(
                source=rule.source,
                pattern=rule.pattern,
                line=None,
                ignored=True,
                effective=index == 0,
                scheme=self.scheme,
                property_name=rule.property_name,
                scope=rule.scope,
                reason="matched-rule",
            )
            for index, rule in enumerate(matches)
        )
        return IgnoreTrace(decision=decision, matches=trace, complete=decision.discovery_complete)

    def _nested_working_copy_markers(
        self, targets: Iterable[str | os.PathLike[str] | Path]
    ) -> frozenset[Path]:
        markers: set[Path] = set()
        for target in targets:
            path = self.resolve_target(target)
            for candidate in path.parents:
                if candidate == self.workspace_root:
                    break
                if (candidate / ".svn").is_dir():
                    markers.add(candidate)
        return frozenset(markers)

    def _matching_rules_from_snapshots(
        self, target: Path, snapshots: Sequence[_SvnPropertySnapshot]
    ) -> tuple[_SvnRule, ...]:
        applicable = tuple(
            snapshot for snapshot in snapshots if target.is_relative_to(snapshot.workspace_root)
        )
        deepest_root = max(
            (snapshot.workspace_root for snapshot in applicable), key=lambda root: len(root.parts)
        )
        rules = (
            rule
            for snapshot in applicable
            for rule in self._matching_rules(target, snapshot)
            if snapshot.workspace_root == deepest_root
            or rule.property_name not in (_IGNORE_PROPERTY, _GLOBAL_IGNORE_PROPERTY)
        )
        return tuple(dict.fromkeys(rules))

    def can_prune_ignored_directory(self, target: Path, decision: IgnoreDecision) -> bool:
        """Keep descending because rule matches do not establish versioned membership."""
        del target, decision
        return False

    def should_descend_directory(self, target: Path) -> bool:
        """Descend into native-listed externals but stop at unrelated nested working copies."""
        snapshot = self._load_snapshot()
        return self._should_descend_directory(
            target, self._load_external_roots(), snapshot.excluded_roots
        )

    def _should_descend_directory(
        self,
        target: Path,
        external_roots: frozenset[Path],
        excluded_roots: frozenset[Path],
    ) -> bool:
        if any(target == root or target.is_relative_to(root) for root in excluded_roots):
            return False
        if target == self.workspace_root:
            return True
        if (target / ".svn").is_dir():
            return target in external_roots
        return True

    def _load_external_roots(self) -> frozenset[Path]:
        """Use native status to distinguish SVN externals from nested working copies."""
        output = self._run(
            ("status", "--xml", "--no-ignore", "--depth", "infinity", "."),
            cwd=self.workspace_root,
        )
        try:
            document = ET.fromstring(output)
        except ET.ParseError as error:
            raise SubversionIgnoreError(
                f"Subversion returned invalid status XML: {error}",
                operation="status",
                path=str(self.workspace_root),
            ) from error
        external_roots: set[Path] = set()
        for entry in document.findall("./target/entry"):
            status = entry.find("wc-status")
            if status is None or status.attrib.get("item") != "external":
                continue
            relative = Path(entry.attrib.get("path", ".").replace("\\", "/"))
            if relative.is_absolute() or ".." in relative.parts:
                raise SubversionIgnoreError(
                    "Subversion returned an external path outside the working copy.",
                    operation="status",
                    path=str(relative),
                )
            try:
                external = (self.workspace_root / relative).resolve()
            except (OSError, RuntimeError) as error:
                raise SubversionIgnoreError(
                    f"Unable to resolve Subversion external path: {error}",
                    operation="status",
                    path=str(relative),
                ) from error
            if not external.is_relative_to(self.workspace_root):
                raise SubversionIgnoreError(
                    "Subversion returned an external path outside the working copy.",
                    operation="status",
                    path=str(relative),
                )
            external_roots.add(external)
        return frozenset(external_roots)

    def _open_walk(self) -> _IgnoreWalkSession:
        """Create a stable property snapshot for one filesystem walk."""
        return _SubversionWalkSession(self)

    def _load_snapshot(self, *, workspace_root: Path | None = None) -> _SvnPropertySnapshot:
        """Load versioned properties without reading Subversion's private WC database."""
        query_root = workspace_root or self.workspace_root
        info_output = self._run(("info", "--xml", "--depth", "infinity", "."), cwd=query_root)
        try:
            info_document = ET.fromstring(info_output)
        except ET.ParseError as error:
            raise SubversionIgnoreError(
                f"Subversion returned invalid working-copy depth XML: {error}",
                operation="info",
                path=str(query_root),
            ) from error
        excluded_roots: set[Path] = set()
        for entry in info_document.findall("./entry"):
            wc_info = entry.find("wc-info")
            if wc_info is None or wc_info.findtext("depth") != "exclude":
                continue
            relative = entry.attrib.get("path", ".").replace("\\", "/")
            if relative.startswith("/") or ".." in Path(relative).parts:
                raise SubversionIgnoreError(
                    "Subversion returned an excluded path outside the working copy.",
                    operation="info",
                    path=relative,
                )
            excluded_roots.add(query_root if relative in ("", ".") else query_root / relative)
        output = self._run(
            (
                "proplist",
                "--xml",
                "--verbose",
                "--depth",
                "infinity",
                "--show-inherited-props",
                ".",
            ),
            cwd=query_root,
        )
        try:
            document = ET.fromstring(output)
        except ET.ParseError as error:
            raise SubversionIgnoreError(
                f"Subversion returned invalid property XML: {error}",
                operation="proplist",
                path=str(query_root),
            ) from error
        rules: list[_SvnRule] = []
        for target in document.findall("./target"):
            relative = target.attrib.get("path", ".").replace("\\", "/")
            inherited = target.findall("./inherited_property")
            explicit = target.findall("./property")
            if explicit and (relative.startswith("/") or ".." in Path(relative).parts):
                raise SubversionIgnoreError(
                    "Subversion returned a property path outside the working copy.",
                    operation="proplist",
                    path=relative,
                )
            scope_path = Path() if relative in ("", ".") or inherited else Path(relative)
            scope = scope_path.as_posix() or "."
            for prop in explicit:
                name = prop.attrib.get("name", "")
                if name not in (_IGNORE_PROPERTY, _GLOBAL_IGNORE_PROPERTY):
                    continue
                for pattern in split_svn_property_patterns(prop.text or ""):
                    rules.append(
                        _SvnRule(
                            source=str(query_root / scope_path),
                            scope=scope,
                            property_name=name,
                            pattern=pattern,
                        )
                    )
            for prop in inherited:
                name = prop.attrib.get("name", "")
                if name not in (_GLOBAL_IGNORE_PROPERTY,):
                    continue
                if not relative:
                    raise SubversionIgnoreError(
                        "Subversion returned an inherited property without its source path.",
                        operation="proplist",
                    )
                for pattern in split_svn_property_patterns(prop.text or ""):
                    rules.append(
                        _SvnRule(
                            source=relative,
                            scope=".",
                            property_name=name,
                            pattern=pattern,
                        )
                    )
        runtime_ignores = load_runtime_global_ignores(
            config_dir=self.config_dir,
            environment=self._environment,
            default_patterns=_DEFAULT_GLOBAL_IGNORES,
        )
        for pattern in runtime_ignores.patterns:
            rules.append(
                _SvnRule(
                    source=runtime_ignores.source,
                    scope=".",
                    property_name="global-ignores",
                    pattern=pattern,
                )
            )
        for pattern in self._global_ignores:
            if pattern:
                rules.append(
                    _SvnRule(
                        source="caller-supplied Subversion global-ignores",
                        scope=".",
                        property_name="global-ignores",
                        pattern=pattern,
                    )
                )
        return _SvnPropertySnapshot(
            workspace_root=query_root,
            rules=tuple(rules),
            excluded_roots=frozenset(excluded_roots),
            discovery_complete=runtime_ignores.discovery_complete,
            diagnostics=runtime_ignores.diagnostics,
        )

    def _run(self, arguments: Sequence[str], *, cwd: Path) -> bytes:
        command = [self.svn_executable, "--non-interactive"]
        if self.config_dir is not None:
            command.extend(("--config-dir", str(self.config_dir)))
        command.extend(arguments)
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                env=self._environment,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except OSError as error:
            raise SubversionIgnoreError(
                f"Unable to run Subversion command: {error}",
                operation=arguments[0] if arguments else "execute",
                path=str(cwd),
            ) from error
        except subprocess.TimeoutExpired as error:
            raise SubversionIgnoreError(
                f"Subversion command timed out after {self.timeout:g} seconds.",
                operation=arguments[0] if arguments else "execute",
                path=str(cwd),
            ) from error
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise SubversionIgnoreError(
                detail or f"Subversion command exited with status {result.returncode}.",
                operation=arguments[0] if arguments else "execute",
                path=str(cwd),
            )
        return result.stdout

    def _explain_with_snapshot(
        self, target: str | os.PathLike[str], snapshot: _SvnPropertySnapshot
    ) -> IgnoreDecision:
        return self._explain_with_snapshots(target, (snapshot,))

    def _explain_with_snapshots(
        self,
        target: str | os.PathLike[str],
        snapshots: Sequence[_SvnPropertySnapshot],
    ) -> IgnoreDecision:
        path = self.resolve_target(target)
        applicable = tuple(
            snapshot for snapshot in snapshots if path.is_relative_to(snapshot.workspace_root)
        )
        matches = self._matching_rules_from_snapshots(path, applicable)
        decision_snapshot = max(applicable, key=lambda item: len(item.workspace_root.parts))
        return self._decision(path, matches[0] if matches else None, decision_snapshot)

    def _matching_rules(self, target: Path, snapshot: _SvnPropertySnapshot) -> tuple[_SvnRule, ...]:
        try:
            relative = target.relative_to(snapshot.workspace_root).as_posix()
        except ValueError:
            return ()
        components = () if relative in ("", ".") else tuple(relative.split("/"))
        matched: list[_SvnRule] = []
        for rule in snapshot.rules:
            scope_parts = () if rule.scope == "." else tuple(rule.scope.split("/"))
            for index, basename in enumerate(components):
                parent_parts = components[:index]
                if rule.property_name == _IGNORE_PROPERTY:
                    applies = parent_parts == scope_parts
                else:
                    applies = (
                        len(parent_parts) >= len(scope_parts)
                        and parent_parts[: len(scope_parts)] == scope_parts
                    )
                if applies and matches_svn_glob(basename, rule.pattern):
                    matched.append(rule)
                    break
        caller_relative = target.relative_to(self.root).as_posix()
        if any(_matches_prefix(caller_relative, pattern) for pattern in self._initial_excludes):
            return ()
        return tuple(matched)

    def _decision(
        self, path: Path, rule: _SvnRule | None, snapshot: _SvnPropertySnapshot
    ) -> IgnoreDecision:
        relative = path.relative_to(self.root).as_posix()
        baseline = next(
            (pattern for pattern in self._initial_excludes if _matches_prefix(relative, pattern)),
            None,
        )
        excluded_root = next(
            (root for root in snapshot.excluded_roots if path == root or path.is_relative_to(root)),
            None,
        )
        diagnostics = snapshot.diagnostics
        if excluded_root is not None:
            diagnostics += (
                IgnoreDiagnostic(
                    code="sparse-path-excluded",
                    message=(
                        "The target is under a Subversion path excluded from this sparse "
                        "working copy; its versioned properties are unavailable."
                    ),
                    source=str(excluded_root),
                ),
            )
        discovery_complete = snapshot.discovery_complete and excluded_root is None
        if baseline is not None:
            return IgnoreDecision(
                path=path,
                ignored=True,
                scheme=self.scheme,
                source="Subversion walker baseline",
                pattern=baseline,
                scope=".",
                reason="baseline-exclusion",
                discovery_complete=discovery_complete,
                diagnostics=diagnostics,
            )
        return IgnoreDecision(
            path=path,
            ignored=rule is not None,
            scheme=self.scheme,
            source=rule.source if rule else None,
            pattern=rule.pattern if rule else None,
            property_name=rule.property_name if rule else None,
            scope=rule.scope if rule else None,
            reason="matched-rule" if rule else "no-matching-rule",
            discovery_complete=discovery_complete,
            diagnostics=diagnostics,
        )


def _find_working_copy_marker(root: Path) -> Path:
    for candidate in (root, *root.parents):
        marker = candidate / ".svn"
        if marker.is_dir():
            return candidate
    raise ValueError(f"no Subversion working-copy root found above: {root}")


def _matches_prefix(relative: str, pattern: str) -> bool:
    path_parts = relative.split("/")
    pattern_parts = pattern.strip("/").split("/")
    if pattern_parts == [""]:
        return False
    return any(
        path_parts[index : index + len(pattern_parts)] == pattern_parts
        for index in range(len(path_parts) - len(pattern_parts) + 1)
    )
