# Sapling and Jujutsu compatibility probes

These probes create disposable workspaces and exercise the current Sapling and Jujutsu clients.
They distinguish repository storage modes from ignore dialects; they do not mutate the checkout
running the oracle.

Run from the repository root:

```sh
python -m scripts.ci oracle-compat --output /tmp/vcs-compat.json
```

The current capture uses Sapling 0.2.20261103 and Jujutsu 0.47.1 on macOS arm64. It checks four
layouts: Sapling with `.git`, Sapling with `.sl`, colocated Jujutsu with `.git` and `.jj`, and
non-colocated Jujutsu with `.jj` only. In all four layouts, `.gitignore` excludes `a.tmp`, while
`.hgignore` and `.jjignore` do not exclude `b.log`. This supports using the existing Git-ignore
policy for the tested in-tree rule subset, with a caller-selected metadata baseline such as
`.sl` or `.jj`.

The isolated source probes also capture that Sapling in `.git` mode reads the XDG Git ignore file
and `.git/info/exclude`; Sapling `.sl` mode reads neither. Jujutsu reads the XDG Git ignore file in
both modes and reads `.git/info/exclude` only when colocated. In modes with all three sources,
`.gitignore` overrides `.git/info/exclude`, which overrides the XDG ignore file. These observations
are captured with Sapling 0.2.20261103 and Jujutsu 0.47.1. They do not establish alternate global
config files, path encoding, or broader VCS behavior.

A second native pattern matrix checks four cases on each mode: a file negation cannot reopen an
ignored parent directory; a child negation can re-include a file when only the parent's contents
are ignored; `/root-only.tmp` is anchored to the workspace root; and `**/deep.log` matches a nested
path. All four Sapling/Jujutsu mode results match these candidates. The portable policy tests replay
the same rules through both direct explanations and included/ignored walker selections. The capture
is still one macOS arm64 client profile, not broad cross-platform Git-dialect certification.

Jujutsu's `status` command snapshots the working copy. The probes run it only in disposable
repositories, then inspect the resulting file list. This is not a safe per-file adapter strategy for
an existing workspace. A Jujutsu-specific native policy should not call status on user repositories
without a separate read-only inventory interface.

The capture supports the initial read-only `SaplingIgnorePolicy` and `JujutsuIgnorePolicy` scopes.
The policies evaluate the captured Git-compatible rule dialect locally and do not invoke either
client. Git-native selection remains appropriate only when an actual `.git` repository is available.
