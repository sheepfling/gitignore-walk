# gitignore-walk

**Evaluate Git-ignore rules, explain matching decisions, and traverse directory trees from Python.**

`gitignore-walk` is a Python 3.10+ library for tools that need predictable, inspectable file
discovery. It supports nested `.gitignore` rules, batch matching, rule provenance, and directory
traversal with optional ignore filtering.

Two policies let applications choose whether to use the bundled evaluator or Git itself:

- **`GitIgnorePolicy` — Portable Python.** A bundled Git-ignore parser and matcher with no
  third-party runtime dependencies. Works without launching Git, even outside a repository.
- **`GitStandardPolicy` — Git-native.** Delegates matching to Git itself, respecting configured
  global excludes, repository configuration, and Git-specific behavior.

Both work with `GitIgnoreWalker`; choose the policy that fits the application's configuration needs.

This release supports Git ignore rules only; Mercurial's `.hgignore` and other VCS ignore formats
are not supported yet. Future formats should have their own policy and tagged config so selecting
or falling back between resolvers never silently changes the ignore grammar. This is a built-in
extension path, not a runtime plugin registry.

Designed for repository analyzers, code indexers, documentation generators, linters, and build tools.

## Quick start

### Portable matching

Use the Python-only policy when you want to avoid a Git executable dependency or need to inspect
ordinary directory trees.

```python
from gitignore_walk import GitIgnoreWalker

walker = GitIgnoreWalker("/path/to/project")

for path in walker.iter_files():
    print(path)
```

The walker creates its portable policy automatically. Pass an existing policy when you need to
share one or use Git-native matching; the automatically created policy is also available as
`walker.policy` for individual queries and explanations.

The portable policy evaluates applicable rules from:

- Root and nested `.gitignore` files.
- Repository `info/exclude`, when discoverable.
- The conventional user-global Git ignore file.
- Explicit caller-provided `initial_excludes`.

It discovers an enclosing repository by walking upward, including worktree `.git` files, but does
not require a repository.

The matcher evaluates the patterns itself without launching Git. It intentionally does not
interpret Git configuration such as custom `core.excludesFile` paths or conditional includes.

### Git-native matching

When you need Git's actual configured ignore behavior:

```python
from gitignore_walk import GitStandardPolicy, GitIgnoreWalker

policy = GitStandardPolicy("/path/to/checkout")

for decision in policy.explain_many(
    [
        "build/output.txt",
        "docs/guide.md",
    ]
):
    print(
        decision.path,
        decision.ignored,
        decision.source,
        decision.line,
        decision.pattern,
    )

walker = GitIgnoreWalker(policy.root, policy=policy)

for path in walker.iter_files():
    print(path)
```

This policy uses `git check-ignore --no-index` and requires an installed Git executable and a
non-bare working tree.

It honors Git configuration, including `core.excludesFile`, linked worktrees, and configuration includes.

Because matching uses `--no-index`, tracked files can still match ignore rules. **Ignore-rule
evaluation is not the same as Git status.**

### Prefer Git with an explicit fallback

Fallback is opt-in. Use `PreferGitPolicyConfig` only when portable behavior is acceptable if Git is
missing. The default `select_policy(root)` stays portable, while `GitPolicyConfig` requires Git and
never falls back. Pass the preferred config to `select_policy` to allow the missing-Git fallback:

```python
import logging

from gitignore_walk import GitIgnoreWalker, PreferGitPolicyConfig, select_policy

selection = select_policy("/path/to/checkout", PreferGitPolicyConfig())
if selection.fallback_reason is not None:
    logging.getLogger(__name__).warning(
        "Using %s after fallback: %s", selection.backend, selection.fallback_reason
    )
walker = GitIgnoreWalker(selection.policy.root, policy=selection.policy)
```

`PortablePolicyConfig` always selects the portable resolver. `GitPolicyConfig` requires Git.
`PreferGitPolicyConfig` tries Git first and uses the portable resolver only when the executable is
confirmed missing. All three accept `initial_excludes` and an optional complete `environment`;
the Git configs also accept `git_executable` and `timeout`.

Selection happens immediately, before iteration. The result's `mode` records the requested config;
`backend` records the resolver actually selected. It is `"git"` or `"portable"`, and checking it
narrows `policy` to `GitStandardPolicy` or `GitIgnorePolicy` for static type checkers. The
`fallback_reason` is `"git-executable-missing"` only on fallback, otherwise `None`. The library
does not log automatically; inspect `backend` or `fallback_reason` and report it at the level your
application needs. The returned policy never switches backends during queries or walks. Permissions,
timeouts, invalid repositories, broken configuration, and later subprocess failures remain errors.
An existing executable whose interpreter/loader is missing is not a missing Git.

