"""Downstream typing fixture for a non-Git policy using the shared walker interface."""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from pathlib import Path

from typing_extensions import assert_type

from gitignore_walk import IgnoreDecision, IgnorePolicy, IgnoreWalker


class ExamplePolicy(IgnorePolicy):
    """Minimal policy implementation without Git matcher types or Git-specific settings."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def resolve_target(self, target: str | os.PathLike[str]) -> Path:
        path = Path(target)
        resolved = path.resolve() if path.is_absolute() else (self.root / path).resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError("target is outside policy root")
        return resolved

    def explain(self, target: str | os.PathLike[str]) -> IgnoreDecision:
        return IgnoreDecision(path=self.resolve_target(target), ignored=False)

    def iter_explain(
        self, targets: Iterable[str | os.PathLike[str]], *, batch_size: int = 256
    ) -> Iterator[IgnoreDecision]:
        del batch_size
        yield from (self.explain(target) for target in targets)


def check_neutral_policy_contract(root: Path) -> None:
    """Check an implementation can consume the shared contract without Git-specific types."""
    policy: IgnorePolicy = ExamplePolicy(root)
    assert_type(IgnoreWalker(root, policy=policy), IgnoreWalker)
