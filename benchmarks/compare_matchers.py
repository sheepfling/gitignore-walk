"""Compare the bundled and PathSpec matchers on decisions and complete walks.

Run with ``python benchmarks/compare_matchers.py --backends regex pathspec:simple``.
Install ``.[bench-re2]`` or ``.[bench-hyperscan]`` to try those PathSpec engines.
"""

from __future__ import annotations

import argparse
import tempfile
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter

from gitignore_walk import GitIgnorePolicy, GitIgnoreWalker, PathSpecMatcher, RegexMatcher


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=5_000)
    parser.add_argument("--patterns", type=int, default=100)
    parser.add_argument("--backends", nargs="+", default=("regex", "pathspec:simple"))
    arguments = parser.parse_args(argv)
    if arguments.files < 1 or arguments.patterns < 1:
        parser.error("--files and --patterns must be positive")

    with tempfile.TemporaryDirectory(prefix="gitignore-walk-bench-") as temporary:
        root = Path(temporary) / "repo"
        root.mkdir()
        _create_corpus(root, files=arguments.files, patterns=arguments.patterns)
        targets = tuple(path.relative_to(root).as_posix() for path in root.rglob("*"))
        print("backend\tdecision_ms\twalk_ms\tfiles\tignored")
        for name in arguments.backends:
            matcher = _matcher(name)
            policy = GitIgnorePolicy(root, matcher=matcher)
            start = perf_counter()
            decisions = policy.is_ignored_many(targets)
            decision_seconds = perf_counter() - start

            start = perf_counter()
            walked = tuple(GitIgnoreWalker(root, policy=policy).iter_files(ignored=False))
            walk_seconds = perf_counter() - start
            print(
                f"{name}\t{decision_seconds * 1000:.2f}\t{walk_seconds * 1000:.2f}"
                f"\t{len(walked)}\t{sum(decisions)}"
            )
    return 0


def _matcher(name: str) -> RegexMatcher | PathSpecMatcher:
    if name == "regex":
        return RegexMatcher()
    prefix = "pathspec:"
    if name.startswith(prefix):
        return PathSpecMatcher(backend=name.removeprefix(prefix))
    raise ValueError(f"unknown matcher {name!r}; use 'regex' or 'pathspec:<engine>'")


def _create_corpus(root: Path, *, files: int, patterns: int) -> None:
    rules = ["*.tmp", "!keep.tmp", "build/", "!build/keep.txt"]
    rules.extend(f"generated-{index:04d}*.dat" for index in range(patterns - len(rules)))
    (root / ".gitignore").write_text("\n".join(rules) + "\n", encoding="utf-8")
    for index in range(files):
        directory = root / f"group-{index % 100:03d}"
        directory.mkdir(exist_ok=True)
        suffix = ".tmp" if index % 4 == 0 else ".txt"
        (directory / f"item-{index:06d}{suffix}").touch()


if __name__ == "__main__":
    raise SystemExit(main())
