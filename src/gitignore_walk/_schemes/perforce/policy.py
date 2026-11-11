"""Portable evaluation of P4IGNORE files for a caller-selected workspace root."""

from __future__ import annotations

# Private walk-session hooks are shared by the built-in policies.
# pyright: reportPrivateUsage=false
import os
import re
import stat
import subprocess
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import islice
from math import isfinite
from pathlib import Path
from typing import Literal

from ..._policy import (
    IgnoreDecision,
    IgnorePolicy,
    IgnoreTrace,
    IgnoreTraceMatch,
    _IgnoreWalkSession,
)
from .errors import PerforceIgnoreError

_DEFAULT_IGNORE_FILES = (".p4ignore", "p4ignore.txt")


def _tagged_records(output: str) -> tuple[dict[str, str], ...]:
    """Parse Perforce tagged output into records separated by ``depotFile`` fields."""
    records: list[dict[str, str]] = []
    record: dict[str, str] = {}
    for line in output.splitlines():
        if not line.startswith("... "):
            continue
        name, separator, value = line[4:].partition(" ")
        if not separator:
            continue
        if name == "depotFile" and record:
            records.append(record)
            record = {}
        record[name] = value
    if record:
        records.append(record)
    return tuple(records)


def _membership_key(path: Path) -> str:
    """Normalize a local P4 path without following symbolic links."""
    return os.path.normcase(os.path.abspath(path))


@dataclass(frozen=True, slots=True)
class _PerforceRule:
    """One compiled P4IGNORE rule and its source-relative matching contract."""

    source: str
    scope: Path
    pattern: str
    line: int
    expression: re.Pattern[str]
    negated: bool
    basename_only: bool
    directory_only: bool
    source_order: int

    def matches(self, target: Path) -> bool:
        """Return whether this rule matches a target or one of its ancestor directories."""
        try:
            relative = target.relative_to(self.scope).as_posix()
        except ValueError:
            return False
        if relative in ("", "."):
            return False
        parts = relative.split("/")
        for index in range(1, len(parts) + 1):
            candidate = "/".join(parts[:index])
            is_directory = index < len(parts) or target.is_dir()
            if self.directory_only and not is_directory:
                continue
            if self.basename_only:
                candidate = parts[index - 1]
            if self.expression.fullmatch(candidate):
                return True
        return False


class _PerforceWalkSession:
    """Cache discovered source contents for one filesystem walk."""

    def __init__(self, policy: PerforceIgnorePolicy) -> None:
        self._policy = policy
        self._source_rules: dict[Path, tuple[_PerforceRule, ...]] = {}
        self._checked_directories: set[tuple[Path, tuple[str, ...], Path]] = set()
        self._configurations: dict[Path, tuple[tuple[str, ...], Path, str | None]] = {}
        self._view_membership: dict[Path, bool] = {}
        self._membership = policy._load_membership() if policy.membership_aware else None

    def resolve_target(self, target: str | os.PathLike[str]) -> Path:
        return self._policy.resolve_target(target)

    def walk_top(self, target: str | os.PathLike[str]) -> Path:
        return self.resolve_target(target)

    def explain_many(self, targets: Iterable[str | os.PathLike[str]]) -> list[IgnoreDecision]:
        requested = list(targets)
        paths = [self.resolve_target(target) for target in requested]
        membership_paths = (
            [self._policy._lexical_target(target) for target in requested]
            if self._membership is not None
            else [None] * len(paths)
        )
        p4config_by_path: dict[Path, str | None] = {}
        for path in paths:
            p4config_by_path[path] = self._policy._discover_ancestors(
                path,
                self._checked_directories,
                self._source_rules,
                self._configurations,
            )
        rules = self._ordered_rules()
        return [
            self._policy._explain_with_rules(
                path,
                rules,
                p4config_by_path[path],
                self._membership,
                membership_path,
            )
            for path, membership_path in zip(paths, membership_paths, strict=True)
        ]

    def _ordered_rules(self) -> tuple[_PerforceRule, ...]:
        return self._policy._ordered_rules(self._source_rules)

    def should_descend_directory(self, target: Path) -> bool:
        return self._policy.should_descend_directory(target)

    def should_select_file(self, target: Path) -> bool:
        return self._policy.should_select_file(target) and self._policy._in_client_view(
            target, self._view_membership
        )

    def can_prune_ignored_directory(self, target: Path, decision: IgnoreDecision) -> bool:
        return self._policy.can_prune_ignored_directory(target, decision)


