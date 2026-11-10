# Sapling and Jujutsu compatibility probes

These probes create disposable workspaces and exercise the current Sapling and Jujutsu clients.
They distinguish repository storage modes from ignore dialects; they do not mutate the checkout
running the oracle.

Run from the repository root:

```sh
python -m scripts.ci oracle-compat --output /tmp/vcs-compat.json
```

The native captures use Sapling 0.2.20261103 and Jujutsu 0.47.1 on macOS 26 arm64 and Debian 13
Linux aarch64 and x86_64. The Linux profiles download upstream release assets and verify their SHA-256
digests before running them in isolated Debian containers. Each profile checks four layouts: Sapling
with `.git`, Sapling with `.sl`, colocated Jujutsu with `.git` and `.jj`, and non-colocated Jujutsu
with `.jj` only. In all four layouts, `.gitignore` excludes `a.tmp`, while
`.hgignore` and `.jjignore` do not exclude `b.log`. This supports using the existing Git-ignore
policy for the tested in-tree rule subset, with a caller-selected metadata baseline such as
`.sl` or `.jj`.

Jujutsu 0.47.1 is also captured on Windows Server 2025 x64 in colocated and non-colocated modes.
Both Windows cases match the same candidates, global-source precedence, path-pattern matrix, and
the `gitdir/i`, `worktree`, `worktree/i`, `onbranch`, and `hasconfig:remote.*.url` include probes.
Sapling's pinned Windows release aborts during `sl status` with `cannot set file timestamp to 0`,
so this profile does not claim Sapling Windows conformance.

The isolated source probes also capture that Sapling in `.git` mode reads the XDG Git ignore file
and `.git/info/exclude`; Sapling `.sl` mode reads neither. Jujutsu reads the XDG Git ignore file in
both modes and reads `.git/info/exclude` only when colocated. In modes with all three sources,
`.gitignore` overrides `.git/info/exclude`, which overrides the XDG ignore file. These observations
are captured against both named client versions on macOS and Debian Linux aarch64 and x86_64.
They do not establish path encoding or broader VCS behavior.

The captures also probe system and user `core.excludesFile` settings. Each disposable home has the
default XDG ignore file (`*.global`), a system ignore file (`*.system`), and a `~/.gitconfig` that
includes another config file selecting a user ignore file (`*.custom`). Sapling `.git` mode and both
Jujutsu modes prefer the user file when set, then use the system file, then the XDG default. An
explicitly empty user setting disables the global source. Sapling `.sl` mode ignores all three.
These results are captured on macOS arm64 and Debian 13 Linux aarch64 and x86_64. The policies expose
`global_excludes_file` for an already resolved path; with `read_git_config=True`, they use the
configured Git executable to resolve the effective setting with Git's scope precedence and
includes. A separate isolated workspace sets `GIT_CONFIG_GLOBAL` before initialization and confirms
that Sapling `.git` mode and both Jujutsu modes use that alternate file, while Sapling `.sl` does
not. `read_git_config=True` follows the environment-selected file because it delegates config
resolution to Git. These observations are captured on macOS arm64 and Debian 13 Linux aarch64 and
x86_64, including a separate Git 2.56 profile; Windows captures the same behavior for both Jujutsu
modes. A repository-local `core.excludesFile` overrides system and user values in
Sapling `.git` mode and both Jujutsu modes; Sapling `.sl` ignores Git config. A `gitdir` conditional
include selects the user file in Sapling `.git` mode and colocated Jujutsu; non-colocated Jujutsu
follows the configured system source for that condition. Both `onbranch:main` and a matching
`hasconfig:remote.*.url` include are honored by Sapling `.git` mode and both Jujutsu modes. The
policy supplies Jujutsu's internal Git store as context for non-colocated workspaces;
caller-provided `GIT_DIR` still takes precedence for the Git config lookup. A separate native probe
shows that Git resolves a matching include for that caller context while Sapling and Jujutsu keep
using their own workspace context and leave the probe visible. This divergence is captured on macOS
and Debian Linux; Windows CI asserts it for both Jujutsu modes. Other conditional forms and
client/platform profiles remain open.

The conditional-include matrix also exercises `gitdir/i` with an uppercase `WORKSPACE/.GIT`
pattern against the lowercase disposable workspace path. On macOS 26 arm64, the case matches for
Sapling `.git` mode and colocated Jujutsu, and does not match Sapling `.sl` or non-colocated
Jujutsu. Linux and Windows captures are checked by native CI; committed Linux captures are kept
alongside this probe when recaptured. Git documents `gitdir/i` as `gitdir` matching without case
sensitivity ([Git config documentation](https://git-scm.com/docs/git-config#_conditional_includes)).

Git 2.56 added `worktree:` conditional includes and supports the case-insensitive `worktree/i:`
form. The Git 2.56.0/macOS arm64 capture shows Git resolving both conditional global ignores and
Sapling `.git` mode honoring them. Jujutsu 0.47.1 colocated mode leaves both probes visible even
though Git 2.56 resolves `core.excludesFile` to the included files; non-colocated mode does not
match because its internal Git store is bare. Therefore `read_git_config=True` can differ from
Jujutsu's own interpretation for these newer include types: it follows the configured Git
executable, as the option specifies. Git's release notes record the feature addition in
[v2.56.0](https://github.com/git/git/blob/v2.56.0/Documentation/RelNotes/2.56.0.adoc).

A second native pattern matrix checks four cases on each mode: a file negation cannot reopen an
ignored parent directory; a child negation can re-include a file when only the parent's contents
are ignored; `/root-only.tmp` is anchored to the workspace root; and `**/deep.log` matches a nested
path. All four Sapling/Jujutsu mode results match these candidates. The portable policy tests replay
the same rules through both direct explanations and included/ignored walker selections. These cases
match on macOS arm64 and Debian 13 Linux aarch64 and x86_64. This remains a small compatibility
subset, not broad Git-dialect certification.

Jujutsu's `status` command snapshots the working copy. The probes run it only in disposable
repositories, then inspect the resulting file list. This is not a safe per-file adapter strategy for
an existing workspace. A Jujutsu-specific native policy should not call status on user repositories
without a separate read-only inventory interface.

The capture supports the initial read-only `SaplingIgnorePolicy` and `JujutsuIgnorePolicy` scopes.
The policies evaluate the captured Git-compatible rule dialect locally and do not invoke either
client. Git-native selection remains appropriate only when an actual `.git` repository is available.

| Capture file                                                     | Environment                | Sapling      | Jujutsu |
| ---------------------------------------------------------------- | -------------------------- | ------------ | ------- |
| `sapling-0.2.20261103-jj-0.47.1-macos-arm64.json`                | macOS 26 arm64             | 0.2.20261103 | 0.47.1  |
| `sapling-0.2.20261103-jj-0.47.1-debian13-arm64.json`             | Debian 13 arm64 in Docker  | 0.2.20261103 | 0.47.1  |
| `sapling-0.2.20261103-jj-0.47.1-debian13-x86_64.json`            | Debian 13 x86_64 in Docker | 0.2.20261103 | 0.47.1  |
| `sapling-0.2.20261103-jj-0.47.1-git-2.56.0-debian13-x86_64.json` | Debian 13 x86_64 in Docker | 0.2.20261103 | 0.47.1  |
| `sapling-0.2.20261103-jj-0.47.1-git-2.56.0-macos-arm64.json`     | macOS 26 arm64             | 0.2.20261103 | 0.47.1  |
| `jj-0.47.1-windows-x64.json`                                     | Windows Server 2025 x64    | —            | 0.47.1  |
