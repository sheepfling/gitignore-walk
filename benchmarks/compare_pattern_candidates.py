"""Compare full ordered rule scans with first-character candidate groups.

Run from the repository root with ``PYTHONPATH=src python
benchmarks/compare_pattern_candidates.py``. The generated corpora intentionally separate selective
literal prefixes from wildcard-first rules.
"""

from __future__ import annotations

from statistics import median
from timeit import repeat

from gitignore_walk._ignore_file import parse_gitignore

RULE_COUNT = 2_000
TARGET_COUNT = 1_000
REPEATS = 5


def _compare(patterns: list[str], targets: list[str]) -> tuple[float, float]:
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

    full = median(repeat(full_scan, number=1, repeat=REPEATS))
    indexed = median(repeat(candidate_scan, number=1, repeat=REPEATS))
    return full, indexed


def main() -> None:
    selective_patterns = [
        f"{chr(97 + index % 26)}group-{index:04d}/artifact-{index:04d}.tmp"
        for index in range(RULE_COUNT)
    ]
    selective_targets = [f"qqq-{index:05d}/keep-{index:05d}.bin" for index in range(TARGET_COUNT)]
    wildcard_patterns = [f"*.ext{index:04d}" for index in range(RULE_COUNT)]
    wildcard_targets = [f"path-{index:05d}/keep-{index:05d}.bin" for index in range(TARGET_COUNT)]

    for name, patterns, targets in (
        ("selective literal prefixes", selective_patterns, selective_targets),
        ("wildcard-first extensions", wildcard_patterns, wildcard_targets),
    ):
        full, indexed = _compare(patterns, targets)
        print(
            f"{name}: {RULE_COUNT} rules / {TARGET_COUNT} targets; "
            f"full={full:.3f}s; indexed={indexed:.3f}s; speedup={full / indexed:.2f}x"
        )


if __name__ == "__main__":
    main()