class PerforceIgnorePolicy(IgnorePolicy):
    """Evaluate P4IGNORE rules without requiring a P4 client or server.

    ``root`` is the traversal boundary supplied by the caller. The evaluator discovers configured
    ignore files in each target's ancestor directories, applies source files from shallow to deep,
    and evaluates rules in file-list and line order. The last matching rule wins, so a later
    exception may re-include a child. `*` matches within one path component; `**` may cross
    separators. A trailing slash matches directories and their descendants. Ignored directories
    are never pruned because P4IGNORE exceptions can select descendants.

    If ``P4IGNORE`` is absent, the policy checks `.p4ignore` followed by `p4ignore.txt` in each
    directory. An explicit value is parsed as Perforce's semicolon-delimited source list and
    replaces those default names. Set ``read_client_config=True`` to query ``p4 set`` for the
    effective P4CONFIG-derived setting at each target; explicit ``p4ignore`` still takes
    precedence. Set ``discover_client_workspace=True`` to query a connected P4 client with
    ``p4 -ztag info`` for the client root; this does not widen the caller's traversal boundary.
    Set ``client_view_aware=True`` to have walks omit files outside that client's view. This
    requires ``discover_client_workspace=True`` and does not change ignore decisions or versioned
    membership. Directories remain traversable because an unmapped directory can contain mapped
    descendants.
    Set ``membership_aware=True`` to query ``p4 have`` and ``p4 opened`` once per batch or walk.
    Submitted and opened files are versioned, present files absent from both lists are unversioned,
    and directories, missing unlisted paths, and dangling symlinks remain unknown. Membership
    queries require a configured connected P4 client and stay independent from ignore rules.

    Attributes:
        root: Caller-selected traversal boundary and target bound.
        scheme: Stable ``"perforce"`` identifier.
        workspace_root: Native client root when discovery is enabled, otherwise the caller root.
        membership_aware: Whether native have-list and opened-file membership is queried.
        p4_executable: P4 client used for optional configuration and membership queries.
    """

    @property
    def scheme(self) -> str:
        """Return the stable identifier for Perforce ignore rules."""
        return "perforce"

    def _source_order_key(self, source: Path) -> tuple[int, str]:
        """Sort sources by workspace depth and directory path."""
        try:
            relative_parent = source.parent.relative_to(self.workspace_root)
        except ValueError:
            try:
                relative_parent = Path(os.path.relpath(source.parent, self.workspace_root))
            except ValueError:
                return (-1, source.parent.as_posix())
            depth = 0
            for part in relative_parent.parts:
                if part != "..":
                    break
                depth -= 1
            return (depth, relative_parent.as_posix())
        return (
            len(relative_parent.parts),
            relative_parent.as_posix(),
        )

    def _scope_label(self, scope: Path) -> str | None:
        """Return a workspace-relative scope, including ``..`` for parent sources."""
        try:
            relative = scope.relative_to(self.workspace_root)
        except ValueError:
            try:
                return Path(os.path.relpath(scope, self.workspace_root)).as_posix()
            except ValueError:
                return None
        return relative.as_posix() or "."

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        environment: Mapping[str, str] | None = None,
        p4ignore: str | None = None,
        read_client_config: bool = False,
        discover_client_workspace: bool = False,
        client_view_aware: bool = False,
        membership_aware: bool = False,
        p4_executable: str = "p4",
        timeout: float = 30.0,
        initial_excludes: Sequence[str] = (),
    ) -> None:
        """Bind caller bounds, optionally discover the client root, and load P4IGNORE selection."""
        try:
            self.root = Path(root).expanduser().resolve()
        except (OSError, RuntimeError) as error:
            raise ValueError(f"unable to resolve Perforce policy root: {error}") from error
        if not self.root.is_dir():
            raise ValueError(f"Perforce policy root must be a directory: {self.root}")
        self._environment = dict(os.environ if environment is None else environment)
        if not isfinite(timeout) or timeout <= 0:
            raise ValueError("Perforce query timeout must be finite and positive")
        self._p4_executable = p4_executable
        self._timeout = timeout
        self._discover_client_workspace = discover_client_workspace
        self.workspace_root = (
            self._discover_workspace_root() if discover_client_workspace else self.root
        )
        if not self.root.is_relative_to(self.workspace_root):
            raise PerforceIgnoreError(
                f"caller root {self.root} is outside Perforce client root {self.workspace_root}",
                operation="workspace",
            )
        self._read_client_config = read_client_config and p4ignore is None
        if client_view_aware and not discover_client_workspace:
            raise ValueError("client_view_aware requires discover_client_workspace=True")
        self._client_view_aware = client_view_aware
        self.membership_aware = membership_aware
        selected = p4ignore if p4ignore is not None else self._environment.get("P4IGNORE")
        self._ignore_files = (
            _DEFAULT_IGNORE_FILES
            if selected is None
            else tuple(item for item in selected.split(";") if item)
        )
        self._initial_excludes = tuple(
            item.replace("\\", "/").strip("/") for item in initial_excludes
        )

    def _discover_workspace_root(self) -> Path:
        """Return the native client root containing the caller root."""
        try:
            result = subprocess.run(
                [self._p4_executable, "-ztag", "info"],
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
            raise PerforceIgnoreError(
                f"Unable to discover Perforce client workspace: {error}",
                operation="workspace",
            ) from error
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown P4 error"
            raise PerforceIgnoreError(
                f"Perforce client workspace discovery failed: {detail}",
                operation="workspace",
            )

        client_root: str | None = None
        for line in result.stdout.splitlines():
            fields = line.split(None, 2)
            if len(fields) == 3 and fields[:2] == ["...", "clientRoot"]:
                client_root = fields[2]
                break
        if not client_root:
            raise PerforceIgnoreError(
                "Perforce client workspace discovery returned no tagged clientRoot",
                operation="workspace",
            )
        try:
            workspace_root = Path(client_root).expanduser().resolve()
        except (OSError, RuntimeError) as error:
            raise PerforceIgnoreError(
                f"Unable to resolve Perforce client root {client_root!r}: {error}",
                operation="workspace",
            ) from error
        if not workspace_root.is_dir():
            raise PerforceIgnoreError(
                f"Perforce client root is not a directory: {workspace_root}",
                operation="workspace",
            )
        return workspace_root

    def resolve_target(self, target: str | os.PathLike[str]) -> Path:
        """Resolve a target and reject paths outside the caller-selected workspace root."""
        path = Path(target).expanduser()
        if not path.is_absolute():
            path = self.root / path
        try:
            path = path.resolve()
        except (OSError, RuntimeError) as error:
            raise ValueError(f"unable to resolve Perforce target: {error}") from error
        if not path.is_relative_to(self.root):
            raise ValueError(f"target must be inside policy root: {path}")
        return path

    def explain(self, target: str | os.PathLike[str]) -> IgnoreDecision:
        """Explain whether one target matches the selected P4IGNORE sources."""
        path = self.resolve_target(target)
        membership = self._load_membership() if self.membership_aware else None
        membership_path = self._lexical_target(target) if membership is not None else None
        rules, p4config_name = self._load_rules(path, {}, set())
        return self._explain_with_rules(path, rules, p4config_name, membership, membership_path)

    def explain_many(self, targets: Iterable[str | os.PathLike[str]]) -> list[IgnoreDecision]:
        """Explain an ordered target batch using one source snapshot."""
        requested = list(targets)
        paths = [self.resolve_target(target) for target in requested]
        membership = self._load_membership() if self.membership_aware else None
        membership_paths = (
            [self._lexical_target(target) for target in requested]
            if membership is not None
            else [None] * len(paths)
        )
        rules_by_source: dict[Path, tuple[_PerforceRule, ...]] = {}
        checked: set[tuple[Path, tuple[str, ...], Path]] = set()
        configurations: dict[Path, tuple[tuple[str, ...], Path, str | None]] = {}
        p4config_by_path: dict[Path, str | None] = {}
        for path in paths:
            p4config_by_path[path] = self._discover_ancestors(
                path, checked, rules_by_source, configurations
            )
        rules = self._ordered_rules(rules_by_source)
        return [
            self._explain_with_rules(
                path,
                rules,
                p4config_by_path[path],
                membership,
                membership_path,
            )
            for path, membership_path in zip(paths, membership_paths, strict=True)
        ]

    def iter_explain(
        self,
        targets: Iterable[str | os.PathLike[str]],
        *,
        batch_size: int = 256,
    ) -> Iterator[IgnoreDecision]:
        """Lazily explain targets in batches with a fresh source snapshot per batch."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        iterator = iter(targets)
        while batch := list(islice(iterator, batch_size)):
            yield from self.explain_many(batch)

    def trace(self, target: str | os.PathLike[str]) -> IgnoreTrace:
        """Return every matching rule in source order and identify the last as effective."""
        path = self.resolve_target(target)
        membership = self._load_membership() if self.membership_aware else None
        membership_path = self._lexical_target(target) if membership is not None else None
        rules, p4config_name = self._load_rules(path, {}, set())
        baseline = self._baseline_match(path, p4config_name=p4config_name)
        matching = tuple(rule for rule in rules if rule.matches(path))
        effective_rule = self._effective_rule(path, rules)
        decision = self._decision(
            path, effective_rule, baseline, p4config_name, membership, membership_path
        )
        trace = tuple(
            IgnoreTraceMatch(
                source=rule.source,
                pattern=rule.pattern,
                line=rule.line,
                ignored=not rule.negated,
                effective=rule is effective_rule,
                scheme=self.scheme,
                scope=self._scope_label(rule.scope),
                reason="matched-rule" if not rule.negated else "exception-rule",
            )
            for rule in matching
        )
        return IgnoreTrace(decision=decision, matches=trace, complete=True)

    def can_prune_ignored_directory(self, target: Path, decision: IgnoreDecision) -> bool:
        """Keep ignored directories traversable because later child rules can re-include paths."""
        del target, decision
        return False

    def should_select_file(self, target: Path) -> bool:
        """Keep regular files in scope unless client-view filtering is enabled."""
        del target
        return True

    def should_descend_directory(self, target: Path) -> bool:
        """Keep directories traversable because unmapped parents can have mapped descendants."""
        del target
        return True

    def _in_client_view(self, target: Path, cache: dict[Path, bool]) -> bool:
        """Return a native P4 mapping result, preserving unknown mappings conservatively."""
        if not self._client_view_aware:
            return True
        path = self.resolve_target(target)
        if path not in cache:
            try:
                result = subprocess.run(
                    [self._p4_executable, "-ztag", "where", str(path)],
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
                raise PerforceIgnoreError(
                    f"Unable to discover Perforce client view for {path}: {error}",
                    operation="client-view",
                    source=str(path),
                ) from error
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip() or "unknown P4 error"
                raise PerforceIgnoreError(
                    f"Perforce client-view query failed: {detail}",
                    operation="client-view",
                    source=str(path),
                )
            elif "file(s) not in client view." in result.stderr:
                in_view = False
            else:
                records: list[dict[str, str]] = []
                for block in result.stdout.strip().split("\n\n"):
                    record: dict[str, str] = {}
                    for line in block.splitlines():
                        if not line.startswith("... "):
                            record.clear()
                            break
                        name, separator, value = line[4:].partition(" ")
                        if separator:
                            record[name] = value
                    if record:
                        records.append(record)
                if len(records) == 1 and "unmap" in records[0]:
                    in_view = False
                elif len(records) == 1 and {"depotFile", "clientFile", "path"}.issubset(records[0]):
                    in_view = True
                else:
                    # Overlays and unknown tagged records need an explicit precedence contract.
                    in_view = True
            cache[path] = in_view
        return cache[path]

    def _open_walk(self) -> _IgnoreWalkSession:
        """Create a walk session that caches ignore files as their directories are visited."""
        return _PerforceWalkSession(self)

    def _lexical_target(self, target: str | os.PathLike[str]) -> Path:
        """Return an absolute target path without resolving symbolic links."""
        path = Path(target).expanduser()
        if not path.is_absolute():
            path = self.root / path
        return Path(os.path.abspath(path))

    def _load_membership(self) -> frozenset[str]:
        """Capture submitted and opened local paths from the selected Perforce client."""
        cwd = self.workspace_root if self._discover_client_workspace else self.root
        have = self._run_membership_query(("-ztag", "have"), cwd=cwd)
        opened = self._run_membership_query(("-ztag", "opened"), cwd=cwd)
        local_paths: set[str] = set()
        for record in _tagged_records(have.stdout):
            if local_path := record.get("path"):
                local_paths.add(_membership_key(Path(local_path)))

        client_files = [
            record["clientFile"]
            for record in _tagged_records(opened.stdout)
            if record.get("clientFile")
        ]
        if client_files:
            where = self._run_membership_query(("-ztag", "where", *client_files), cwd=cwd)
            for record in _tagged_records(where.stdout):
                if local_path := record.get("path"):
                    local_paths.add(_membership_key(Path(local_path)))
        return frozenset(local_paths)

    def _run_membership_query(
        self, arguments: Sequence[str], *, cwd: Path
    ) -> subprocess.CompletedProcess[str]:
        operation = arguments[1] if len(arguments) > 1 else "membership"
        try:
            result = subprocess.run(
                [self._p4_executable, *arguments],
                cwd=cwd,
                env=self._environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise PerforceIgnoreError(
                f"Unable to discover Perforce membership with {operation}: {error}",
                operation="membership",
            ) from error
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown P4 error"
            raise PerforceIgnoreError(
                f"Perforce membership query failed for {operation}: {detail}",
                operation="membership",
            )
        return result

    def _load_rules(
        self,
        target: Path,
        rules_by_source: dict[Path, tuple[_PerforceRule, ...]],
        checked_directories: set[tuple[Path, tuple[str, ...], Path]],
    ) -> tuple[tuple[_PerforceRule, ...], str | None]:
        configurations: dict[Path, tuple[tuple[str, ...], Path, str | None]] = {}
        p4config_name = self._discover_ancestors(
            target, checked_directories, rules_by_source, configurations
        )
        return self._ordered_rules(rules_by_source), p4config_name

    def _discover_ancestors(
        self,
        target: Path,
        checked_directories: set[tuple[Path, tuple[str, ...], Path]],
        rules_by_source: dict[Path, tuple[_PerforceRule, ...]],
        configurations: dict[Path, tuple[tuple[str, ...], Path, str | None]] | None = None,
    ) -> str | None:
        try:
            relative_parent = target.parent.relative_to(self.root)
        except ValueError:
            return None
        if configurations is None:
            configurations = {}
        if target.parent not in configurations:
            configurations[target.parent] = self._ignore_configuration(target.parent)
        ignore_files, config_root, p4config_name = configurations[target.parent]
        try:
            relative_parent = target.parent.relative_to(config_root)
        except ValueError:
            return p4config_name
        directories = [config_root]
        current = config_root
        for part in relative_parent.parts:
            current = current / part
            directories.append(current)
        for directory in directories:
            check_key = (directory, ignore_files, config_root)
            if check_key in checked_directories:
                continue
            checked_directories.add(check_key)
            for source_order, name in enumerate(ignore_files):
                source = Path(name).expanduser()
                if source.is_absolute():
                    scope = config_root
                else:
                    source = directory / source
                    scope = source.parent
                if source in rules_by_source or not source.is_file():
                    continue
                rules_by_source[source] = self._read_rules(source, scope, source_order)
        return p4config_name

    def _ignore_configuration(self, directory: Path) -> tuple[tuple[str, ...], Path, str | None]:
        """Return effective P4IGNORE source names and the scope of their P4CONFIG value."""
        if not self._read_client_config:
            return (
                self._ignore_files,
                self.workspace_root,
                self._environment.get("P4CONFIG") or None,
            )
        try:
            result = subprocess.run(
                [self._p4_executable, "set"],
                cwd=directory,
                env=self._environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise PerforceIgnoreError(
                f"Unable to discover Perforce configuration: {error}",
                operation="config",
            ) from error
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown P4 error"
            raise PerforceIgnoreError(
                f"Perforce configuration discovery failed: {detail}", operation="config"
            )

        p4ignore: str | None = None
        p4config_name: str | None = None
        source_path: Path | None = None
        for line in result.stdout.splitlines():
            name, separator, value = line.partition("=")
            if not separator:
                continue
            source = re.search(r" \(config '([^']+)'(?:,.*)?\s*\)\s*$", value)
            if name == "P4CONFIG":
                if source is not None:
                    value = value[: source.start()]
                else:
                    value = re.sub(r" \((?:enviro|set|set -s)\)\s*$", "", value)
                p4config_name = value.strip() or None
            if name == "P4IGNORE":
                if source is not None:
                    value = value[: source.start()]
                    source_path = Path(source.group(1))
                else:
                    value = re.sub(r" \((?:enviro|set|set -s)\)\s*$", "", value)
                p4ignore = value
                break
        if p4ignore is None:
            return _DEFAULT_IGNORE_FILES, self.workspace_root, p4config_name
        scope = source_path.parent if source_path is not None else self.workspace_root
        names = tuple(item for item in p4ignore.split(";") if item)
        return names, scope, p4config_name

    def _read_rules(
        self, source: Path, scope: Path, source_order: int
    ) -> tuple[_PerforceRule, ...]:
        try:
            contents = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise PerforceIgnoreError(
                f"Unable to read Perforce ignore source: {error}",
                operation="read",
                source=str(source),
            ) from error
        rules: list[_PerforceRule] = []
        for line_number, raw_line in enumerate(contents.splitlines(), start=1):
            # P4 trims ASCII spaces around a rule before checking comments and
            # matching. Tabs remain part of the rule text.
            pattern = raw_line.strip(" ")
            if not pattern:
                continue
            if pattern.startswith("#"):
                continue
            pattern = pattern[1:] if pattern.startswith(r"\#") else pattern
            if not pattern:
                continue
            negated = pattern.startswith("!")
            if negated:
                pattern = pattern[1:]
            if not pattern:
                continue
            directory_only = pattern.endswith("/")
            pattern = pattern.rstrip("/")
            root_anchored = pattern.startswith("/")
            if root_anchored:
                pattern = pattern[1:]
            basename_only = not root_anchored and "/" not in pattern and "**" not in pattern
            try:
                expression = re.compile(_glob_to_regex(pattern))
            except re.error as error:
                raise PerforceIgnoreError(
                    f"Invalid Perforce pattern at {source}:{line_number}: {error}",
                    operation="parse",
                    source=str(source),
                    line=line_number,
                ) from error
            rules.append(
                _PerforceRule(
                    source=str(source),
                    scope=scope,
                    pattern=raw_line,
                    line=line_number,
                    expression=expression,
                    negated=negated,
                    basename_only=basename_only,
                    directory_only=directory_only,
                    source_order=source_order,
                )
            )
        return tuple(rules)

    def _ordered_rules(
        self, rules_by_source: dict[Path, tuple[_PerforceRule, ...]]
    ) -> tuple[_PerforceRule, ...]:
        return tuple(
            rule
            for source in sorted(
                rules_by_source,
                key=lambda path: (
                    self._source_order_key(path),
                    rules_by_source[path][0].source_order if rules_by_source[path] else 0,
                ),
            )
            for rule in rules_by_source[source]
        )

    def _baseline_match(self, path: Path, *, p4config_name: str | None = None) -> str | None:
        relative = path.relative_to(self.root).as_posix()
        parts = relative.split("/")
        if self._contains_component(path, ".p4root"):
            return ".p4root"
        if p4config_name is not None and self._contains_component(path, p4config_name):
            return p4config_name
        for excluded in self._initial_excludes:
            if any(part == excluded for part in parts):
                return excluded
        return None

    def _contains_component(self, path: Path, name: str) -> bool:
        """Match a path component using the filesystem's case behavior when it exists."""
        candidate = path
        while candidate != self.workspace_root:
            if candidate.name == name:
                return True
            try:
                if candidate.exists() and candidate.samefile(candidate.with_name(name)):
                    return True
            except OSError:
                pass
            candidate = candidate.parent
        return False

    def _explain_with_rules(
        self,
        path: Path,
        rules: tuple[_PerforceRule, ...],
        p4config_name: str | None = None,
        membership_paths: frozenset[str] | None = None,
        membership_path: Path | None = None,
    ) -> IgnoreDecision:
        effective = self._effective_rule(path, rules)
        return self._decision(
            path,
            effective,
            self._baseline_match(path, p4config_name=p4config_name),
            p4config_name,
            membership_paths,
            membership_path,
        )

    @staticmethod
    def _effective_rule(path: Path, rules: tuple[_PerforceRule, ...]) -> _PerforceRule | None:
        """Choose the closest source, then first configured file, then last matching line."""
        matches = [rule for rule in rules if rule.matches(path)]
        if not matches:
            return None
        return max(
            matches,
            key=lambda rule: (
                len(rule.scope.parts),
                -rule.source_order,
                rule.line,
            ),
        )

    def _decision(
        self,
        path: Path,
        rule: _PerforceRule | None,
        baseline: str | None,
        p4config_name: str | None,
        membership_paths: frozenset[str] | None = None,
        membership_path: Path | None = None,
    ) -> IgnoreDecision:
        membership: Literal["versioned", "unversioned"] | None = None
        if membership_paths is not None and membership_path is not None:
            if _membership_key(membership_path) in membership_paths:
                membership = "versioned"
            else:
                try:
                    mode = membership_path.lstat().st_mode
                except OSError:
                    pass
                else:
                    if stat.S_ISDIR(mode) or (stat.S_ISLNK(mode) and not membership_path.exists()):
                        pass
                    else:
                        membership = "unversioned"
        if baseline is not None:
            built_in = baseline in {".p4root", p4config_name}
            return IgnoreDecision(
                path=path,
                ignored=True,
                scheme=self.scheme,
                source="Perforce built-in defaults" if built_in else "Perforce walker baseline",
                pattern=baseline,
                scope=".",
                reason="built-in-exclusion" if built_in else "baseline-exclusion",
                discovery_complete=True,
                membership=membership,
            )
        ignored = rule is not None and not rule.negated
        return IgnoreDecision(
            path=path,
            ignored=ignored,
            scheme=self.scheme,
            source=rule.source if rule else None,
            pattern=rule.pattern if rule else None,
            line=rule.line if rule else None,
            scope=self._scope_label(rule.scope) if rule else None,
            reason=("matched-rule" if ignored else "exception-rule")
            if rule
            else "no-matching-rule",
            discovery_complete=True,
            membership=membership,
        )


def _glob_to_regex(pattern: str) -> str:
    """Compile the captured P4IGNORE `*` and `**` wildcards to a full-path regex."""
    pieces = ["^"]
    index = 0
    while index < len(pattern):
        if pattern.startswith("**", index):
            pieces.append(".*")
            index += 2
        elif pattern[index] == "*":
            pieces.append("[^/]*")
            index += 1
        else:
            pieces.append(re.escape(pattern[index]))
            index += 1
    pieces.append("$")
    return "".join(pieces)
