# Sapling and Jujutsu compatibility probes

These probes create disposable workspaces and exercise the current Sapling and Jujutsu clients.
They distinguish repository storage modes from ignore dialects; they do not mutate the checkout
running the oracle.

Run from the repository root:

```sh
python -m scripts.ci oracle-compat --output /tmp/vcs-compat.json
```

To run the same disposable capture through the shared native summary, select `compat` explicitly:

```sh
python -m scripts.ci native --backends compat --output-dir .local/ci
```

This requires Git, Sapling (`sl`), and Jujutsu (`jj`) on `PATH`; it records both clients and the
platform in the shared `summary.json` while retaining this oracle's scheme-specific capture format.
Use `--sl <path>` and `--jj <path>` to select explicit or checksum-pinned executables instead of
the commands found on `PATH`.

The native captures use Sapling 0.2.20261103 and Jujutsu 0.47.1 on macOS 26 arm64, Debian 13
Linux aarch64 and x86_64, and Windows Server 2025 x64. Full Jujutsu 0.46.0 compatibility is retained
on Debian 13 x86_64. Full 0.45.1 captures are retained on macOS 26 arm64 and Debian 13 x86_64 for a
release-boundary comparison of nested `.gitignore` symlink handling. The Linux profiles
download upstream release assets and verify their SHA-256
digests before running them in isolated Debian containers. Each profile checks four layouts: Sapling
with `.git`, Sapling with `.sl`, colocated Jujutsu with `.git` and `.jj`, and non-colocated Jujutsu
with `.jj` only. In all four layouts, `.gitignore` excludes `a.tmp`, while
`.hgignore` and `.jjignore` do not exclude `b.log`. This supports using the existing Git-ignore
policy for the tested in-tree rule subset, with a caller-selected metadata baseline such as
`.sl` or `.jj`.

Sapling 0.2.20261028 has version-scoped Debian 13 arm64 and x86_64 captures for source, path-pattern,
and global-configuration behavior alongside Jujutsu 0.47.1. The Windows Server 2025 x64 capture
adds both Sapling storage modes and Jujutsu 0.47.1. On the Debian profiles, Sapling `.sl` mode
panics with `StripPrefixError` for each tested path-pattern group; the Windows capture also excludes
that group in the combined compatibility profile. Separate probes run both the 13-path and extended
`.sl` groups on Windows and Debian 13 arm64/x86_64. All three captures record the same
`StripPrefixError` panic with exit code 101; both observations have `native_status: "client-error"`
and `candidate_matches: null`. This is evidence of a client failure, not evidence that the candidate
patterns match. The captures are versioned as `sapling-0.2.20261028-sl-patterns-<platform>.json`.
The `.git` mode matches the full 13-path pattern matrix on both Linux and Windows. Every combined
profile marks
`sapling.sl-mode.pattern_discovery` in `excluded_probes`; Jujutsu's pattern probes and both clients'
source/configuration probes still run and match. Reproduce these captures with
`run.py --sl <older-sapling> --jj <jj> --skip-sapling-pattern-mode sl --output <capture.json>`.
The separate probes use `sapling_pattern_profile.py`; they run each pattern group in a disposable
workspace and normalize the process ID in the native panic text for stable fixtures. Linux CI runs
the probes inside checksum-verified Debian 13 containers; Windows CI downloads the checksum-pinned
release asset.
The full compatibility matrix remains excluded for this mode.

Sapling 0.2.20261103 is captured on Windows Server 2025 x64 in both `.git` and `.sl` modes alongside
Jujutsu 0.47.1. The candidate, source/configuration, and path-pattern probes match in both Sapling
modes. The symlink probe confirms Sapling `.sl` follows a nested `.gitignore` symlink while `.git`
mode skips it. The isolated capture home retains an empty `~/.gitconfig` so Sapling's Windows
timestamp translation works without adding any Git settings. Windows CI recaptures this profile
from a checksum-pinned Sapling release asset and retains the artifact for seven days.

Sapling 0.2.20261102 has a separate release-boundary profile for the `.gitignore` fix described in
its release notes. The four probes cover directory-only rules below missing and empty ignore files
and a nested ignore source below an empty parent. Both `.sl` and `.git` modes ignore all four paths
on Debian 13 ARM64 and Windows Server 2025 x64. The older 0.2.20261028 profile leaves these paths
visible in `.sl` mode; 0.2.20261103 preserves the fixed behavior. These captures establish this
specific fix across the tested releases and platforms, not full dialect conformance for 0.2.20261102.
The full compatibility matrix also matches Sapling 0.2.20261102 and Jujutsu 0.47.1 on Debian 13
ARM64 across both Sapling storage modes, both Jujutsu modes, source discovery, path patterns,
configuration, and symlink probes.

