"""Portable Mercurial ignore policy using the scheme's own parser and scope rules."""

from __future__ import annotations

# The walk-session protocol is a built-in implementation hook, not a public plugin API.
# pyright: reportPrivateUsage=false
import os
import re
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
from ._ignore_loader import HgIgnoreSources, load_ignore_sources
from ._patterns import HgRule
from .errors import MercurialIgnoreError

_DEFAULT_INITIAL_EXCLUDES = (".hg",)
_UI_IGNORE_SETTING = re.compile(r"^.*:\d+: ui\.ignore(?:\.[^=]+)?=(.*)$")


class _MercurialWalkSession:
    """One walk using a stable snapshot of all discovered Mercurial rules."""

    def __init__(self, policy: MercurialIgnorePolicy) -> None:
        self._policy = policy
        self._sources = policy._load_sources()

    def resolve_target(self, target: str | os.PathLike[str]) -> Path:
        return self._policy.resolve_target(target)

    def walk_top(self, target: str | os.PathLike[str]) -> Path:
        return self.resolve_target(target)

    def explain_many(self, targets: Iterable[str | os.PathLike[str]]) -> list[IgnoreDecision]:
        return [self._policy._explain_with_sources(target, self._sources) for target in targets]

    def should_descend_directory(self, target: Path) -> bool:
        return self._policy.should_descend_directory(target)

    def can_prune_ignored_directory(self, target: Path, decision: IgnoreDecision) -> bool:
        return self._policy.can_prune_ignored_directory(target, decision)


