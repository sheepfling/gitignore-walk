# gitignore-walk

**Evaluate VCS ignore rules, explain matching decisions, and traverse directory trees from Python.**

`gitignore-walk` is a Python 3.10+ library for tools that need predictable, inspectable file
discovery. It supports Git, initial portable Mercurial and Perforce policies, initial Fossil and
Breezy ignore policies, an initial Subversion-property policy, a native Darcs boring-candidate
policy, and read-only Sapling and Jujutsu policies for captured Git-ignore behavior. Policies provide
rule provenance and directory traversal with optional filtering.

For Git, two policies let applications choose whether to use the bundled evaluator or Git itself:

- **`GitIgnorePolicy` — Portable Python.** A bundled Git-ignore parser and matcher with no
  third-party runtime dependencies. Works without launching Git, even outside a repository.
- **`GitStandardPolicy` — Git-native.** Delegates matching to Git itself, respecting configured
  global excludes, repository configuration, and Git-specific behavior.

These policies work with `IgnoreWalker`; choose the scheme and evaluator that fit the application's
configuration needs.

The shared API uses scheme-neutral names: `IgnorePolicy`, `IgnoreWalker`, `IgnoreDecision`,
`IgnoreTrace`, `IgnoreTraceMatch`, and `IgnoreWalkEntry`. Git-specific behavior stays in policies
such as `GitIgnorePolicy` and `GitStandardPolicy`.

