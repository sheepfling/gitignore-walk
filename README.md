# gitignore-walk

`gitignore-walk` supports Python 3.10–3.15 and evaluates Git ignore rules, explains matching
decisions, and traverses directory trees under an explicit policy. It provides two backends:

- **`GitIgnorePolicy`** parses and evaluates root and nested `.gitignore` files in Python. It works
  without invoking Git and can discover an enclosing repository by walking upward.
- **`GitStandardPolicy`** delegates to the installed Git executable and honors Git's configured
  ignore sources, including global excludes and repository configuration.

Both backends support individual and batch queries, explanations, and filtered traversal through
`GitIgnoreWalker`. The library is useful for repository analyzers, code indexers, documentation
generators, linters, and build tools that need predictable control over file discovery.

This unreleased alpha was extracted from [mdrepo](https://github.com/sheepfling/mdrepo) without
changing mdrepo. The distribution name remains provisional and has not been reserved on PyPI.

## Quick start

### Portable matching

```python
from gitignore_walk import GitIgnorePolicy, GitIgnoreWalker

policy = GitIgnorePolicy(
    "/path/to/project",
    initial_excludes=(".git/",),
)
walker = GitIgnoreWalker(policy.root, policy=policy)

for path in walker.iter_files(ignored=False):
    print(path)
```

The portable backend includes its own Git-ignore parser and matcher, so it works without Git or
third-party runtime dependencies. Starting at the supplied root, it walks upward to discover a
`.git` directory or worktree `.git` file. It reads applicable `.gitignore`
files from the repository root through the target's ancestors, the repository's `info/exclude` when
discoverable, and the conventional user-global file at `$XDG_CONFIG_HOME/git/ignore` (or
`$HOME/.config/git/ignore`).

Portable discovery intentionally does not interpret Git config. In particular, it does not resolve
custom `core.excludesFile` paths, system-level config, or config includes and conditional includes.
Use `GitStandardPolicy` when those Git-specific settings must match exactly. This portable policy
still evaluates every discovered pattern itself; it does not launch Git.

The portable precedence is user-global excludes, repository `info/exclude`, then applicable
`.gitignore` files from the worktree root down to the target directory. Deeper `.gitignore` files
override matching rules in their parents.

### Git-native matching and explanations

```python
from gitignore_walk import GitStandardPolicy, GitIgnoreWalker

policy = GitStandardPolicy("/path/to/checkout")

for decision in policy.explain_many(["build/output.txt", "docs/guide.md"]):
    print(
        decision.path,
        decision.ignored,
        decision.source,
        decision.line,
        decision.pattern,
    )

walker = GitIgnoreWalker(policy.root, policy=policy)
for path in walker.iter_files(ignored=False):
    print(path)
```

The Git-backed policy uses `git check-ignore --no-index` and honors Git's configured excludes,
including `core.excludesFile`, `.git/info/exclude`, conditional includes, and linked-worktree
configuration. Its root must be the root of a non-bare Git worktree.

A matching rule can report a tracked path as ignored because `--no-index` deliberately ignores
index state. The result explains ignore rules; it does not predict Git status or whether a file
will be committed.

## API and traversal

- `is_gitignored(root, target)` is the portable one-shot helper.
- Both policies provide `is_ignored(target)`, `is_ignored_many(targets)` and `explain(target)`.
- `GitStandardPolicy.explain_many(targets)` returns ordered, detailed results in one Git process.
- `GitIgnoreDecision` has `path`, `ignored`, `source`, `pattern`, and one-based `line` fields.
- `parse_gitignore(lines, source=...)` returns the immutable `GitIgnoreSpec` used by
  `matches_gitignore(spec, relative, is_directory=...)`.
- `GitIgnoreWalker.walk()` yields `GitIgnoreWalkEntry(directory, dir_names, file_names)`, a
  named tuple that stays compatible with `os.walk`-style unpacking.
- **`ignored=None` is the default and does no ignore filtering.** `False` selects unignored
  entries, and `True` selects ignored entries while still visiting safe unignored parents.
- `iter_files()` yields the selected file paths. Hidden files and `.git` are not automatically
  excluded. Set an explicit caller baseline if that is desired.
- Top-down walks with `ignored=None` or `ignored=False` support `os.walk`-style pruning: mutate
  the yielded `dir_names` list to prevent descent into selected directories. Ignored-only walks
  must visit unignored parents to find ignored descendants, so their returned filtered directory
  list does not control traversal.
- Discovered symlinks and special files are omitted. `follow_links=True` is rejected.
- Relative targets are rooted at the policy root. Missing paths are allowed. Targets outside
  the root are rejected. Unknown nonexistent paths are treated as files, not guessed directories.
- Caller `initial_excludes` are hard baseline rules evaluated by the portable matcher, not
  additional Git config. A positive baseline match cannot be undone by a repository,
  info/exclude, or global negation.

## Matcher backends

`GitIgnorePolicy` and `GitIgnoreWalker` default to the bundled `RegexMatcher`; the portable policy
can accept another `GitIgnoreMatcher` implementation without changing source discovery, precedence,
provenance, or traversal. `PathSpecMatcher` is an optional adapter for comparing PathSpec engines:

```python
from gitignore_walk import GitIgnorePolicy, PathSpecMatcher

policy = GitIgnorePolicy("/path/to/project", matcher=PathSpecMatcher(backend="simple"))
```

Install `.[bench]` for PathSpec's `simple` and `best` engines, `.[bench-re2]` for RE2, or
`.[bench-hyperscan]` for Hyperscan. These are optional development extras; the default package
still has no runtime dependencies. Compare batched decisions and complete walks with:

```sh
python benchmarks/compare_matchers.py --files 5000 --patterns 100 \
  --backends regex pathspec:simple pathspec:best
```

Use `pathspec:re2` or `pathspec:hyperscan` after installing the matching extra. Benchmark results
depend on the machine, rule set, tree shape, and optional engine availability; measure on the
workload that matters to your caller.

## Errors, provenance, and consistency

`GitIgnoreError` reports read/parse/process failures. The portable backend rejects invalid UTF-8
ignore files; Git can process their bytes and still apply following valid lines. The native
backend preserves undecodable output bytes with the filesystem encoding's surrogate escape and
uses NUL-delimited input/output for unusual filenames. An unmatched native result has no
provenance; a matching negation includes its source even though `ignored=False`. The portable
backend retains mdrepo's legacy behavior of omitting negation provenance for all of its ignore
sources.

The Git-backed backend raises on nonempty Git stderr, even when Git returned success. It never
silently falls back to portable matching or pretends a partial response is complete. Missing
Git, malformed config, process failures and a timeout are errors. A missing optional excludes
file has Git's normal semantics and is not itself an error.

Each portable batch/walk caches ignore files on first read for that operation. This is not an
atomic filesystem snapshot. Native batches use one Git process; a filtered native walk uses one
batch per visited directory. Later directories can observe changed configuration or ignore files.
Neither backend is a filesystem sandbox or safe against concurrent hostile filesystem mutations.
Use external coordination when a stable tree/policy view is required.

Git configuration is inherited intentionally, including `HOME`, XDG and `GIT_CONFIG_*` variables.
`environment=` supplies a complete copied environment instead. `GIT_DIR`, `GIT_WORK_TREE`,
`GIT_COMMON_DIR`, `GIT_INDEX_FILE`, and `GIT_PREFIX` are removed so an unrelated invoking Git
process cannot redirect repository selection. Environment values are captured at construction;
configuration file changes are visible to later Git invocations. `timeout=` defaults to 30 seconds
per Git invocation. The subprocess uses no shell and does not change Git configuration or the index.

## Compatibility limitations before migration

Legacy portable behaviors remain visible and tested rather than silently changed:

1. Portable point queries resolve symlinks before matching. An explicitly supplied internal
   symlink walk root also resolves to its target, even though discovered symlinks are omitted.
   Native point queries preserve the final symlink's Git pathname, reject intermediate symlink
   traversal, and reject a symlink walk root.
2. Bottom-up filtered walks cannot prune descent. An ignored directory row can be yielded with
   empty child lists. Use top-down traversal when pruning matters. This applies to both policies.
3. Git for Windows normalizes trailing-space pathnames that Win32 cannot represent as distinct
   ordinary files. The portable API preserves those strings. Tests assert each backend's actual
   platform behavior rather than claiming universal parity for invalid native filenames.

See [maturity and migration gates](docs/migration.md) and [validation](docs/validation.md).
The library is alpha; mdrepo should keep its existing implementation until the gates are met and a separate migration is reviewed.

## Development

```sh
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -v
python -m ruff check .
python -m ruff format --check .
python -m pyright --pythonpath /absolute/path/to/your/python
python -m build
python -m twine check dist/*
```

Tests isolate HOME, XDG and Git configuration and never alter the developer's global configuration.
The CI matrix covers Ubuntu, macOS, and Windows on Python 3.10–3.15. Its differential fixtures
compare the portable matcher with Git's own evaluator. A configured workflow is not evidence those
platforms have passed on the current commit.

## Sources and license

Portable policy and traversal originated in `mdrepo.gitignore` at
[`78476e0`](https://github.com/sheepfling/mdrepo/blob/78476e0343f6ae3799606c17024d5aa790c6d688/src/mdrepo/gitignore.py).
The mdrepo-specific durability classes stay in mdrepo. The original MIT notice is retained.
This package adds explicit Git-backed policy and package tests, not a Rust binding replacement.

Normative references: [gitignore](https://git-scm.com/docs/gitignore),
[git check-ignore](https://git-scm.com/docs/git-check-ignore),
[git config](https://git-scm.com/docs/git-config).
