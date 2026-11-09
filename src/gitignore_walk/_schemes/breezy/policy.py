"""Portable evaluation of Breezy ignore rules with native default-rule discovery."""

from __future__ import annotations

# Private walk-session hooks are shared by the built-in policies.
# pyright: reportPrivateUsage=false
import fnmatch
import math
import os
import re
import subprocess
import tempfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..._policy import (
    IgnoreDecision,
    IgnoreDiagnostic,
    IgnorePolicy,
    IgnoreTrace,
    IgnoreTraceMatch,
    _IgnoreWalkSession,
)
from .errors import BreezyIgnoreError

_WORKSPACE_MARKER = ".bzr"
_NAMED_CAPTURE = re.compile(r"\(\?P<([A-Za-z_][A-Za-z0-9_]*)>")
_GLOBAL_INLINE_FLAGS = re.compile(r"(?<!\\)(?:\\\\)*\(\?[aiLmsux]+\)")
_SEPARATOR_RUN = re.compile(r"[\\/]+")


@dataclass(frozen=True, slots=True)
class _BreezyRule:
    """One compiled Breezy rule with source provenance and priority class."""

    source: str
    pattern: str
    line: int
    priority: str
    regex: bool
    root_only: bool
    expression: re.Pattern[str]
    diagnostic: IgnoreDiagnostic | None = None

    def matches(self, relative_path: str) -> bool:
        """Return whether the rule matches one workspace-relative path."""
        if self.root_only and "/" in relative_path:
            return False
        if self.regex or "/" in self.pattern:
            candidate = relative_path
        else:
            candidate = relative_path.rsplit("/", 1)[-1]
        return self.expression.match(candidate) is not None


@dataclass(frozen=True, slots=True)
class _BreezySnapshot:
    """Compiled default, global, and checkout-local rules for one query batch."""

    rules: tuple[_BreezyRule, ...]


class _BreezyWalkSession:
    """Use one stable rule snapshot and exception-aware pruning for one walk."""

    def __init__(self, policy: BreezyIgnorePolicy) -> None:
        self._policy = policy
        self._snapshot = policy._load_snapshot()

    def resolve_target(self, target: str | os.PathLike[str]) -> Path:
        return self._policy.resolve_target(target)

    def walk_top(self, target: str | os.PathLike[str]) -> Path:
        return self.resolve_target(target)

    def explain_many(self, targets: Iterable[str | os.PathLike[str]]) -> list[IgnoreDecision]:
        return [self._policy._explain_with_snapshot(target, self._snapshot) for target in targets]

    def should_descend_directory(self, target: Path) -> bool:
        return self._policy.should_descend_directory(target)

    def can_prune_ignored_directory(self, target: Path, decision: IgnoreDecision) -> bool:
        return self._policy._can_prune(target, decision, self._snapshot)