Jujutsu 0.45.1, 0.46.0, and 0.47.1 are captured on Windows Server 2025 x64 in colocated and
non-colocated modes. All three releases match the candidate, source/configuration, and path-pattern
probes. The versioned captures also establish that 0.45.1 follows nested symlinked `.gitignore`
files, while 0.46.0 and 0.47.1 skip them. Windows CI recaptures these profiles from checksum-pinned
release assets and retains the run artifacts for seven days.

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
modes. Native live tests also cover `GIT_CONFIG_COUNT`/`KEY_n`/`VALUE_n` injection for Sapling `.git`
and both Jujutsu modes; Sapling `.sl` remains isolated from Git config. A repository-local
`GIT_CONFIG_NOSYSTEM=1` probe with an explicit `GIT_CONFIG_SYSTEM` file confirms the system ignore
is suppressed in Sapling `.git`/`.sl` and both Jujutsu modes on macOS 26 arm64. The live policy test
compares this with `read_git_config=True`; Linux and Windows native jobs recapture the probe.
`core.excludesFile` overrides system and user values in
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

The native pattern matrix now checks 13 cases on each Sapling/Jujutsu mode: ignored-parent and
contents-only negation, root anchoring, recursive `**`, escaped leading `#` and `!`, zero-directory
`**/` matches, and `?` within a recursive component, including a nonmatching length control. All
four Sapling/Jujutsu mode results match the candidates. The portable policy tests replay the same
rules through direct explanations and included/ignored walker selections. Sapling/Jujutsu 0.47.1
matches on macOS arm64 and Debian 13 Linux aarch64/x86_64; Jujutsu 0.46.0 also matches on macOS
arm64 and Debian 13 x86_64. This remains a focused compatibility subset, not broad Git-dialect
certification.

An extended path probe adds a character-class range, a basename pattern matched below a nested
directory, and a directory-only pattern paired with a same-named file control. Sapling 0.2.20261103
and Jujutsu 0.47.1 match all five queried paths in both storage modes on macOS arm64; the native
capture is recorded in `results/sapling-0.2.20261103-jj-0.47.1-macos-arm64.json`. Jujutsu 0.45.1
also matches in both modes on macOS arm64, preserving evidence across the 0.46 symlink-behavior
release boundary. Windows captures match on Sapling 0.2.20261103 and Jujutsu 0.45.1, 0.46.0, and
0.47.1 in their respective storage modes. Debian 13 ARM64 and x86_64 captures match on Sapling
0.2.20261103/Jujutsu 0.47.1; the x86_64 captures also match on Jujutsu 0.45.1 and 0.46.0. These
results are incorporated into the versioned profiles. The portable policy and walker tests replay
the same cases.

A separate nested-source probe places `nested/.gitignore` as a symlink to an ignore file outside
the workspace. Sapling `.sl` mode follows the symlink and ignores `nested/probe.symlink`; Sapling
`.git` mode and both Jujutsu modes skip the symlinked ignore source and leave the candidate visible.
The portable policies now preserve this mode-specific behavior. Committed macOS and Debian 13 Linux
captures on aarch64 and x86_64 record all four native results. If a host cannot create the symlink,
the oracle records an explicit skip rather than claiming a match.

