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
x86_64 Mercurial 7.1.2. A hosted Ubuntu x86_64 capture records Mercurial 6.7.2 from the native
Linux CI job. The original 48 path cases include case-sensitive glob
matching, Unicode normalization-form sensitivity, missing-source behavior, an external include
symlink, an undecodable byte in a glob pattern, and trailing-space behavior: glob rules trim trailing
spaces, while regexp
rules keep them. Regex cases also capture unanchored search, explicit start anchoring, and scoped
inline flags. Two additional source-boundary cases capture an include through a directory symlink
outside the workspace and a dangling symlink include. Mercurial follows the first; the second warns
and skips the source. The policy follows the valid external source and reports incomplete discovery
for the dangling source. These two cases are captured on macOS arm64 and Debian 13 Linux x86_64.
The hosted Linux 6.7.2 profile has 64 matching boolean comparisons and a matching structured
invalid-syntax result; the nested-subinclude and include-cycle behaviors remain open native errors.
Its six captured walk fixtures all match.
Fourteen regex-extension probes cover lookaround, word boundaries, backreferences, newline matching,
and inline flags. All fourteen captures on macOS arm64, hosted Ubuntu x86_64, and Windows Server
2025 x86_64 agree with the evaluator. Debian 13's Mercurial 7.0.1 captures include eleven; the
three inline-flag probes are exercised by live-client differential tests but do not have versioned
Debian capture records.
Three additional probes cover the `a`, `L`, and `x` inline regex flags. Captures on Mercurial
7.2.4/macOS arm64, 6.7.2/hosted Ubuntu x86_64, and 7.1.2/Windows x86_64 match the evaluator: ASCII
and locale byte classes reject a UTF-8 non-ASCII letter under `LC_ALL=C`, while verbose mode accepts
whitespace and a trailing regex comment. Mercurial 7.1.2 on Windows matches the same `é` path with
`(?L)`; the policy reflects this platform result using Windows' active code page. All three cases
are included in live-client differential tests. Their versioned captures remain absent from Debian
13's Mercurial 7.0.1 profiles.
An unreadable
included file is skipped by native Mercurial with a warning; the
policy reports `discovery_complete=False` with a source-unavailable diagnostic. Config discovery
fixtures cover named entries, home-relative paths, repository configuration, and an included
`.hg/hgrc` file. Eight additional byte-semantics cases are captured on Mercurial 7.2.4/macOS arm64
and Mercurial 7.0.1/Debian 13 Linux aarch64 and x86_64. They show regex character classes and case
folding are byte-oriented, UTF-8 literals still match, and glob `?` consumes one byte of a multi-byte
UTF-8 path. The test suite also compares these patterns directly with the installed native client on
each client-enabled CI profile. The Windows capture now contains all 67 path cases, including the
additional byte-semantics and nested-subinclude failure probes.
An additional source-precedence probe gives `.hgignore` and a configured `ui.ignore` file the same
matching rule. On Mercurial 7.2.4/macOS arm64 and 7.0.1/Debian 13 Linux x86_64, native `debugignore`
attributes the decision to the workspace `.hgignore`; the policy trace retains both sources and
marks `.hgignore` effective. The captures are in the matching profile results.
The full Mercurial test module passes in Debian 13 Linux aarch64 and x86_64 containers.

The reviewed Windows capture is committed in `results/hg-7.1.2-windows-x86_64.json`: 60 closed
boolean comparisons and the structured invalid-syntax result match, with no differing closed
result; four path probes skip for platform constraints. The include-cycle observation remains the
documented safe divergence. The nested-subinclude case is also captured here: Mercurial raises
`AssertionError` when a `subinclude:` is reached through an included source, as it does on macOS
7.2.4 and hosted Linux 6.7.2. The portable policy still evaluates the nested source correctly. The
Unicode digit-class query
has no parseable
`debugignore` output on Windows, so the capture uses NUL-delimited native status membership to
confirm the unignored result. Four path probes remain explicitly skipped for POSIX-only byte names,
reserved/backslash filenames, and POSIX unreadable-file permissions. The Windows client emits
`skipping unreadable pattern file ...: Invalid argument` for file and directory symlink sources;
the library now marks those sources unavailable and leaves their paths unignored. The walk capture
is in `results/hg-walk-7.1.2-windows-x86_64.json`; all six fixtures match, including the repeated
source under two symlink scopes, whose paths remain unknown because Windows Mercurial does not read
the symlinked sources. The remaining skips leave POSIX-specific behavior unverified on Windows.

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

`walk_cases.json` defines native ignored-file enumerations captured on macOS with Mercurial 7.2.4,
hosted Ubuntu x86_64 with Mercurial 6.7.2, and Debian 13 Linux on aarch64 and x86_64 with
Mercurial 7.0.1. The corpus includes a nested
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