Mercurial support is an initial portable implementation of `.hgignore` regexp, glob, rootglob,
`include`, and `subinclude` rules. These syntax and source-scope distinctions follow the
[Mercurial ignore documentation](https://mercurial-scm.org/help/topics/hgignore) and
[pattern documentation](https://www.mercurial-scm.org/help/topics/patterns). It does not read
Mercurial configuration files by default. Pass configured `ui.ignore` files explicitly or set
`MercurialPolicyConfig(read_client_config=True)` to ask the installed `hg` executable to discover
them. This mode delegates Mercurial's config-file search and precedence to `hg config`; it requires
the executable and reports config command failures. In the captured
Mercurial 7.2.4/macOS arm64, 7.0.1/Debian 13 Linux aarch64 and x86_64, and 7.1.2/Windows Server
2025 x86_64 profiles, workspace `.hgignore` rules precede configured files, and configured file
order is preserved. The scheme has its own tagged config and never falls back to Git. The other
listed VCS policies are also initial implementations with scheme-specific evidence and limitations;
additional formats and broader conformance remain under research. Each format gets its own policy
and config in this built-in extension path; there is no runtime plugin registry. See the
[unreleased VCS expansion notes](CHANGELOG.md). The
[contributor checklist](docs/contributing/ignore-scheme-readiness.md) and
[VCS expansion backlog](docs/contributing/vcs-expansion-backlog.md) record the architecture and
remaining conformance work.

Designed for repository analyzers, code indexers, documentation generators, linters, and build tools.

## Quick start

### Portable matching

Use the Python-only policy when you want to avoid a Git executable dependency or need to inspect
ordinary directory trees.

```python
from gitignore_walk import IgnoreWalker

walker = IgnoreWalker("/path/to/project")

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
from gitignore_walk import GitStandardPolicy, IgnoreWalker

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

walker = IgnoreWalker(policy.root, policy=policy)

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

from gitignore_walk import IgnoreWalker, PreferGitPolicyConfig, select_policy

selection = select_policy("/path/to/checkout", PreferGitPolicyConfig())
if selection.fallback_reason is not None:
    logging.getLogger(__name__).warning(
        "Using %s after fallback: %s", selection.backend, selection.fallback_reason
    )
walker = IgnoreWalker(selection.policy.root, policy=selection.policy)
```

`PortablePolicyConfig` selects portable Git rules. `GitPolicyConfig` requires Git.
`PreferGitPolicyConfig` tries Git first and uses the portable resolver only when the executable is
confirmed missing. `MercurialPolicyConfig`, `SaplingPolicyConfig`, and `JujutsuPolicyConfig`
explicitly select their schemes. These configs accept
`initial_excludes`; the Git configs also accept an optional complete `environment`,
`git_executable`, and `timeout`.

Selection happens immediately, before iteration. The result's `mode` records the requested config;
`backend` records the resolver actually selected. Git selections use `"git"` or `"portable"`;
Mercurial uses `"mercurial-python"`. Checking `mode` or `backend` narrows `policy` to its concrete
type for static type checkers. The
`fallback_reason` is `"git-executable-missing"` only on fallback, otherwise `None`. The library
does not log automatically; inspect `backend` or `fallback_reason` and report it at the level your
application needs. The returned policy never switches backends during queries or walks. Permissions,
timeouts, invalid repositories, broken configuration, and later subprocess failures remain errors.
An existing executable whose interpreter/loader is missing is not a missing Git.

`SubversionPolicyConfig` explicitly selects native Subversion property discovery. It requires the
`svn` executable, evaluates versioned `svn:ignore` and inherited `svn:global-ignores` properties,
and can read `[miscellany] global-ignores` from an explicitly selected `config_dir/config` file.
When the setting is absent, it uses Subversion's built-in default patterns; an explicitly empty
setting disables those defaults. Additional runtime patterns can be supplied through
`global_ignores`. Without `config_dir`, it reads `/etc/subversion/config` followed by
`$HOME/.subversion/config` (using the supplied `environment`); a per-user setting overrides a
system setting. On Windows it reads machine and user Registry settings along with the standard
`PROGRAMDATA` and `APPDATA` config files, following [Subversion's documented source precedence](https://svnbook.red-bean.com/en/1.7/svn-book.html#svn.advanced.confarea.windows-registry).
It reports inaccessible Registry sources as incomplete. By default, it does not query versioned
membership. Set `membership_aware=True` to query verbose native status and add known `"versioned"`
or `"unversioned"` membership to each `IgnoreDecision`; paths absent from the status listing remain
unknown. The `ignored` field continues to report the rule match. In membership-aware walks, known
versioned entries are selected as included even if a rule matches. This option adds a native status
command for each discovered working-copy snapshot. Status values such as normal, modified, added,
deleted, missing, replaced, obstructed, and conflicted are treated as versioned; native unversioned
and ignored entries are treated as unversioned. The live status-transition test covers these states.
A file below an obstructed directory can still be reached by filesystem traversal even though native
status omits it; its membership stays unknown. The walker keeps ignored directories traversable,
excludes `.svn` metadata by default, and stops at nested `.svn` working copies. It follows externals
that native `svn status` identifies and loads versioned ignore
properties within each listed external working copy, including nested externals; properties from an
outer working copy do not leak across a nested external boundary. This initial policy is compared
against Subversion 1.15.0/macOS
arm64, 1.14.5/Linux aarch64 and x86_64, and 1.14.5/SlikSvn Windows x86_64 profiles, not broad
client/platform certification. See the
[Subversion oracle notes](tests/oracles/svn/README.md).

`PerforcePolicyConfig` explicitly selects the local P4IGNORE evaluator. The caller supplies the
traversal root; no P4 server is required for local rule matching. It reads `P4IGNORE` from the
supplied environment, or checks `.p4ignore` followed by `p4ignore.txt` when the setting is absent. Set
`read_client_config=True` to have the installed P4 client resolve `P4CONFIG` and report its
effective `P4IGNORE` setting. This option invokes `p4 set` for each queried directory; an explicit
`p4ignore=` value takes precedence and keeps evaluation client-independent.
Set `discover_client_workspace=True` to ask `p4 -ztag info` for the configured client root. This
lets the evaluator find ignore files above a nested traversal root while continuing to reject
targets outside the caller's root. Workspace discovery requires a configured P4 client/server
connection and is independent of `read_client_config`.
Set `client_view_aware=True` with workspace discovery to omit files that `p4 -ztag where` reports as
unmapped or explicitly excluded. This affects walker file selection only; it does not alter
P4IGNORE decisions or report versioned membership. Directories remain traversable because an
unmapped directory can still contain files mapped by a wildcard view rule.
The file list uses semicolon separators. The captured precedence is deepest source directory first,
then earliest configured filename at that level, then the last matching line in that file. The
supported subset includes `*`, `**`, leading-slash rules anchored to their ignore file, trailing-slash
directory rules, and `!` exceptions. The walker does not prune ignored directories, so an exception
can re-include a descendant. Broader pattern edge cases are not implemented. It
trims ASCII spaces around each rule, preserves interior spaces and tabs, and supports the documented
`\#` comment escape. All 37 boolean candidates match native P4/P4
Server 2026.1 profiles on macOS arm64, Debian 13 Linux x86_64, and Ubuntu 24.04 Linux x86_64; three
path-boundary probes separately record cases where `p4 add` rejects a filename before ignore
eligibility can be evaluated. See the
[Perforce oracle notes](tests/oracles/perforce/README.md).

`DarcsPolicyConfig` explicitly selects Darcs' native boring-candidate behavior. It requires a Darcs
repository and the `darcs` executable. The policy asks Darcs for add candidates and managed paths,
so files already under version control remain included even when their names match a boring rule.
It keeps ignored directories traversable and excludes `_darcs` metadata by default. Each query batch
uses one pair of native inventory commands; a walker holds one inventory for the duration of that
walk. Managed paths use Darcs' NUL-delimited output; ambiguous line-oriented candidate output falls
back to a targeted dry-run query for each requested path. The policy delegates the ERE dialect and
user/repository preference discovery to Darcs rather than emulating them in Python. Its initial
captures match six closed candidates on Darcs 2.18.5/macOS
arm64 and 2.18.4/Debian 13 x86_64. The documented `boringfile` precedence disagrees with both
captured clients: both keep a local boring rule active alongside a configured `boringfile`. The
policy delegates this behavior to Darcs. See the
[Darcs oracle notes](tests/oracles/darcs/README.md).

`BreezyPolicyConfig` explicitly selects Breezy rule evaluation. It requires `brz` to query the
client's version-specific built-in ignore rules, then evaluates those defaults alongside the
standard user ignore file and the working tree's root `.bzrignore`:

```python
from gitignore_walk import BreezyPolicyConfig, IgnoreWalker, select_policy

selection = select_policy("/path/to/breezy/checkout", BreezyPolicyConfig())
walker = IgnoreWalker(selection.policy.root, policy=selection.policy)

for decision in selection.policy.explain_many(["build/output.tmp", "src/main.py"]):
    print(decision.path, decision.ignored, decision.source, decision.line)
```

The evaluator supports basename and workspace-relative globs, `**`, `RE:` regular expressions,
exceptions (`!`), and strong exclusions (`!!`). Patterns with a slash match the complete
workspace-relative path; patterns without a slash match its final component. An exception below an
ignored directory keeps the directory traversable, even if the exception's target is absent. Rule
decisions and pruning are separate: an ignored parent can remain a traversal candidate. `initial_excludes`
defaults to `.bzr` metadata. Named regex capture groups are normalized to non-capturing groups and
reported as diagnostics; malformed regexes raise `BreezyIgnoreError`. The policy does not inspect
versioned membership. All 36 boolean candidates, including exact-path versus `/**` strong exclusions,
`BRZ_HOME` global-ignore discovery, negative lookahead, and scoped inline regex flags, are compared
with Breezy 3.3.24 on macOS arm64 and Linux aarch64; 33 are captured on Linux x86_64 and Windows
Server 2025 x86_64. Native winning-pattern probes establish regular source order as global ignores,
built-in defaults, then branch `.bzrignore` on macOS arm64 and Linux aarch64. Both profiles also
reject `RE:(?i)foo` with a native invalid-pattern error, despite the published pattern guide showing
that form. Other regex, global-config, and platform behavior remain open; see the
[Breezy oracle notes](tests/oracles/breezy/README.md) and [Breezy pattern
reference](https://www.breezy-vcs.org/doc/en/user-reference/patterns-help.html).

### Fossil matching

Choose Fossil explicitly to evaluate its effective `ignore-glob` setting. The policy discovers the
checkout root from `_FOSSIL_` or `.fslckout`, asks Fossil for the effective setting (including its
versioned/local/global precedence), and evaluates patterns locally with SQLite `GLOB` semantics:

```python
from gitignore_walk import FossilPolicyConfig, select_policy

selection = select_policy("/path/to/fossil/checkout", FossilPolicyConfig())
for decision in selection.policy.explain_many(["build/output.tmp", "src/main.py"]):
    print(decision.path, decision.ignored, decision.pattern)
```

Fossil patterns match complete workspace-relative paths; `*` may cross `/`. ASCII whitespace and
commas separate patterns; Unicode whitespace remains pattern data. Quoted patterns can contain
those separators, `#` is ordinary pattern
data, and a backslash does not escape those separators. Patterns are additive with no `!` negation.
Ignored directory matches can be pruned. The default baseline excludes Fossil checkout markers from
included walks; `selection="ignored"` and `selection="all"` can still return those marker files.
Native `fossil extras` output agrees with included and ignored selections for the captured untracked
traversal fixture. Decisions report ignore-rule matches independently from tracked membership. To
query file membership as well, opt in with `FossilPolicyConfig(membership_aware=True)`; this reads
Fossil's structured JSON directory and checkout-status results. Membership remains `None` for
directories, which Fossil does not track as files. This initial implementation matches 41 boolean
candidates on Fossil 2.28/macOS arm64, 2.26/Linux aarch64 and
x86_64, and 2.23/Ubuntu 24.04 x86_64. Captured probes cover range classes, Unicode `?`, case
sensitivity, class-negation markers, unmatched brackets, and Unicode whitespace inside and around
patterns. Other tokenizer boundaries and broader
platform/client coverage remain open. Membership-aware walks keep scheduled additions, edits,
renames, and missing tracked paths separate from ignored unversioned files in both top-down and
bottom-up traversal. The default Fossil config also keeps `.fslckout` and `_FOSSIL_` out of included
results; pass `initial_excludes=()` to replace that baseline when the checkout marker should be
yielded. See
the [Fossil glob documentation](https://fossil-scm.org/home/doc/trunk/www/globs.md) and
[oracle notes](tests/oracles/fossil/README.md).

The property behavior follows Subversion's documented distinction: `svn:ignore` applies to
children of its directory, while `svn:global-ignores` applies through the directory's subtree. Both
properties use additive filename globs; they do not use Git's `!` negation syntax. See the
[Subversion ignore-property documentation](https://subversion.apache.org/blog/2013-06-26-repository-dictated-configuration-part-3-global-ignores.html).
The policy also asks `svn proplist --show-inherited-props` for `svn:global-ignores` inherited from
repository ancestors above the working-copy root; the source URL is retained in each decision.

```python
from gitignore_walk import IgnoreWalker, SubversionPolicyConfig, select_policy

selection = select_policy(
    "/path/to/subversion/working-copy",
    SubversionPolicyConfig(
        config_dir="/path/to/svn-config",
        global_ignores=["*.local-cache"],
    ),
)
walker = IgnoreWalker(selection.policy.root, policy=selection.policy)

for decision in selection.policy.explain_many(["build/output.tmp", "src/main.py"]):
    print(decision.path, decision.ignored, decision.source, decision.property_name)
```

`config_dir` is passed to native `svn` commands and overrides standard system/user config sources;
its `config` file supplies `[miscellany] global-ignores` when present. Without it, the policy reads
standard system and per-user INI files in native precedence order and Windows Registry values on
Windows. If no discovered config defines `global-ignores`, Subversion's built-in default pattern list
is used; an explicit empty value disables that list. The `global_ignores` field adds patterns to the
effective configured or built-in set.

Calling `select_policy(root)` is equivalent to passing `PortablePolicyConfig()`. Existing policy
constructors and the walker's portable default are unchanged.

`environment` is a complete environment, not an overlay. Both the selector and `GitIgnorePolicy`
use supplied HOME/USERPROFILE and XDG_CONFIG_HOME for conventional global ignores without consulting
ambient variables. An explicit environment without these locations has no conventional global file.
Omitting the portable policy's environment retains its existing ambient discovery behavior.

Fallback handles ancestor/nested `.gitignore`, discoverable `info/exclude`, and conventional global
ignores. It **does not read Git configuration**, including custom `core.excludesFile` or includes,
so its results can differ from native Git. Use strict Git mode when these settings are required.

### Mercurial matching

Choose Mercurial explicitly when evaluating a Mercurial workspace. By default, this uses the bundled
Python policy without launching `hg`; `read_client_config=True` opts into a read-only config query:

```python
from gitignore_walk import IgnoreWalker, MercurialPolicyConfig, select_policy

selection = select_policy(
    "/path/to/mercurial/checkout",
    MercurialPolicyConfig(read_client_config=True),
)
walker = IgnoreWalker(selection.policy.root, policy=selection.policy)

for decision in selection.policy.explain_many(["build/output.txt", "docs/guide.md"]):
    print(decision.path, decision.ignored, decision.source, decision.line, decision.scope)
```

Mercurial ignore matching is local and portable by default. Set `membership_aware=True` when
constructing `MercurialPolicyConfig` to make read-only `hg status --all --unknown --ignored -0`
queries annotate known file membership as `"versioned"` or `"unversioned"`; rule matching remains
independent of that annotation. Membership-aware walks select versioned paths as included even when
they match `.hgignore`, and they keep ignored-only selection for ignored unversioned paths. This
option requires the `hg` executable and a real working copy.
Paths omitted by native status remain unknown. Each direct query, batch, or walk uses one captured
status snapshot.

The policy discovers the enclosing `.hg` workspace, reads its root `.hgignore`, and loads any
additional files passed with `ignore_files`. Relative extra-file paths are resolved from the
workspace root. With `read_client_config=True`, Mercurial's `hg config --debug ui` command discovers
the effective configured files and their order; this requires the `hg` executable, while rule
matching remains local and portable. Relative configured paths use the workspace root, and `~` paths
use the discovery environment's home directory. Membership is not queried unless
`membership_aware=True`; even then, an ignored match does not imply that a path is absent from
version control. `initial_excludes` is a walker baseline and
defaults to excluding `.hg` metadata.
Walks also stop at nested `.hg` workspaces, matching parent-repository status enumeration.

Mercurial rules are additive: `!` is not a negation operator. Because this implementation does not
support inclusion exceptions, an ignored directory can be pruned safely. Missing include sources
produce diagnostics and set `discovery_complete=False`; include cycles are reported without
recursing indefinitely. Unsupported or malformed patterns raise `MercurialIgnoreError`.

Mercurial's matcher treats regexes and glob wildcards as bytes. The portable evaluator encodes paths
as UTF-8 with `surrogateescape`: regex `\w`/`\d` classes and case-insensitive matching stay
byte-oriented, and glob `?` consumes one byte. For example, a single `?` does not match the
two-byte UTF-8 spelling of `é`, while `??` does; literal UTF-8 patterns still match. Python's
Unicode-only `(?u)` regex flag is rejected, matching Mercurial's byte regex mode.

The implementation is compared with captured Mercurial 7.2.4/macOS arm64, 7.0.1/Linux aarch64 and
x86_64, and 7.1.2/Windows Server 2025 x86_64 profiles for path matching and ignored-file walking.
The Windows capture has five path skips and one symlink-dependent walk skip; those cases are not
claimed as conformance. The four-profile corpus is still limited evidence, not full cross-platform
certification. See the [oracle notes](tests/oracles/hg/README.md) for exact results and limitations.

### Sapling and Jujutsu matching

`SaplingPolicyConfig` and `JujutsuPolicyConfig` select policies for the captured Git-compatible
ignore behavior. Both reuse the Git ignore matcher while resolving each system's workspace markers
and supported sources separately. Ignore-only queries are client-independent; each scheme can
optionally query native data for version-control membership:

- Sapling discovers the nearest `.sl` or `.git` workspace. `.sl` mode reads workspace `.gitignore`
  files only. `.git` mode also reads XDG Git ignores and `.git/info/exclude`.
- `SaplingPolicyConfig(membership_aware=True)` runs read-only `sl status --all --print0`. It
  reports known versioned and unversioned membership separately from ignore matches. Status-omitted
  paths remain unknown; the option requires Sapling to be installed.
- `JujutsuPolicyConfig(membership_aware=True)` runs `jj --ignore-working-copy file list` so it
  reads the saved working-copy tree without snapshotting filesystem changes. Saved-tree files are
  versioned; present files absent from that tree are unversioned; absent unlisted paths and
  directories remain unknown. This option requires Jujutsu to be installed.
- Jujutsu discovers the nearest `.jj` workspace. Both colocated and non-colocated modes read
  workspace `.gitignore` files and XDG Git ignores. A colocated `.git/info/exclude` is read when
  present; an outer Git repository's exclude file is not inherited.
- In a linked Git worktree, Git and Sapling `.git` mode use the shared Git directory's
  `info/exclude`; colocated Jujutsu uses that worktree's own Git directory. Native captures cover
  the three clients on macOS arm64 and Debian 13 Linux arm64/x86_64.
- When all three source levels are present, workspace `.gitignore` overrides `.git/info/exclude`,
  which overrides the XDG ignore file.
- Native captures also confirm that Sapling `.git` mode and both Jujutsu modes honor a custom
  `core.excludesFile`; Sapling `.sl` mode does not. Pass the resolved ignore-file path as
  `global_excludes_file` to the corresponding policy config, or set `read_git_config=True` to ask
  the configured Git executable to resolve system/user settings and their included files. The
  user setting overrides the system setting; when neither exists, discovery uses the XDG default.
  An explicitly empty setting disables the global source. A repository-local setting overrides
  system and user values. Native captures also cover `gitdir`, `onbranch:main`, matching
  `hasconfig:remote.*.url` conditional includes, and repository-local precedence. For
  non-colocated Jujutsu, the policy uses the workspace's internal Git store as condition context
  unless the caller supplies `GIT_DIR`. That caller context affects the Git config lookup; native
  Sapling and Jujutsu probes kept their workspace context and did not apply a `gitdir` include
  selected by the alternate `GIT_DIR`. Git documents config scope and include behavior in
  [git-config](https://git-scm.com/docs/git-config), and ignore precedence in the
  [Git ignore documentation](https://git-scm.com/docs/gitignore).

Native live checks also cover Git's environment-injected `GIT_CONFIG_COUNT` entries. Sapling `.git`
mode and both Jujutsu modes honor an injected `core.excludesFile`, while Sapling `.sl` mode ignores
Git config. With `read_git_config=True`, the policy uses Git's config resolver and follows the same
environment-provided value.

Conditional include support follows the configured Git executable's version. Git 2.56 added
`worktree:` includes and supports their case-insensitive `worktree/i:` form. The captured Sapling
`.git` mode honors both; Jujutsu 0.47.1 does not honor either natively in colocated mode. With
`read_git_config=True` and Git 2.56 or newer, the Jujutsu policy follows Git's resolved
`core.excludesFile`, so those cases can differ from native Jujutsu. See the
[compatibility oracle notes](tests/oracles/compat/README.md) for versioned captures and exact
results.

The captured pattern matrix also covers directory-level negation barriers, child re-inclusion,
workspace-root anchoring, and recursive `**`; both policy decisions and walker selections match the
captured native results for those cases.

Jujutsu changed how it reads in-tree `.gitignore` symlinks in version 0.46.0. Captures show that
0.45.1 follows a nested symlinked `.gitignore`, while 0.46.0 and 0.47.1 skip it. The policy defaults
to the 0.46.0+ behavior. To match Jujutsu 0.45.1, set
`follow_symlinked_gitignore=True` in `JujutsuPolicyConfig`; the read-only policy does not invoke
`jj` to detect the client's version. The release change is documented in the
[Jujutsu 0.46.0 notes](https://github.com/jj-vcs/jj/releases/tag/v0.46.0); the versioned native
captures and reproduction command are in the [compatibility oracle notes](tests/oracles/compat/README.md).

Enable Git system/user config discovery when you need the configured `core.excludesFile`:

```python
from gitignore_walk import JujutsuPolicyConfig, select_policy

selection = select_policy(
    "/path/to/jujutsu/checkout",
    JujutsuPolicyConfig(read_git_config=True, git_executable="git"),
)
```

This runs `git config` during selection; lookup failures raise `GitIgnoreError`. Set
`global_excludes_file` instead when the caller already knows the effective path, avoiding the Git
executable requirement.

The caller's root remains the query and traversal bound, while `workspace_root` reports the
discovered VCS root. The default walker baseline excludes `.sl` or `.git` for Sapling, depending on
storage mode, and `.jj` for Jujutsu. By default, these policies do not query versioned membership or
read Git config. Both can query membership with `membership_aware=True`; Jujutsu reads its saved tree
without invoking the snapshotting status command. Git config discovery requires
`read_git_config=True` and Git. The captured behavior covers Sapling 0.2.20261103 and
Jujutsu 0.47.1 on macOS arm64 and Debian 13 Linux arm64/x86_64.
The full native capture and limitations are in the
[compatibility oracle notes](tests/oracles/compat/README.md).

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

`IgnoreDecision` identifies the `scheme`, final `ignored` result, source and matched rule. It can
also carry a source `line` or `property_name`, effective `scope`, policy-defined `reason`, optional
`membership` (`"versioned"`, `"unversioned"`, or `None` when unknown), and non-fatal discovery
`diagnostics`. `discovery_complete` tells callers whether all applicable sources were found. Git
policies identify their scheme as `"git"`; Mercurial uses `"mercurial"`. Mercurial
source discovery failures remain visible as diagnostics and incomplete discovery.
`ignored` describes the scheme's ignore-rule result, not version-control membership or add/commit
eligibility. Git-native queries use `--no-index`, so tracked paths are still evaluated against rules.

For overlay diagnostics, use `policy.trace(path)`. It returns the effective decision and the
matching rule from each applicable source in precedence order, with `effective=True` on the rule
that determined the result. The portable policy traces its configured layers and parent-directory
blocking rules. `GitStandardPolicy` reports Git's winning rule, but sets `complete=False` because
Git's check-ignore interface does not expose every shadowed matching rule. This trace completeness
flag is separate from `decision.discovery_complete`, which describes source discovery.

This distinction matters when explaining *why* a file was selected, not just whether it matched an
ignore rule.

## Choose a matching policy

| Capability              | Git portable      | Git-native     | Mercurial portable       | Subversion properties         | Perforce portable      |
| ----------------------- | ----------------- | -------------- | ------------------------ | ----------------------------- | ---------------------- |
| Requires VCS executable | No                | Git            | For config or membership | `svn`                         | No                     |
| Nested ignore sources   | `.gitignore`      | `.gitignore`   | `.hgignore` includes     | Directory properties          | `P4IGNORE` files       |
| Runtime/global config   | Conventional file | Git config     | Explicit or `hg config`  | Config directory and patterns | Explicit/environment   |
| Inherited rules         | Git precedence    | Git precedence | No                       | `svn:global-ignores`          | Nested file precedence |
| Batch matching          | Yes               | Yes            | Yes                      | Yes                           | Yes                    |
| Match explanations      | Yes               | Partial        | Yes                      | Yes                           | Yes                    |
| Filtered traversal      | Yes               | Yes            | Yes                      | Yes                           | Yes                    |

**Choose portable** when your application needs a self-contained matcher, may run outside
repositories, or needs predictable Python-only evaluation.

**Choose Git-native** when the user's Git configuration is part of the required behavior.

The policies have intentional compatibility differences. `GitStandardPolicy` never silently falls
back to portable matching.

## Traverse and filter directory trees

`IgnoreWalker` supports `os.walk`-style traversal:

```python
walker = IgnoreWalker("/path/to/project")

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

`walk()` yields `IgnoreWalkEntry` named tuples, supporting both named attributes and familiar
three-value unpacking.

`iter_files()` provides a simpler interface when only file paths are needed.

Git policies exclude `.git` files and directories by default. The Mercurial policy excludes `.hg`
metadata by default. `initial_excludes` replaces the active policy's baseline: use
`initial_excludes=()` to remove it, or include the matching metadata directory with any other hard
exclusions. Use `selection="all"` to bypass ignore filtering. Other hidden files follow the active
policy.

Ignored-only traversal still visits necessary unignored parents to locate ignored descendants. Its
filtered directory list does not control pruning.

## Matching and lower-level APIs

All policies support individual and batch queries:

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

| API                                                   | Purpose                                                                        |
| ----------------------------------------------------- | ------------------------------------------------------------------------------ |
| `SubversionIgnorePolicy`                              | Native discovery and evaluation of Subversion ignore properties                |
| `SubversionPolicyConfig`                              | Explicit Subversion selection and runtime config options                       |
| `SubversionIgnoreError`                               | Report native Subversion discovery or execution failures                       |
| `BreezyIgnorePolicy`                                  | Local Breezy rule evaluation with native built-in-rule discovery               |
| `BreezyPolicyConfig`                                  | Explicit Breezy selection and client/configuration options                     |
| `BreezyIgnoreError`                                   | Report Breezy rule-source, parse, and client failures                          |
| `DarcsBoringPolicy`                                   | Native, membership-aware Darcs boring-candidate evaluation                     |
| `DarcsPolicyConfig`                                   | Darcs client, environment, timeout, and walker-baseline selection              |
| `DarcsPolicySelection`                                | Typed result identifying the Darcs native candidate backend                    |
| `DarcsBoringError`                                    | Report Darcs native candidate or managed-path discovery failures               |
| `PerforceIgnorePolicy`                                | Evaluate the supported P4IGNORE subset within a caller-selected traversal root |
| `PerforcePolicyConfig`                                | Explicit selection, source-list, client-root, and client-view options          |
| `PerforcePolicySelection`                             | Typed result identifying the selected Perforce policy and backend              |
| `PerforceIgnoreError`                                 | Report Perforce source, pattern, configuration, and workspace errors           |
| `MercurialIgnorePolicy`                               | Portable Mercurial `.hgignore` evaluation                                      |
| `MercurialPolicyConfig`                               | Mercurial selection with extra paths or opt-in native config discovery         |
| `select_policy(root, config)`                         | Select a tagged built-in scheme and backend                                    |
| `MercurialIgnoreError`                                | Report Mercurial source, pattern, and config-discovery errors                  |
| `SaplingPolicyConfig(membership_aware=True)`          | Opt into native Sapling versioned/unversioned membership queries               |
| `SaplingIgnoreError`                                  | Report Sapling native membership query failures                                |
| `JujutsuPolicyConfig(membership_aware=True)`          | Opt into read-only Jujutsu saved-tree membership queries                       |
| `JujutsuIgnoreError`                                  | Report Jujutsu native membership query failures                                |
| `is_gitignored(root, target)`                         | Portable one-shot query                                                        |
| `parse_gitignore(lines, source=...)`                  | Parse ignore rules into an immutable `GitIgnoreSpec`                           |
| `matches_gitignore(spec, relative, is_directory=...)` | Evaluate a parsed specification                                                |
| `IgnoreWalker.walk()`                                 | Directory traversal with optional filtering                                    |
| `IgnoreWalker.iter_files()`                           | File-only traversal                                                            |
| `IgnorePolicy.explain_many()`                         | Return a mutable list of detailed decisions                                    |
| `IgnorePolicy.is_ignored_many()`                      | Return a mutable list of ignore decisions                                      |
| `IgnorePolicy.iter_explain()`                         | Lazily yield detailed decisions                                                |
| `IgnorePolicy.iter_ignored()`                         | Lazily yield ignore decisions                                                  |

All built-in policies implement `IgnorePolicy`. Lazy methods consume targets as they run: Git's
portable policy caches each ignore file when first read, the Mercurial policy reads one source
snapshot per lazy iteration, and the Git-native policy queries up to `batch_size` targets per Git
process (256 by default). New query operations observe changed ignore sources; no mode freezes the
filesystem.

`IgnoreWalker` asks its policy whether an ignored directory is safe to prune. The policy contract
defaults to keeping it traversable, since another ignore scheme may allow included descendants.
Policies can also stop descent at scheme-specific workspace boundaries independently of whether a
directory matches an ignore rule.

## Important behavior

A few details are worth knowing before integrating the library:

**Roots and paths.** Relative queries use the policy root. Missing targets are allowed. Targets
outside that root are rejected, and unknown nonexistent targets are treated as files.

**Baseline exclusions.** Each policy treats `initial_excludes` as hard exclusions. A positive
baseline match cannot be overridden by scheme rules.

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