Jujutsu's behavior depends on its release. Version 0.45.1 follows the symlink in both modes;
version 0.46.0 changed to skip it, and 0.47.1 retains the new behavior. The policy defaults to the
0.46.0+ behavior. Set `JujutsuPolicyConfig(follow_symlinked_gitignore=True)` to model 0.45.1.
Focused macOS 26 arm64 and Debian 13 x86_64 captures for 0.45.1 and 0.46.0 are retained in
`results/`, and native CI recaptures the Linux cases. The full 0.45.1 captures also record the
global configuration and pattern probes on macOS arm64 and Debian 13 x86_64; Windows native CI now
recaptures and checks the full 0.45.1 and 0.46.0 matrices as artifacts, including the version
boundary where nested symlinked `.gitignore` files stopped being followed. Reproduce the focused
capture with
`run.py --jj <jj-executable> --symlink-only --output <capture.json>`; add
`--expect-jj-follows-symlink` for the 0.45.1 profile. Use that flag without `--symlink-only` to
capture the full older-client profile. The v0.46.0 [release notes](https://github.com/jj-vcs/jj/releases/tag/v0.46.0)
document this change. The official assets were SHA-256 verified before capture:
`jj-v0.45.1-aarch64-apple-darwin.tar.gz` (`51ba42e3d0682616f6eb015045bfe45289b396f03511f9897f645ce8e9272743`)
and `jj-v0.46.0-aarch64-apple-darwin.tar.gz`
(`43daa37ce0f9716cdf6fb65a29cbcae74a3160aef048cf3cb3d166d41cb4ab58`); the Linux x86_64 assets
use `f35438350b5d61963aac5dd74ede510b31d6b9690769d1a6268cf058cc825f72` and
`fce0271158e665ceb82dc66c5eb95b1728649094e9133074f3b5baece345fc08`, respectively.

Jujutsu's `status` command snapshots the working copy. The probes run it only in disposable
repositories, then inspect the resulting file list. This is not a safe per-file adapter strategy for
an existing workspace. A Jujutsu-specific native policy should not call status on user repositories
without a separate read-only inventory interface.

Nested-workspace probes separately test whether the parent client's file candidates cross into a
child workspace. Sapling stops at a nested workspace with the same storage marker (`.sl` or
`.git`) but traverses a child using the other marker. Jujutsu stops at nested `.jj` workspaces in
all colocated/non-colocated parent and child combinations. The portable walkers mirror these
boundaries and do not descend into `.jj`, `.sl` (for Sapling `.sl` mode), or `.git` metadata.
Captures cover Sapling/Jujutsu on macOS arm64 and Debian 13 Linux aarch64/x86_64; Jujutsu-only
captures are also recaptured on Windows Server 2025 x64 by CI. The Jujutsu matrix includes both
0.46.0 and 0.47.1 on macOS arm64 and Debian 13 x86_64, so the nested `.jj` boundary is checked
across the release that changed symlink handling as well as the current pinned release.

The captures support ignore evaluation in `SaplingIgnorePolicy` and `JujutsuIgnorePolicy`.
Ignore-only queries evaluate the captured Git-compatible rule dialect locally. Sapling's separate
opt-in membership query uses NUL-delimited `sl status --all`; Jujutsu's opt-in query reads
`jj file list` with `--ignore-working-copy` and does not snapshot the workspace. Git-native
selection remains appropriate only when an actual `.git` repository is available.

Linked Git worktrees expose a source-location difference. Git and Sapling `.git` mode read
`info/exclude` from the shared Git directory; colocated Jujutsu reads it from the linked worktree's
Git directory. The dedicated probe creates both files with distinct patterns and checks all three
clients against the same candidate set. This is captured on macOS arm64 and Debian 13 Linux
arm64/x86_64, plus Git/Jujutsu on Windows Server 2025 x64. The runner normalizes both temporary
path spellings and Jujutsu's generated change IDs. The Python policy tests assert that the
corresponding source directories remain scheme-specific.

| Capture file                                                               | Environment                | Sapling      | Jujutsu |
| -------------------------------------------------------------------------- | -------------------------- | ------------ | ------- |
| `linked-worktree-sapling-0.2.20261103-jj-0.47.1-macos-arm64.json`          | macOS 26 arm64             | 0.2.20261103 | 0.47.1  |
| `linked-worktree-sapling-0.2.20261103-jj-0.47.1-debian13-arm64.json`       | Debian 13 arm64 in Docker  | 0.2.20261103 | 0.47.1  |
| `linked-worktree-sapling-0.2.20261103-jj-0.47.1-debian13-x86_64.json`      | Debian 13 x86_64 in Docker | 0.2.20261103 | 0.47.1  |
| `linked-worktree-jj-0.47.1-macos-arm64.json`                               | macOS 26 arm64             | —            | 0.47.1  |
| `linked-worktree-jj-0.47.1-windows-x64.json`                               | Windows Server 2025 x64    | —            | 0.47.1  |
| `sapling-0.2.20261103-jj-0.47.1-macos-arm64.json`                          | macOS 26 arm64             | 0.2.20261103 | 0.47.1  |
| `sapling-0.2.20261103-jj-0.47.1-debian13-arm64.json`                       | Debian 13 arm64 in Docker  | 0.2.20261103 | 0.47.1  |
| `sapling-0.2.20261103-jj-0.47.1-debian13-x86_64.json`                      | Debian 13 x86_64 in Docker | 0.2.20261103 | 0.47.1  |
| `sapling-0.2.20261103-jj-0.47.1-windows-x64.json`                          | Windows Server 2025 x64    | 0.2.20261103 | 0.47.1  |
| `sapling-0.2.20261102-behavior-debian13-arm64.json`                        | Debian 13 arm64 in Docker  | 0.2.20261102 | —       |
| `sapling-0.2.20261102-behavior-windows-x64.json`                           | Windows Server 2025 x64    | 0.2.20261102 | —       |
| `sapling-0.2.20261102-jj-0.47.1-debian13-arm64.json`                       | Debian 13 arm64 in Docker  | 0.2.20261102 | 0.47.1  |
| `sapling-0.2.20261102-jj-0.47.1-debian13-x86_64.json`                      | Debian 13 x86_64 in Docker | 0.2.20261102 | 0.47.1  |
| `sapling-0.2.20261102-jj-0.47.1-windows-x64.json`                          | Windows Server 2025 x64    | 0.2.20261102 | 0.47.1  |
| `sapling-0.2.20261028-jj-0.47.1-debian13-arm64.json`                       | Debian 13 arm64 in Docker  | 0.2.20261028 | 0.47.1  |
| `sapling-0.2.20261028-jj-0.47.1-debian13-x86_64.json`                      | Debian 13 x86_64 in Docker | 0.2.20261028 | 0.47.1  |
| `sapling-0.2.20261028-jj-0.47.1-windows-x64.json`                          | Windows Server 2025 x64    | 0.2.20261028 | 0.47.1  |
| `sapling-0.2.20261028-sl-patterns-debian13-arm64.json`                     | Debian 13 arm64 in Docker  | 0.2.20261028 | —       |
| `sapling-0.2.20261028-sl-patterns-debian13-x86_64.json`                    | Debian 13 x86_64 in Docker | 0.2.20261028 | —       |
| `sapling-0.2.20261028-sl-patterns-windows-x64.json`                        | Windows Server 2025 x64    | 0.2.20261028 | —       |
| `sapling-0.2.20261103-jj-0.47.1-git-2.56.0-debian13-x86_64.json`           | Debian 13 x86_64 in Docker | 0.2.20261103 | 0.47.1  |
| `sapling-0.2.20261103-jj-0.47.1-git-2.56.0-macos-arm64.json`               | macOS 26 arm64             | 0.2.20261103 | 0.47.1  |
| `jj-0.47.1-windows-x64.json`                                               | Windows Server 2025 x64    | —            | 0.47.1  |
| `jj-0.46.0-windows-x64.json`                                               | Windows Server 2025 x64    | —            | 0.46.0  |
| `jj-0.45.1-windows-x64.json`                                               | Windows Server 2025 x64    | —            | 0.45.1  |
| `jj-0.45.1-macos-arm64.json`                                               | macOS 26 arm64             | —            | 0.45.1  |
| `jj-0.45.1-debian13-x86_64.json`                                           | Debian 13 x86_64 in Docker | —            | 0.45.1  |
| `jj-0.46.0-macos-arm64.json`                                               | macOS 26 arm64             | —            | 0.46.0  |
| `jj-0.46.0-debian13-x86_64.json`                                           | Debian 13 x86_64 in Docker | —            | 0.46.0  |
| `workspace-boundaries-sapling-0.2.20261103-jj-0.47.1-macos-arm64.json`     | macOS 26 arm64             | 0.2.20261103 | 0.47.1  |
| `workspace-boundaries-sapling-0.2.20261103-jj-0.47.1-debian13-arm64.json`  | Debian 13 arm64 in Docker  | 0.2.20261103 | 0.47.1  |
| `workspace-boundaries-sapling-0.2.20261103-jj-0.47.1-debian13-x86_64.json` | Debian 13 x86_64 in Docker | 0.2.20261103 | 0.47.1  |
| `workspace-boundaries-jj-0.46.0-macos-arm64.json`                          | macOS 26 arm64             | —            | 0.46.0  |
| `workspace-boundaries-jj-0.46.0-debian13-x86_64.json`                      | Debian 13 x86_64 in Docker | —            | 0.46.0  |
| `jj-0.45.1-macos-arm64-symlink.json`                                       | macOS 26 arm64             | —            | 0.45.1  |
| `jj-0.45.1-debian13-x86_64-symlink.json`                                   | Debian 13 x86_64 in Docker | —            | 0.45.1  |
| `jj-0.46.0-macos-arm64-symlink.json`                                       | macOS 26 arm64             | —            | 0.46.0  |
| `jj-0.46.0-debian13-x86_64-symlink.json`                                   | Debian 13 x86_64 in Docker | —            | 0.46.0  |
