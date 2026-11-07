"""Compare full ordered rule scans with first-character candidate groups.

Run from the repository root with ``PYTHONPATH=src python
benchmarks/compare_pattern_candidates.py``. The generated corpora intentionally separate selective
literal prefixes from wildcard-first rules.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from statistics import median
from timeit import repeat

from gitignore_walk import parse_gitignore

DEFAULT_RULE_COUNT = 2_000
DEFAULT_TARGET_COUNT = 1_000
DEFAULT_REPEATS = 5

def _compare(patterns: list[str], targets: list[str], *, repeats: int) -> tuple[float, float]:
    spec = parse_gitignore(patterns, source="synthetic benchmark")

    def full_scan() -> int:
        last_line = 0
        for target in targets:
            decision = None
            for pattern in spec.patterns:
                if pattern.matches(target, is_directory=False):
                    decision = pattern
            if decision is not None:
                last_line += decision.source_line
        return last_line

    def candidate_scan() -> int:
        last_line = 0
        for target in targets:
            characters = {part[0] for part in target.split("/") if part}
            decision = None
            for pattern in spec.candidate_patterns(characters):
                if pattern.matches(target, is_directory=False) and (
                    decision is None or pattern.source_line > decision.source_line
                ):
                    decision = pattern
            if decision is not None:
                last_line += decision.source_line
        return last_line

    full = median(repeat(full_scan, number=1, repeat=repeats))
    indexed = median(repeat(candidate_scan, number=1, repeat=repeats))
    return full, indexed

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules", type=int, default=DEFAULT_RULE_COUNT)
    parser.add_argument("--targets", type=int, default=DEFAULT_TARGET_COUNT)
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    arguments = parser.parse_args(argv)
    for name in ("rules", "targets", "repeats"):
        if getattr(arguments, name) < 1:
            parser.error(f"--{name} must be positive")

    rule_count = arguments.rules
    target_count = arguments.targets
    selective_patterns = [
        f"{chr(97 + index % 26)}group-{index:04d}/artifact-{index:04d}.tmp"
        for index in range(rule_count)
    ]
    selective_targets = [f"qqq-{index:05d}/keep-{index:05d}.bin" for index in range(target_count)]
    wildcard_patterns = [f"*.ext{index:04d}" for index in range(rule_count)]
    wildcard_targets = [f"path-{index:05d}/keep-{index:05d}.bin" for index in range(target_count)]

    for name, patterns, targets in (
            ("selective literal prefixes", selective_patterns, selective_targets),
            ("wildcard-first extensions", wildcard_patterns, wildcard_targets),
    ):
        full, indexed = _compare(patterns, targets, repeats=arguments.repeats)
        print(
            f"{name}: {rule_count} rules / {target_count} targets; "
            f"full={full:.3f}s; indexed={indexed:.3f}s; speedup={full / indexed:.2f}x"
        )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