class MercurialIgnorePolicy(IgnorePolicy):
    """Evaluate Mercurial ignore rules without invoking the Mercurial executable.

    The policy discovers the nearest Mercurial workspace above ``root``, loads its root
    ``.hgignore``, and accepts additional ignore files explicitly through ``ignore_files``.
    It implements regexp, unrooted glob, rootglob, include, and subinclude rules. It does not
    inspect Mercurial configuration files by default; supply any configured ``ui.ignore`` files
    explicitly or set ``read_client_config=True`` to ask the Mercurial executable to discover
    configured files. Client-config discovery requires the executable and reports its failures.
    Matching is additive, as in Mercurial, and does not implement Git-style negation.

    Attributes:
        root: Traversal root that bounds policy targets.
        scheme: The stable ``"mercurial"`` ignore dialect identifier.
        workspace_root: Discovered Mercurial repository root, or ``root`` when no repository
            metadata is found above it.
    """

    @property
    def scheme(self) -> str:
        """Return the stable identifier for Mercurial ignore rules."""
        return "mercurial"

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        ignore_files: Sequence[str | os.PathLike[str]] = (),
        read_client_config: bool = False,
        hg_executable: str = "hg",
        environment: Mapping[str, str] | None = None,
        timeout: float = 30.0,
        initial_excludes: Sequence[str] = _DEFAULT_INITIAL_EXCLUDES,
    ) -> None:
        """Create a Mercurial policy with explicit or client-discovered extra sources.

        Args:
            root: Caller-selected traversal root.
            ignore_files: Extra rule files in addition to workspace `.hgignore`.
            read_client_config: Discover configured ``ui.ignore`` files with ``hg config``.
            hg_executable: Mercurial executable used for optional configuration discovery.
            environment: Complete process environment for discovery, or the current environment.
            timeout: Maximum time in seconds for configuration discovery.
            initial_excludes: Baseline paths excluded by the walker.
        """
        try:
            self.root = Path(root).expanduser().resolve()
        except (OSError, RuntimeError) as error:
            raise ValueError(f"unable to resolve Mercurial policy root: {error}") from error
        if not self.root.is_dir():
            raise ValueError(f"Mercurial policy root must be a directory: {self.root}")
        self.workspace_root = _find_workspace_root(self.root)
        self._initial_excludes = tuple(
            path.replace("\\", "/").strip("/") for path in initial_excludes
        )
        self._configured_sources = tuple(Path(path).expanduser() for path in ignore_files)
        if timeout <= 0:
            raise ValueError("Mercurial configuration discovery timeout must be positive")
        if read_client_config:
            self._configured_sources += _discover_ui_ignore_files(
                self.workspace_root,
                hg_executable=hg_executable,
                environment=environment,
                timeout=timeout,
            )
        self._load_sources()

    def resolve_target(self, target: str | os.PathLike[str]) -> Path:
        """Resolve a target and reject paths outside the caller's traversal root."""
        path = Path(target).expanduser()
        if not path.is_absolute():
            path = self.root / path
        try:
            path = path.resolve()
        except (OSError, RuntimeError) as error:
            raise ValueError(f"unable to resolve Mercurial target: {error}") from error
        if not path.is_relative_to(self.root):
            raise ValueError(f"target must be inside policy root: {path}")
        return path

    def explain(self, target: str | os.PathLike[str]) -> IgnoreDecision:
        """Explain whether a target matches a Mercurial ignore source."""
        return self._explain_with_sources(target, self._load_sources())

    def trace(self, target: str | os.PathLike[str]) -> IgnoreTrace:
        """Return all matching rules in source order, with the first match effective."""
        path = self.resolve_target(target)
        sources = self._load_sources()
        matches = self._matching_rules(path, sources)
        decision = self._decision(path, matches[0] if matches else None, sources)
        if decision.reason == "baseline-exclusion":
            trace = (
                IgnoreTraceMatch(
                    source=decision.source or "Mercurial walker baseline",
                    pattern=decision.pattern or "",
                    line=None,
                    ignored=True,
                    effective=True,
                    scheme=self.scheme,
                    scope=".",
                    reason="baseline-exclusion",
                ),
            )
            return IgnoreTrace(decision, trace, complete=sources.complete)
        trace = tuple(
            IgnoreTraceMatch(
                source=rule.source,
                pattern=rule.pattern,
                line=rule.line,
                ignored=True,
                effective=index == 0,
                scheme=self.scheme,
                scope=_relative_scope(self.workspace_root, rule.matcher_root),
                reason="matched-rule",
            )
            for index, rule in enumerate(matches)
        )
        return IgnoreTrace(decision, trace, complete=sources.complete)

    def iter_explain(
        self,
        targets: Iterable[str | os.PathLike[str]],
        *,
        batch_size: int = 256,
    ) -> Iterator[IgnoreDecision]:
        """Lazily explain targets in input order."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        del batch_size
        sources = self._load_sources()
        for target in targets:
            yield self._explain_with_sources(target, sources)

    def can_prune_ignored_directory(self, target: Path, decision: IgnoreDecision) -> bool:
        """Prune ignored subtrees because Mercurial ignore rules have no negation."""
        del target
        return decision.ignored

    def should_descend_directory(self, target: Path) -> bool:
        """Stop at Mercurial metadata and nested workspace boundaries."""
        metadata_root = self.workspace_root / ".hg"
        if target == metadata_root or target.is_relative_to(metadata_root):
            return False
        return target == self.workspace_root or not (target / ".hg").exists()

    def _load_sources(self) -> HgIgnoreSources:
        """Refresh source contents for one query or a lazy query batch."""
        return load_ignore_sources(self.workspace_root, self._configured_sources)

    def _explain_with_sources(
        self, target: str | os.PathLike[str], sources: HgIgnoreSources
    ) -> IgnoreDecision:
        """Explain one target against an already loaded source snapshot."""
        path = self.resolve_target(target)
        matches = self._matching_rules(path, sources)
        return self._decision(path, matches[0] if matches else None, sources)

    def _open_walk(self) -> _IgnoreWalkSession:
        """Create a stable source snapshot for one directory walk."""
        return _MercurialWalkSession(self)

    def _matching_rules(self, target: Path, sources: HgIgnoreSources) -> tuple[HgRule, ...]:
        baseline_path = target.relative_to(self.root).as_posix()
        if any(_matches_prefix(baseline_path, pattern) for pattern in self._initial_excludes):
            return ()
        matches: list[HgRule] = []
        for rule in sources.rules:
            try:
                scoped = target.relative_to(rule.matcher_root).as_posix()
            except ValueError:
                continue
            if any(rule.matches(candidate) for candidate in _path_prefixes(scoped)):
                matches.append(rule)
        return tuple(matches)

    def _decision(
        self, path: Path, rule: HgRule | None, sources: HgIgnoreSources
    ) -> IgnoreDecision:
        relative = path.relative_to(self.root).as_posix()
        baseline = next(
            (pattern for pattern in self._initial_excludes if _matches_prefix(relative, pattern)),
            None,
        )
        if baseline is not None:
            source = "Mercurial walker baseline"
            return IgnoreDecision(
                path=path,
                ignored=True,
                scheme=self.scheme,
                source=source,
                pattern=baseline,
                scope=".",
                reason="baseline-exclusion",
                discovery_complete=sources.complete,
                diagnostics=sources.diagnostics,
            )
        return IgnoreDecision(
            path=path,
            ignored=rule is not None,
            scheme=self.scheme,
            source=rule.source if rule is not None else None,
            pattern=rule.pattern if rule is not None else None,
            line=rule.line if rule is not None else None,
            scope=_relative_scope(self.workspace_root, rule.matcher_root) if rule else None,
            reason="matched-rule" if rule is not None else "no-matching-rule",
            discovery_complete=sources.complete,
            diagnostics=sources.diagnostics,
        )


def _find_workspace_root(root: Path) -> Path:
    for candidate in (root, *root.parents):
        if (candidate / ".hg").exists():
            return candidate
    return root


def _path_prefixes(relative: str) -> Iterator[str]:
    if relative in ("", "."):
        return
    parts = relative.split("/")
    for index in range(1, len(parts) + 1):
        yield "/".join(parts[:index])


def _matches_prefix(relative: str, pattern: str) -> bool:
    path_parts = relative.split("/")
    pattern_parts = pattern.strip("/").split("/")
    if pattern_parts == [""]:
        return False
    return any(
        path_parts[index : index + len(pattern_parts)] == pattern_parts
        for index in range(len(path_parts) - len(pattern_parts) + 1)
    )


def _relative_scope(workspace_root: Path, matcher_root: Path) -> str:
    try:
        relative = matcher_root.relative_to(workspace_root).as_posix()
    except ValueError:
        return str(matcher_root)
    return relative or "."


def _discover_ui_ignore_files(
    workspace_root: Path,
    *,
    hg_executable: str,
    environment: Mapping[str, str] | None,
    timeout: float,
) -> tuple[Path, ...]:
    """Ask Mercurial for effective ``ui.ignore`` paths in native config order."""
    env = dict(os.environ if environment is None else environment)
    env["HGPLAIN"] = "1"
    env["LC_ALL"] = "C"
    try:
        result = subprocess.run(
            [hg_executable, "config", "--debug", "ui"],
            cwd=workspace_root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MercurialIgnoreError(
            f"Unable to discover Mercurial ui.ignore configuration: {error}",
            operation="config",
        ) from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown Mercurial error"
        raise MercurialIgnoreError(
            f"Mercurial ui.ignore configuration discovery failed: {detail}",
            operation="config",
        )
    sources: list[Path] = []
    for line in result.stdout.splitlines():
        match = _UI_IGNORE_SETTING.match(line)
        if match is None:
            continue
        value = match.group(1).strip()
        if value:
            path = _expand_configured_path(value, env)
            sources.append(path if path.is_absolute() else workspace_root / path)
    return tuple(sources)


def _expand_configured_path(value: str, environment: Mapping[str, str]) -> Path:
    """Expand Mercurial's home-relative paths using the discovery environment."""
    if value == "~" or value.startswith(("~/", "~\\")):
        home = environment.get("HOME") or environment.get("USERPROFILE")
        if home:
            return Path(home) / value[2:] if value != "~" else Path(home)
    return Path(value).expanduser()