Calling `select_policy(root)` is equivalent to passing `PortablePolicyConfig()`. Existing policy
constructors and the walker's portable default are unchanged.

`environment` is a complete environment, not an overlay. Both the selector and `GitIgnorePolicy`
use supplied HOME/USERPROFILE and XDG_CONFIG_HOME for conventional global ignores without consulting
ambient variables. An explicit environment without these locations has no conventional global file.
Omitting the portable policy's environment retains its existing ambient discovery behavior.

Fallback handles ancestor/nested `.gitignore`, discoverable `info/exclude`, and conventional global
ignores. It **does not read Git configuration**, including custom `core.excludesFile` or includes,
so its results can differ from native Git. Use strict Git mode when these settings are required.

## Understand why a path is ignored

Consider a repository with two ignore files:

```text
project/
├── .gitignore
├── build/
│   └── output.log
└── src/
    ├── .gitignore
    ├── debug.log
    └── keep.log
```

The root `.gitignore` contains:

```gitignore
*.log
```

And `src/.gitignore` contains:

```gitignore
!keep.log
```

The root rule ignores `.log` files. The nested rule makes `src/keep.log` eligible for inclusion again.

Using the Git-native policy:

```python
policy = GitStandardPolicy("/path/to/project")

for path in (
    "build/output.log",
    "src/debug.log",
    "src/keep.log",
):
    decision = policy.explain(path)
    print(path, decision.ignored, decision.pattern)
```

Expected results:

```text
build/output.log True *.log
src/debug.log True *.log
src/keep.log False !keep.log
```

The detailed explanation also identifies the matching rule's origin:

| Path               | Ignored | Source           | Line |
| ------------------ | ------- | ---------------- | ---- |
| `build/output.log` | Yes     | `.gitignore`     | 1    |
| `src/debug.log`    | Yes     | `.gitignore`     | 1    |
| `src/keep.log`     | No      | `src/.gitignore` | 1    |

`GitIgnoreDecision` exposes the evaluated `path`, `ignored` state, `source`, matching `pattern`, and
one-based `line` number.

For overlay diagnostics, use `policy.trace(path)`. It returns the effective decision and the
matching rule from each applicable source in precedence order, with `effective=True` on the rule
that determined the result. The portable policy traces its configured layers and parent-directory
blocking rules. `GitStandardPolicy` reports Git's winning rule, but sets `complete=False` because
Git's check-ignore interface does not expose every shadowed matching rule.

This distinction matters when explaining *why* a file was selected, not just whether it matched an
ignore rule.

## Choose a matching policy

| Capability                     | Portable Python   | Git-native |
| ------------------------------ | ----------------- | ---------- |
| Requires Git                   | No                | Yes        |
| Works outside Git repositories | Yes               | No         |
| Nested `.gitignore`            | Yes               | Yes        |
| Repository `info/exclude`      | When discoverable | Yes        |
| Conventional global ignores    | Yes               | Yes        |
| Custom `core.excludesFile`     | No                | Yes        |
| Git configuration includes     | No                | Yes        |
| Batch matching                 | Yes               | Yes        |
| Match explanations             | Yes               | Yes        |
| Filtered traversal             | Yes               | Yes        |

**Choose portable** when your application needs a self-contained matcher, may run outside
repositories, or needs predictable Python-only evaluation.

**Choose Git-native** when the user's Git configuration is part of the required behavior.

The policies have intentional compatibility differences. `GitStandardPolicy` never silently falls
back to portable matching.

## Traverse and filter directory trees

`GitIgnoreWalker` supports `os.walk`-style traversal:

```python
walker = GitIgnoreWalker("/path/to/project")

for directory, dir_names, file_names in walker.walk():
    print(directory, file_names)
```

The `selection` parameter controls which entries are returned:

| Value        | Behavior                           |
| ------------ | ---------------------------------- |
| `"included"` | Select unignored entries (default) |
| `"ignored"`  | Select ignored entries             |
| `"all"`      | Traverse without ignore filtering  |

For top-down unfiltered or unignored walks, modify `dir_names` to prevent descent:

```python
for directory, dir_names, file_names in walker.walk():
    dir_names[:] = [name for name in dir_names if name != "generated"]
```

`walk()` yields `GitIgnoreWalkEntry` named tuples, supporting both named attributes and familiar
three-value unpacking.

`iter_files()` provides a simpler interface when only file paths are needed.

Policies exclude `.git` files and directories by default, including nested repository metadata.
`initial_excludes` replaces this baseline: use `initial_excludes=()` to remove it, or include
`.git` alongside any other hard exclusions you supply. Use `selection="all"` to bypass ignore
filtering. Other hidden files follow the active policy.

Ignored-only traversal still visits necessary unignored parents to locate ignored descendants. Its
filtered directory list does not control pruning.

