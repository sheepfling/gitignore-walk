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
`.sl` or `.jj`; it does not establish config-file, global-exclude, path-encoding, or broader VCS
behavior.

Jujutsu's `status` command snapshots the working copy. The probes run it only in disposable
repositories, then inspect the resulting file list. This is not a safe per-file adapter strategy for
an existing workspace. A Jujutsu-specific native policy should not call status on user repositories
without a separate read-only inventory interface.

The capture is exploratory evidence, not a new Sapling or Jujutsu policy. The existing portable
Git-ignore policy can be selected directly for a caller who wants the tested in-tree rule subset;
Git-native selection remains appropriate only when an actual `.git` repository is available.