class BreezyIgnorePolicy(IgnorePolicy):
    """Evaluate Breezy's `.bzrignore`, user ignore file, and client default rules.

    The policy discovers a Breezy tree, obtains the installed client's built-in rules using the
    read-only ``brz ignore --default-rules`` command, and evaluates all rules locally. It supports
    basename and root-relative globs, ``/**/``, ``RE:`` expressions over complete
    workspace-relative paths, exception priority, and ``!!`` strong exclusions. A declared exception
    can keep an ignored ancestor traversable even when its target does not exist. Ignore decisions
    describe rule behavior, not tracked membership.

    Attributes:
        root: Caller traversal root, bounded to this policy's targets.
        workspace_root: Discovered Breezy working-tree root.
        scheme: Stable ``"breezy"`` identifier.
    """

    @property
    def scheme(self) -> str:
        """Return the stable identifier for Breezy ignore rules."""
        return "breezy"

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        brz_executable: str = "brz",
        environment: Mapping[str, str] | None = None,
        global_ignore_file: str | os.PathLike[str] | None = None,
        timeout: float = 30.0,
        initial_excludes: Sequence[str] = (_WORKSPACE_MARKER,),
    ) -> None:
        """Bind a caller root to a Breezy tree and load the client's built-in rules."""
        try:
            self.root = Path(root).expanduser().resolve()
        except (OSError, RuntimeError) as error:
            raise ValueError(f"unable to resolve Breezy policy root: {error}") from error
        if not self.root.is_dir():
            raise ValueError(f"Breezy policy root must be a directory: {self.root}")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        self.brz_executable = brz_executable
        self.timeout = timeout
        self._environment = dict(os.environ if environment is None else environment)
        self._global_ignore_file = (
            Path(global_ignore_file).expanduser() if global_ignore_file is not None else None
        )
        self._initial_excludes = tuple(
            item.replace("\\", "/").strip("/") for item in initial_excludes
        )
        self.workspace_root = _find_workspace_root(self.root)
        self._default_patterns = self._load_default_patterns()
        self._load_snapshot()

    def resolve_target(self, target: str | os.PathLike[str]) -> Path:
        """Resolve a target and reject paths outside the caller's traversal root."""
        path = Path(target).expanduser()
        if not path.is_absolute():
            path = self.root / path
        try:
            path = path.resolve()
        except (OSError, RuntimeError) as error:
            raise ValueError(f"unable to resolve Breezy target: {error}") from error
        if not path.is_relative_to(self.root):
            raise ValueError(f"target must be inside policy root: {path}")
        return path

    def explain(self, target: str | os.PathLike[str]) -> IgnoreDecision:
        """Explain whether Breezy ignore rules affect one target."""
        return self._explain_with_snapshot(target, self._load_snapshot())

    def explain_many(self, targets: Iterable[str | os.PathLike[str]]) -> list[IgnoreDecision]:
        """Explain an ordered set of targets against one rule snapshot."""
        snapshot = self._load_snapshot()
        return [self._explain_with_snapshot(target, snapshot) for target in targets]

    def iter_explain(
        self, targets: Iterable[str | os.PathLike[str]], *, batch_size: int = 256
    ) -> Iterator[IgnoreDecision]:
        """Lazily explain targets against one stable rule snapshot."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        snapshot = self._load_snapshot()
        for target in targets:
            yield self._explain_with_snapshot(target, snapshot)

    def trace(self, target: str | os.PathLike[str]) -> IgnoreTrace:
        """Return all matching rules, ordered by Breezy's ignore/exception priority."""
        path = self.resolve_target(target)
        snapshot = self._load_snapshot()
        relative = path.relative_to(self.workspace_root).as_posix()
        matches = self._matching_rules(relative, snapshot)
        decision = self._decision(path, relative, snapshot, matches)
        effective = decision.source, decision.pattern, decision.line
        trace = tuple(
            IgnoreTraceMatch(
                source=rule.source,
                pattern=rule.pattern,
                line=rule.line,
                ignored=rule.priority != "exception",
                effective=(rule.source, rule.pattern, rule.line) == effective,
                scheme=self.scheme,
                scope=".",
                reason=("matched-exception" if rule.priority == "exception" else "matched-rule"),
            )
            for rule in matches
        )
        return IgnoreTrace(decision=decision, matches=trace, complete=True)

    def can_prune_ignored_directory(self, target: Path, decision: IgnoreDecision) -> bool:
        """Keep ignored directories traversable when a Breezy exception can reach below them."""
        return self._can_prune(target, decision, self._load_snapshot())

    def _open_walk(self) -> _IgnoreWalkSession:
        """Create a walk session with one stable set of rules."""
        return _BreezyWalkSession(self)

    def _load_default_patterns(self) -> tuple[str, ...]:
        """Read version-specific default rules without touching the caller's Breezy config."""
        with tempfile.TemporaryDirectory(prefix="gitignore-walk-brz-defaults-") as temporary:
            home = Path(temporary)
            environment = {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "BRZ_HOME": str(home / "brz-home"),
                "BRZ_PLUGIN_PATH": "",
                "PATH": os.pathsep.join(os.get_exec_path(self._environment)),
                "LC_ALL": "C",
                "LANG": "C",
                "TZ": "UTC",
            }
            result = self._run_brz(
                ("ignore", "--no-plugins", "--default-rules"), environment, cwd=self.workspace_root
            )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise BreezyIgnoreError(
                f"Unable to read Breezy default ignore rules: {detail}",
                operation="default-rules",
            )
        return tuple(result.stdout.decode("utf-8", errors="strict").splitlines())

    def _load_snapshot(self) -> _BreezySnapshot:
        """Load current global and checkout rules around the cached native defaults."""
        rules: list[_BreezyRule] = []
        global_path = self._global_ignore_path()
        if global_path.is_file():
            rules.extend(_load_rule_file(global_path))
        for line_number, pattern in enumerate(self._default_patterns, start=1):
            if rule := _compile_rule(pattern, source="Breezy built-in defaults", line=line_number):
                rules.append(rule)
        local_path = self.workspace_root / ".bzrignore"
        if local_path.is_file():
            rules.extend(_load_rule_file(local_path))
        return _BreezySnapshot(tuple(rules))

    def _global_ignore_path(self) -> Path:
        """Resolve the standard XDG user ignore file unless the caller chose an explicit path."""
        if self._global_ignore_file is not None:
            path = self._global_ignore_file
            return path if path.is_absolute() else self.workspace_root / path
        brz_home = self._environment.get("BRZ_HOME")
        if brz_home:
            return Path(brz_home) / "breezy" / "ignore"
        if os.name == "nt":
            app_data = self._environment.get("APPDATA")
            if app_data:
                return Path(app_data) / "Breezy" / "ignore"
        xdg = self._environment.get("XDG_CONFIG_HOME")
        if xdg:
            return Path(xdg) / "breezy" / "ignore"
        home = self._environment.get("HOME") or self._environment.get("USERPROFILE")
        return (Path(home) if home else Path.home()) / ".config" / "breezy" / "ignore"

    def _run_brz(
        self,
        arguments: Sequence[str],
        environment: Mapping[str, str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(
                [self.brz_executable, *arguments],
                cwd=cwd,
                env=dict(environment),
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except OSError as error:
            raise BreezyIgnoreError(
                f"Unable to run Breezy command: {error}", operation=arguments[0]
            ) from error
        except subprocess.TimeoutExpired as error:
            raise BreezyIgnoreError(
                f"Breezy command timed out after {self.timeout:g} seconds.",
                operation=arguments[0],
            ) from error

    def _explain_with_snapshot(
        self, target: str | os.PathLike[str], snapshot: _BreezySnapshot
    ) -> IgnoreDecision:
        path = self.resolve_target(target)
        relative = path.relative_to(self.workspace_root).as_posix()
        matches = self._matching_rules(relative, snapshot)
        return self._decision(path, relative, snapshot, matches)

    def _matching_rules(
        self,
        relative: str,
        snapshot: _BreezySnapshot,
    ) -> tuple[_BreezyRule, ...]:
        # Breezy compares each rule with the complete workspace-relative path when the
        # pattern contains a slash or is a regex, and otherwise with the final path component.
        # Ancestor exceptions affect traversal reachability, not the target's rule decision.
        return tuple(rule for rule in snapshot.rules if rule.matches(relative))

    def _decision(
        self,
        path: Path,
        relative: str,
        snapshot: _BreezySnapshot,
        matches: tuple[_BreezyRule, ...],
    ) -> IgnoreDecision:
        relative_to_root = path.relative_to(self.root).as_posix()
        baseline = next(
            (
                pattern
                for pattern in self._initial_excludes
                if _path_matches_prefix(relative_to_root, pattern)
            ),
            None,
        )
        diagnostics = tuple(
            rule.diagnostic for rule in snapshot.rules if rule.diagnostic is not None
        )
        if baseline is not None:
            return IgnoreDecision(
                path=path,
                ignored=True,
                scheme=self.scheme,
                source="Breezy walker baseline",
                pattern=baseline,
                scope=".",
                reason="baseline-exclusion",
                discovery_complete=True,
                diagnostics=diagnostics,
            )
        winning = _winning_rule(matches)
        if winning is None:
            return IgnoreDecision(
                path=path,
                ignored=False,
                scheme=self.scheme,
                reason="no-matching-rule",
                discovery_complete=True,
                diagnostics=diagnostics,
            )
        ignored = winning.priority != "exception"
        return IgnoreDecision(
            path=path,
            ignored=ignored,
            scheme=self.scheme,
            source=winning.source,
            pattern=winning.pattern,
            line=winning.line,
            scope=".",
            reason="matched-exception" if winning.priority == "exception" else "matched-rule",
            discovery_complete=True,
            diagnostics=diagnostics,
        )

    def _can_prune(self, target: Path, decision: IgnoreDecision, snapshot: _BreezySnapshot) -> bool:
        if not decision.ignored:
            return False
        relative = target.relative_to(self.workspace_root).as_posix()
        return not any(
            rule.priority == "exception" and _exception_may_open(relative, rule)
            for rule in snapshot.rules
        )


def _find_workspace_root(root: Path) -> Path:
    """Find the nearest Breezy tree marker at or above ``root``."""
    for candidate in (root, *root.parents):
        if (candidate / _WORKSPACE_MARKER).exists():
            return candidate
    raise ValueError(f"no Breezy working tree found at or above policy root: {root}")


def _load_rule_file(path: Path) -> list[_BreezyRule]:
    """Read one UTF-8 Breezy ignore source while preserving spaces in pattern records."""
    try:
        contents = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise BreezyIgnoreError(
            f"Unable to read Breezy ignore source: {error}",
            operation="read",
            source=str(path),
        ) from error
    rules: list[_BreezyRule] = []
    for line_number, pattern in enumerate(contents.splitlines(), start=1):
        if not pattern or pattern.startswith("#"):
            continue
        if rule := _compile_rule(pattern, source=str(path), line=line_number):
            rules.append(rule)
    return rules


def _compile_rule(pattern: str, *, source: str, line: int) -> _BreezyRule | None:
    """Apply Breezy normalization, compile one rule, and classify its priority."""
    original_pattern = pattern
    # Match Breezy 3.3.24's normalize_pattern order: !!RE is not exempted before
    # the leading priority marker is stripped, so backslashes become separators.
    if not pattern.startswith(("RE:", "!RE:")):
        pattern = _SEPARATOR_RUN.sub("/", pattern)
    if len(pattern) > 1:
        pattern = pattern.rstrip("/")
    priority = "ignore"
    body = pattern
    if body.startswith("!!"):
        priority, body = "strong", body[2:]
    elif body.startswith("!"):
        priority, body = "exception", body[1:]
    if not body:
        return None
    regex = body.startswith("RE:")
    expression_text = body[3:] if regex else body.rstrip("/")
    root_only = not regex and expression_text.startswith("./")
    if root_only:
        expression_text = expression_text[2:]
    diagnostic = None
    try:
        if regex:
            if _NAMED_CAPTURE.search(expression_text):
                expression_text = _NAMED_CAPTURE.sub("(?:", expression_text)
                diagnostic = IgnoreDiagnostic(
                    code="named-regex-capture-normalized",
                    message="Breezy normalizes named capture groups to non-capturing groups.",
                    source=source,
                )
            # Python 3.10 only warned about global flags inside Breezy's capture
            # wrapper, while newer interpreters reject them. Keep parser behavior
            # stable across supported Python versions.
            if _GLOBAL_INLINE_FLAGS.search(expression_text):
                raise re.error("global flags are not at the start of the expression")
            # Breezy wraps regular expressions in a capturing group before
            # compiling them. Keep that wrapper: numeric backreferences are
            # numbered relative to it, including its open group.
            expression = re.compile(f"({expression_text})$")
        else:
            expression = re.compile(_glob_to_regex(expression_text))
    except re.error as error:
        raise BreezyIgnoreError(
            f"Invalid Breezy pattern at {source}:{line}: {error}",
            operation="parse",
            source=source,
            line=line,
        ) from error
    return _BreezyRule(
        source=source,
        pattern=original_pattern,
        line=line,
        priority=priority,
        regex=regex,
        root_only=root_only,
        expression=expression,
        diagnostic=diagnostic,
    )


def _glob_to_regex(pattern: str) -> str:
    """Compile Breezy path globs; ordinary wildcards cannot cross path separators."""
    segments = pattern.split("/")
    expression = ["^"]
    for index, segment in enumerate(segments):
        if segment == "**" and index < len(segments) - 1:
            expression.append("(?:[^/]+/)*")
            continue
        if segment == "**":
            expression.append(".*")
        else:
            translated = fnmatch.translate(segment)
            expression.append(translated[len("(?s:") : -len(")\\Z")])
        if index < len(segments) - 1 and segment != "**":
            expression.append("/")
    expression.append("$")
    return "".join(expression)


def _winning_rule(matches: tuple[_BreezyRule, ...]) -> _BreezyRule | None:
    """Apply Breezy's priority classes: strong ignore, exception, then regular ignore."""
    strong = next((rule for rule in matches if rule.priority == "strong"), None)
    if strong is not None:
        return strong
    exception = next((rule for rule in matches if rule.priority == "exception"), None)
    if exception is not None:
        return exception
    return next((rule for rule in matches if rule.priority == "ignore"), None)


def _exception_may_open(directory: str, rule: _BreezyRule) -> bool:
    """Conservatively decide if an exception could re-open ``directory`` for descendants."""
    if rule.priority != "exception":
        return False
    if rule.regex:
        return True
    pattern = rule.pattern[1:]
    if pattern.startswith("./"):
        return directory == "."
    if "/" not in pattern:
        return True
    wildcard_positions = [pattern.find(character) for character in "*?[" if character in pattern]
    first_wildcard = min(wildcard_positions) if wildcard_positions else len(pattern)
    literal_prefix = pattern[:first_wildcard].rstrip("/")
    if not literal_prefix:
        return True
    return (
        literal_prefix == directory
        or literal_prefix.startswith(directory + "/")
        or directory.startswith(literal_prefix + "/")
    )


def _path_prefixes(path: str) -> tuple[str, ...]:
    """Return a workspace-relative path and each ancestor directory, most specific first."""
    parts = path.split("/")
    return tuple("/".join(parts[:index]) for index in range(len(parts), 0, -1))


def _path_matches_prefix(path: str, pattern: str) -> bool:
    """Match a baseline exclusion against the target or one of its ancestors."""
    expression = re.compile(_glob_to_regex(pattern))
    return any(expression.fullmatch(item) is not None for item in _path_prefixes(path))