## Matching and lower-level APIs

Both policies support individual and batch queries:

```python
policy.is_ignored("build/output.log")

policy.is_ignored_many(
    [
        "src/main.py",
        "build/output.log",
        "docs/guide.md",
    ]
)

policy.explain("build/output.log")
```

Other available interfaces include:

| API                                                   | Purpose                                              |
| ----------------------------------------------------- | ---------------------------------------------------- |
| `is_gitignored(root, target)`                         | Portable one-shot query                              |
| `parse_gitignore(lines, source=...)`                  | Parse ignore rules into an immutable `GitIgnoreSpec` |
| `matches_gitignore(spec, relative, is_directory=...)` | Evaluate a parsed specification                      |
| `GitIgnoreWalker.walk()`                              | Directory traversal with optional filtering          |
| `GitIgnoreWalker.iter_files()`                        | File-only traversal                                  |
| `IgnorePolicy.explain_many()`                         | Return a mutable list of detailed decisions          |
| `IgnorePolicy.is_ignored_many()`                      | Return a mutable list of ignore decisions            |
| `IgnorePolicy.iter_explain()`                         | Lazily yield detailed decisions                      |
| `IgnorePolicy.iter_ignored()`                         | Lazily yield ignore decisions                        |

Both policies implement `IgnorePolicy`. Lazy methods consume targets as they run: the portable
policy caches each ignore file when first read, and the Git-native policy queries up to `batch_size`
targets per Git process (256 by default). Git can observe changes between batches. Errors are raised
when iteration reaches the affected target or batch; neither mode freezes the filesystem.

## Important behavior

A few details are worth knowing before integrating the library:

**Roots and paths.** Relative queries use the policy root. Missing targets are allowed. Targets
outside that root are rejected, and unknown nonexistent targets are treated as files.

**Baseline exclusions.** Both policies treat `initial_excludes` as hard exclusions. A positive
baseline match cannot be overridden by later Git-ignore negation rules.

**Symlinks.** Discovered symlinks are omitted from traversal. Following symlinks is unsupported.
Explicit point-query behavior differs between policies in certain cases.

**Filesystem consistency.** Operations may cache discovered rules or execute Git in batches. They do
not provide an atomic snapshot of a changing directory tree.

**Errors.** Matching, decoding, configuration, and subprocess failures are reported rather than
silently ignored. The Git-native policy does not automatically fall back to portable evaluation.

**Platform differences.** Pathname interpretation and filesystem behavior can differ between POSIX
and Windows, particularly for filenames Windows cannot ordinarily represent.

These boundaries are covered by differential and platform-specific tests. See [validation](docs/validation.md)
for local test commands and the latest verification results.

The library is not a filesystem security boundary.

## Development

From the repository root, create a Python 3.12 virtual environment and install the development
tools. The commands use that environment's Python directly, so activation is optional.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m scripts.ci all
```

In Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m scripts.ci all
```

If `.venv` already exists, verify it uses Python 3.12 before reusing it. Run the last command before
pushing. It runs the same full local check as CI: tests, Ruff lint and format checks, strict Pyright,
Markdown checks, and package validation. See [local and CI verification](docs/validation.md) for the
phases, how to diagnose a failure, and the interpreter/platform matrix used by hosted CI.

GitHub Actions delegates each matrix entry to this same runner: other platform and Python entries
run `test`, while Ubuntu Python 3.12 runs `all`. That job is the hosted counterpart to the complete
local pre-push run.

When editing Markdown, apply safe formatting fixes before the final check:

```sh
rumdl check --fix .
python -m mdrepo fix .  # Python 3.11+
python -m scripts.ci all
```

Or test across supported Python interpreters installed locally:

```sh
python -m scripts.ci matrix
```

| Command   | Purpose                                                      |
| --------- | ------------------------------------------------------------ |
| `test`    | Unit and differential verification on the active interpreter |
| `quality` | Ruff, strict Pyright, and Markdown checks                    |
| `package` | Wheel/sdist build, Twine validation, isolated wheel import   |
| `all`     | All checks for the active interpreter                        |
| `matrix`  | Test across locally installed supported interpreters         |
| `local`   | Windows interpreter matrix and Linux Docker matrix           |

GitHub Actions covers Python 3.10, 3.12, and 3.15 on Ubuntu, plus Python 3.12 on Windows and macOS.

Tests isolate Git configuration and HOME/XDG settings. Differential fixtures compare portable
matching with Git's own evaluator.

See [validation](docs/validation.md) for local CI details and verified results.

## References

Matching behavior is informed by Git's official documentation:

- [gitignore](https://git-scm.com/docs/gitignore)
- [git check-ignore](https://git-scm.com/docs/git-check-ignore)
- [git config](https://git-scm.com/docs/git-config)
