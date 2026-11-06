# gitignore-walk

An unreleased Python 3.11+ library for checking, explaining and traversing Git-ignore rules.
Extracted from [mdrepo](https://github.com/sheepfling/mdrepo) without changing mdrepo.
The [private repository](https://github.com/sheepfling/gitignore-walk) is created; the PyPI
distribution name remains provisional and has not been reserved or published.

## Choose the scope explicitly

The default `GitIgnorePolicy` reads root and nested `.gitignore` files using `pathspec`.
It works without Git and without a `.git` directory. It does **not** read global excludes,
Git config, `.git/info/exclude`, or the index. This preserves the original mdrepo policy.

```python
from gitignore_walk import GitIgnorePolicy, GitIgnoreWalker

policy = GitIgnorePolicy("/path/to/project", initial_excludes=(".git/",))
for path in GitIgnoreWalker(policy.root, policy=policy).iter_files(ignored=False):
    print(path)
```

`GitIgnorePolicy` works without a Git installation. Opt into `GitStandardPolicy` only when you
want the installed Git executable and its actual configuration.
It includes `core.excludesFile`, system/global/local/worktree config, includes and conditional
includes, tilde expansion, XDG fallback, `.git/info/exclude`, and repository `.gitignore` files.
Its root must be the root of a non-bare Git worktree. Linked worktrees and separate Git dirs are
resolved by Git, not by assuming `.git` is a directory.

```python
from gitignore_walk import GitStandardPolicy, GitIgnoreWalker

policy = GitStandardPolicy("/path/to/checkout", initial_excludes=(".git/",))
for decision in policy.explain_many(["build/output.txt", "docs/guide.md"]):
    print(decision.path, decision.ignored, decision.source, decision.line, decision.pattern)
for path in GitIgnoreWalker(policy.root, policy=policy).iter_files(ignored=False):
    print(path)
```

The Git-backed policy always uses `git check-ignore --no-index`. A tracked file can therefore
be reported ignored by a matching rule. This is **not** an index/status/clean-checkout query or a
promise about what Git will commit. Git-native means Git's ignore-rule engine, within the
explicit path and error boundaries described below.

## API and traversal

- `is_gitignored(root, target)` is the portable one-shot helper.
- Both policies provide `is_ignored(target)`, `is_ignored_many(targets)` and `explain(target)`.
- `GitStandardPolicy.explain_many(targets)` returns ordered, detailed results in one Git process.
- `GitIgnoreDecision` has `path`, `ignored`, `source`, `pattern`, and one-based `line` fields.
- `GitIgnoreWalker.walk()` yields `GitIgnoreWalkEntry(directory, dir_names, file_names)`, a
  named tuple that stays compatible with `os.walk`-style unpacking.
- **`ignored=None` is the default and does no ignore filtering.** `False` selects unignored
  entries, and `True` selects ignored entries while still visiting safe unignored parents.
- `iter_files()` yields the selected file paths. Hidden files and `.git` are not automatically
  excluded. Set an explicit caller baseline if that is desired.
- Top-down unignored/all walks expose mutable traversal directory lists. Ignored-only walks must
  visit unignored parents, so their returned filtered directory list does not control traversal.
- Discovered symlinks and special files are omitted. `follow_links=True` is rejected.
- Relative targets are rooted at the policy root. Missing paths are allowed. Targets outside
  the root are rejected. Unknown nonexistent paths are treated as files, not guessed directories.
- Caller `initial_excludes` are hard baseline rules evaluated with `pathspec`, not additional Git
  config. A positive baseline match cannot be undone by a repository or global negation.

## Errors, provenance, and consistency

`GitIgnoreError` reports read/parse/process failures. The portable backend rejects invalid UTF-8
ignore files; Git can process their bytes and still apply following valid lines. The native
backend preserves undecodable output bytes with the filesystem encoding's surrogate escape and
uses NUL-delimited input/output for unusual filenames. An unmatched native result has no
provenance; a matching negation includes its source even though `ignored=False`. The portable
backend retains mdrepo's legacy behavior of omitting repository-negation provenance.

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
The CI matrix covers Ubuntu, macOS and Windows on Python 3.11-3.15, plus the minimum pathspec
version. A configured workflow is not evidence those platforms have passed on the current commit.

## Sources and license

Portable policy and traversal originated in `mdrepo.gitignore` at
[`78476e0`](https://github.com/sheepfling/mdrepo/blob/78476e0343f6ae3799606c17024d5aa790c6d688/src/mdrepo/gitignore.py).
The mdrepo-specific durability classes stay in mdrepo. The original MIT notice is retained.
This package adds explicit Git-backed policy and package tests, not a Rust binding replacement.

Normative references: [gitignore](https://git-scm.com/docs/gitignore),
[git check-ignore](https://git-scm.com/docs/git-check-ignore),
[git config](https://git-scm.com/docs/git-config).

