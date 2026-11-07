"""Optional PathSpec matcher adapter for backend comparisons."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from importlib import import_module
from typing import Protocol, cast

from ._ignore_file import GitIgnoreError, GitIgnoreMatch


class _Pattern(Protocol):
    pattern: str | None


class _CheckResult(Protocol):
    include: bool | None
    index: int | None


class _CompiledPathSpec(Protocol):
    patterns: Sequence[_Pattern]

    def check_file(self, file: str) -> _CheckResult:
        """Check one normalized path and retain the final matching pattern index."""

        ...


@dataclass(frozen=True, slots=True)
class _PathSpecFile:
    spec: _CompiledPathSpec
    directory_spec: _CompiledPathSpec
    directory_pattern_indexes: tuple[int, ...]
    source_lines: tuple[int | None, ...]


@dataclass(frozen=True, slots=True)
class PathSpecMatcher:
    """Use PathSpec's Git-ignore rules with a selectable regex backend.

    Constructing this matcher does not import PathSpec. The optional dependency is loaded when
    the first ignore file is parsed, so the library's default installation stays dependency-free.
    Supported backend names are ``best``, ``simple``, ``re2``, and ``hyperscan``.
    """

    backend: str = "best"

    @property
    def name(self) -> str:
        return f"pathspec:{self.backend}"

    def parse(self, lines: Iterable[str], *, source: str) -> object:
        source_lines = tuple(lines)
        try:
            pathspec_module = import_module("pathspec")
        except ImportError as error:
            raise GitIgnoreError(
                "PathSpecMatcher requires the optional 'pathspec' dependency; "
                "install gitignore-walk[bench]"
            ) from error

        spec_class = pathspec_module.GitIgnoreSpec
        from_lines = cast(Callable[..., object], spec_class.from_lines)
        try:
            compiled = cast(
                _CompiledPathSpec,
                from_lines(source_lines, backend=self.backend),
            )
            directory_pattern_indexes = tuple(
                index
                for index, pattern in enumerate(compiled.patterns)
                if not (pattern.pattern or "").rstrip().endswith("/**")
            )
            constructor = cast(Callable[..., object], spec_class)
            directory_spec = cast(
                _CompiledPathSpec,
                constructor(
                    tuple(compiled.patterns[index] for index in directory_pattern_indexes),
                    backend=self.backend,
                ),
            )
        except (ImportError, ValueError, TypeError) as error:
            raise GitIgnoreError(
                f"unable to compile {source} with PathSpec backend {self.backend!r}: {error}"
            ) from error
        return _PathSpecFile(
            spec=compiled,
            directory_spec=directory_spec,
            directory_pattern_indexes=directory_pattern_indexes,
            source_lines=_source_line_numbers(source_lines, compiled.patterns),
        )

    def match(
        self,
        spec: object,
        relative: str,
        *,
        source: str,
        is_directory: bool,
    ) -> GitIgnoreMatch | None:
        file = cast(_PathSpecFile, spec)
        path = relative.replace("\\", "/")
        if is_directory and not path.endswith("/"):
            path += "/"
        spec = file.directory_spec if is_directory else file.spec
        result = spec.check_file(path)
        if result.include is None or result.index is None:
            return None
        pattern_index = (
            file.directory_pattern_indexes[result.index] if is_directory else result.index
        )
        pattern = file.spec.patterns[pattern_index]
        return GitIgnoreMatch(
            ignored=result.include,
            source=source,
            pattern=pattern.pattern or "",
            line=file.source_lines[pattern_index] or pattern_index + 1,
        )


def _source_line_numbers(
    lines: Sequence[str],
    patterns: Sequence[_Pattern],
) -> tuple[int | None, ...]:
    """Map compiled PathSpec patterns to their original one-based source lines."""

    line_numbers: list[int | None] = []
    cursor = 0
    for pattern in patterns:
        line_number: int | None = None
        while cursor < len(lines):
            candidate = lines[cursor].rstrip("\r\n")
            candidate_number = cursor + 1
            cursor += 1
            if candidate == pattern.pattern:
                line_number = candidate_number
                break
        line_numbers.append(line_number)
    return tuple(line_numbers)
