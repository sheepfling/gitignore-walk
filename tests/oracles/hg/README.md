# Mercurial native oracle

`cases.json` contains candidate behaviors derived from the implementation research handoff. The
candidate values are hypotheses until they are compared with a captured Mercurial result. Open
questions have no guessed expected boolean.

Run the probes from the repository root:

```sh
python tests/oracles/hg/run.py
```

To use the shared local/CI command and choose a capture path:

```sh
python -m scripts.ci oracle-hg \
  --output /tmp/hg-oracle.json \
  --walk-output /tmp/hg-walk-oracle.json
```

GitHub Actions runs this command in Ubuntu and Windows jobs with Mercurial installed and uploads
separate workflow artifacts. It records single-path `debugignore` observations and
`status --ignored` plus `status --unknown` file walks. The committed captures cover macOS arm64
Mercurial 7.2.4, Debian 13 Linux aarch64 and x86_64 Mercurial 7.0.1, and Windows Server 2025
x86_64 Mercurial 7.1.2. The original 48 path cases include case-sensitive glob
matching, Unicode normalization-form sensitivity, missing-source behavior, an external include
symlink, an undecodable byte in a glob pattern, and trailing-space behavior: glob rules trim trailing
spaces, while regexp
rules keep them. Regex cases also capture unanchored search, explicit start anchoring, and scoped
inline flags. Two additional source-boundary cases capture an include through a directory symlink
outside the workspace and a dangling symlink include. Mercurial follows the first; the second warns
and skips the source. The policy follows the valid external source and reports incomplete discovery
for the dangling source. These two cases are captured on macOS arm64 and Debian 13 Linux x86_64.
Seven regex probes cover lookahead, lookbehind, word boundaries, and backreferences. Captures on
macOS arm64 and Debian Linux aarch64 and x86_64 agree with the byte-regex evaluator; the live-client
differential test also exercises these cases.
An unreadable
included file is skipped by native Mercurial with a warning; the
policy reports `discovery_complete=False` with a source-unavailable diagnostic. Config discovery
fixtures cover named entries, home-relative paths, repository configuration, and an included
`.hg/hgrc` file. Eight additional byte-semantics cases are captured on Mercurial 7.2.4/macOS arm64
and Mercurial 7.0.1/Debian 13 Linux aarch64 and x86_64. They show regex character classes and case
folding are byte-oriented, UTF-8 literals still match, and glob `?` consumes one byte of a multi-byte
UTF-8 path. The test suite also compares these patterns directly with the installed native client on
each client-enabled CI profile; the Windows committed capture still contains the original 48 cases.
The full Mercurial test module passes in Debian 13 Linux aarch64 and x86_64 containers.

The reviewed Windows capture is committed in `results/hg-7.1.2-windows-x86_64.json`: all 42
candidate comparisons match, with no differing candidate results. The include-cycle observation
remains the documented safe divergence. Five path probes are explicitly skipped for POSIX-only byte
names, reserved/backslash filenames, symlinked ignore sources, and POSIX unreadable-file
permissions. The walk capture is in
`results/hg-walk-7.1.2-windows-x86_64.json`; five fixtures match and the repeated-source-under-two-
symlink-scopes fixture is skipped because this Mercurial-on-Windows profile does not read its
symlinked ignore source. The Windows profile adds cross-platform evidence, but these skips leave
the corresponding behaviors unverified on Windows.

The `oracle-hg` command also probes repository-config trust on POSIX. It creates a temporary
repository whose `.hg/hgrc` enables one ignore file, observes the file as owned by the
executing user, then changes its owner to root and repeats the native and library probes. This checks
that opt-in `ui.ignore` discovery uses Mercurial's effective trusted configuration. On Linux hosted
CI, the workflow uploads this as `hg-trust-oracle.json`; Windows records the trust probe as skipped
because Mercurial's ownership trust rule is POSIX-specific. A local non-root runner needs
passwordless `sudo` solely to make the repository config root-owned. Without that capability the
probe writes an explicit skipped capture and does not count as passing trust evidence. See the
[Mercurial configuration documentation](https://mercurial-scm.org/help/topics/config) for its
repository config trust rules.

The six walk fixtures cover
ignored-parent descendants, included rule sources,
subinclude scope (including one physical source reached through symlink aliases under two scopes),
and the distinction between a tracked path matching a rule and unknown paths listed by native
status. The job collects native observations for review; candidate differences and client
query errors remain visible in the capture and are not treated as implementation passes.

The runner creates a fresh temporary home, Mercurial config, and repository for each case. It sets
`HGRCPATH`, `HGPLAIN`, and `LC_ALL`, captures effective `ui.ignore` config output for opt-in
discovery cases, and writes the raw command output to the ignored
`capture.local.json`. Client failures and unmatched output remain visible per case; a missing client
is recorded as `skipped`, never as a pass. Do not run this oracle against a real working copy.

Committed files in `results/` retain normalized output, the client/platform profile, candidate
comparison, and hashes of the normalized stdout/stderr. Normalization only replaces the random
temporary repository and home paths. Raw local output is retained by the runner for auditing that
normalization.

`walk_cases.json` defines native ignored-file enumerations captured on macOS with Mercurial 7.2.4
and Debian 13 Linux on aarch64 and x86_64 with Mercurial 7.0.1. The corpus includes a nested
repository: parent-repository status does not enumerate files inside the child `.hg` workspace, so
the shared walker must stop at that boundary. The policy also treats the workspace root's `.hg`
metadata directory as non-traversable. The library comparison in `tests/test_mercurial.py` compares
all three profiles' untracked file paths. A separate Linux integration case creates a filename with
an undecodable byte and compares the walk with NUL-delimited native status; it skips filesystems,
such as the tested macOS filesystem, that reject the name. Tracked-file membership is asserted
separately because the policy reports ignore matching and does not query Mercurial's dirstate.

This oracle asks `hg debugignore` whether a single path matches ignore rules. It does not establish
tracked-file behavior, add/status behavior, traversal output, or compatibility with other Mercurial
versions. Forty-six boolean expectations and the structured invalid-syntax expectation agree on
each original captured profile. The eight added byte-semantics expectations also match in both
expanded captures. The include-cycle case has
no native candidate boolean because the client recurses until failure; the library detects the cycle
and returns an incomplete-discovery diagnostic as a safe divergence. In particular,
`hg.subinclude-rebases` reports the path as ignored and then exits with a source-formatting error.
The same scoped `rootglob` behavior is independently confirmed by `hg.walk.subinclude-scope` in
native `status --ignored` captures on all three profiles. The library therefore has direct
walk-level conformance evidence for this rule even though the single-path debug command crashes.
These command failures are client observations, not desired library behavior.
