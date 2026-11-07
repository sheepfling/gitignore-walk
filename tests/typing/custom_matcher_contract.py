"""Downstream type-check fixture for custom matcher implementations."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from typing_extensions import assert_type

from gitignore_walk import GitIgnoreMatch, GitIgnoreMatcher, GitIgnorePolicy


@dataclass(frozen=True, slots=True)
class CustomSpec:
    """Compiled rules owned by the example downstream matcher."""

    rules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CustomMatcher:
    """Example backend that parses rules into ``CustomSpec``."""

    name: str = "custom"

    def parse(self, lines: Iterable[str], *, source: str) -> CustomSpec:
        del source
        return CustomSpec(tuple(lines))

    def match(
        self,
        spec: CustomSpec,
        relative: str,
        *,
        source: str,
        is_directory: bool,
    ) -> GitIgnoreMatch | None:
        del spec, relative, source, is_directory
        return None


custom_matcher: GitIgnoreMatcher[CustomSpec] = CustomMatcher()


def check_custom_matcher_contract(root: Path) -> None:
    """Check custom spec inference and acceptance by the public policy constructor."""

    spec = custom_matcher.parse(("*.custom",), source="typing fixture")
    assert_type(spec, CustomSpec)

    match = custom_matcher.match(
        spec,
        "example.custom",
        source="typing fixture",
        is_directory=False,
    )
    assert_type(match, GitIgnoreMatch | None)

    GitIgnorePolicy(root, matcher=custom_matcher)
