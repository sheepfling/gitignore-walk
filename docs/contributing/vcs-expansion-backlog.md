# VCS walking expansion backlog

This is the working plan for expanding `gitignore-walk` beyond Git. It incorporates the
`vcs-ignore-research-checkpoint.zip` and `vcs-ignore-implementation-research.zip` handoffs supplied
on November 7–8, 2026. It orders work by dependencies and evidence gates so that new dialects do not
inherit Git assumptions. It is a backlog, not a commitment to support every VCS listed here. Promote
a slice to a GitHub issue when it is ready to start and keep its acceptance evidence with that issue.

## Current baseline

The shared `IgnorePolicy`/`IgnoreWalker` seam, conservative pruning capability, tagged selection
types, and per-scheme package layout are in place. Git and an initial portable Mercurial evaluator
are implemented; Mercurial remains under conformance development. An initial native-discovery
Subversion property policy is implemented, and its expanded matching corpus passes on captured
profiles. Native discovery now includes `svn:global-ignores` inherited from repository ancestors
above the checkout root; this is captured on macOS arm64, Linux aarch64 and x86_64, and Windows
x86_64. External walking also queries each listed external working copy's properties, including
nested externals, and keeps outer-working-copy rules outside each nested boundary. Broader
discovery and working-copy conformance remain open. The
implementation research handoff records 94 native assertions against Git 2.47.3 and ripgrep 14.1.1
on Linux, plus one malformed-input observation. It also supplies 88 non-Git candidate cases: 67
documentation/source-derived and 21 open questions. The original Mercurial native corpus has 48 path
probes and six traversal fixtures, captured with Mercurial 7.2.4 on macOS arm64, 7.0.1 on Linux
aarch64 and x86_64, and 7.1.2 on Windows x86_64. A hosted Ubuntu x86_64 capture adds Mercurial
6.7.2. The current Mercurial 7.2.4 Windows profile adds 71 path cases: 65 closed observations
match, six remain open, and four skip because their fixtures require POSIX behavior. Its six walk
fixtures match. The historical Windows 7.1.2 capture has 67 path cases, including 60 closed boolean
comparisons and one structured invalid-syntax match, while four path probes skip on platform
constraints. The
include-cycle and nested-subinclude native errors remain open. NUL-delimited native status closes the
Unicode digit-class case whose `debugignore`
output is unparseable on Windows. Eight additional regex/glob byte-semantics probes now
match native results on macOS arm64 and Debian 13 Linux aarch64 and x86_64; the client-enabled test
also compares them with the installed Mercurial on each platform. Fourteen regex-extension probes
match native on macOS arm64, hosted Ubuntu x86_64, Windows Server 2025 x86_64, and both Debian 13
Linux architectures. The live-client differential test exercises the full set.
Workspace `.hgignore` precedence over a matching configured `ui.ignore` source is now captured and
checked on macOS, Linux x86_64, and Windows. Two symlink-source boundary probes match on macOS and
Debian Linux x86_64. A self-referential include-source loop also matches on macOS and Windows.
Live-client tests exercise the regex cases. The latest Mercurial module run on macOS passes with
631 passed and 11 skipped.
All 46 original boolean expectations
and the structured invalid-syntax expectation agree across the original profiles, as do all six
walk fixtures. Parent
walks stop at nested `.hg` workspaces, and root walks stop at `.hg` metadata.
One source-discovery case records Mercurial 7.2.4/macOS, 6.7.2/hosted Linux, and 7.1.2/Windows
raising `AssertionError` while evaluating `subinclude:` from a file reached through `include:`; the
portable policy loads that nested source and returns an ignored decision. The repeated native
failure establishes this as a multi-platform client divergence rather than a macOS-only anomaly.
An undecodable glob pattern matches native `debugignore` on all three profiles, and actual byte-path
walks match native status on both Linux architectures; the walk test skips macOS because its
filesystem rejects such names. Mercurial also compares Unicode paths by exact code-point spelling: an
NFC glob does not match the equivalent NFD query. Forty-six `debugignore` queries exit normally.
One other query prints an ignored decision, then exits with a
formatting error; that `subinclude` behavior is independently confirmed by a matching native
`status --ignored` walk fixture on all three profiles. The include-cycle case is a documented safe
divergence: the native client recurses and errors, while the library detects the cycle and reports
incomplete discovery. Additional source-boundary probes confirm that Mercurial follows an include
through a symlinked directory outside the workspace and warns when the symlink target is dangling;
the policy follows the former and marks discovery incomplete for the latter. Both new probes match
Mercurial 7.2.4/macOS arm64 and 7.0.1/Debian 13 Linux x86_64. Results are recorded
under `tests/oracles/hg/`. The initial SVN property policy evaluates `svn:ignore`, inherited
`svn:global-ignores`, Subversion's built-in default global patterns, patterns from an explicit
`config_dir/config` runtime file, and additional caller-supplied global patterns after native
property discovery. An explicit runtime setting replaces built-in defaults; ambient configuration
files and machine/user Registry values are discovered on Windows. Registry read failures carry
diagnostics; the dedicated disposable Windows Registry/native comparison has been reviewed and
captured against Subversion 1.14.5 SlikSvn on Windows Server 2025 x86_64. Live native status
comparisons on the development client cover built-in defaults and per-user file precedence; the
native APR probes now reproduce backslash quoting, both class-negation markers, malformed opening
brackets, and the absence of POSIX character classes. They also confirm spaces do not split
`svn:ignore` or `svn:global-ignores` property lines. The new cases match on Subversion
1.15.0/macOS arm64, 1.14.5/Linux aarch64 and x86_64, and 1.14.5/SlikSvn Windows x86_64. Windows
skips the escaped-wildcard filename because Windows cannot represent `*` in a filename. The new
inherited-property case also matches native status on all four captured profiles. A switched
working-copy case found that recursive property discovery omits inherited rules at switched paths;
the policy now queries each native-reported switched root and scopes its inherited
`svn:global-ignores` there. Native status, policy decisions, and walker selections agree on
Subversion 1.15.0/macOS arm64, 1.14.3/Ubuntu 24.04 x86_64, and 1.14.5/SlikSvn Windows x86_64.
The APR glob-flags question has source evidence in both the 1.14.5 and 1.15.0 `string.c` tags:
the common helper calls `apr_fnmatch` with flags `0`, and status passes a basename to the helper.
The native default-flags case confirms leading-period wildcard matching and case sensitivity on
Subversion 1.15.0/macOS arm64 (APR 1.7.6), 1.14.3/Ubuntu 24.04 x86_64 (APR 1.7.2), and
1.14.5/SlikSvn Windows x86_64 (APR 1.7.5). The three client results agree on the ignored paths and
the visible uppercase control.
The SVN corpus now also covers newline- and tab-bearing filenames: Subversion 1.15.0/macOS arm64
captures their XML numeric-reference round trip, and top-down and bottom-up policy walks preserve
the decoded paths. Windows records an explicit skip because it cannot represent these filenames;
Subversion 1.14.5 Linux aarch64 and x86_64 captures also match all 16 cases, including both walks.
The initial SVN property fixture covers seven ignored paths and local, inherited, nested, runtime,
negation, case, and tracked-file distinctions; native results match on Subversion 1.15.0/macOS arm64
and 1.14.5/Linux aarch64. A sparse-depth `empty` fixture confirms directory properties remain
available and apply to new files; an excluded-depth fixture confirms status stops at the excluded
directory and its properties are unavailable. Both match on all three profiles, and policy walks
stop at excluded roots while explaining direct queries there as incomplete. Additional native
fixtures on Subversion 1.15.0/macOS and 1.14.5/Debian 13 Linux x86_64 cover `files` and `immediates`
depths. Native status collapses nested unversioned directories, while the walker descends and
leaves omitted descendant membership unknown; depth-empty versioned child directories retain
their local ignore properties. Captures are retained in the macOS and Linux x86_64 result
files. A separate native case confirms parent `svn status` reports a nested working-copy directory
but does not enumerate files
beneath it; the policy walk excludes unrelated nested `.svn` roots and descends into externals listed
by native status, including repository-root-relative URLs with and without pinned revisions,
parent-relative URLs, absolute URLs, server-root-relative URLs, and scheme-relative URLs served by a
loopback-only disposable `svnserve` repository.
File externals are captured on macOS, both Linux architectures, and Windows: native status reports a
file external as a normal versioned file, and the ignore policy keeps its name match separate from
that membership result. The opt-in membership-aware file-external test passes on all four profiles.
The SlikSvn Windows suite passed with 99 passed and 12 skipped in the latest hosted run; the macOS
and Linux suites pass with 107 passed and 4 skipped each. Native status paths omitted by sparse
working-copy depth remain unknown. The status-transition fixture also confirms Subversion omits a
filesystem child below an obstructed directory; the policy walk still reaches that child, keeps
its membership unknown, and continues to report ignore matching independently.
An unversioned-directory fixture also confirms that native status collapses `cache/` into one
unversioned entry on macOS Subversion 1.15.0, hosted Ubuntu 1.14.3, and Windows SlikSvn 1.14.5.
The policy keeps rule matching separate from native membership when status collapses an
unversioned directory. Broader status traversal remains open. A second fixture gives `cache` an
inherited ignore rule: default status omits that directory, while `--no-ignore` reports it once
without its descendants. The walker continues through it and evaluates descendant basenames against
applicable rules; membership remains unknown for descendants omitted from status. A third fixture
shows a `cache` pattern matches the versioned directory name but not the different basename of its
child: tracked files remain included and the unversioned child is not ignored. This exposed and fixed
an ancestor-component false positive in the policy. Native status and membership captures match on
macOS 1.15.0, Ubuntu 1.14.3, and Windows SlikSvn 1.14.5.
Explicit and standard file-based runtime-config discovery plus built-in defaults
are implemented. Native precedence captures cover system-to-user INI files on Debian 13 x86_64 and
machine/user Registry-to-INI precedence on Windows SlikSvn 1.14.5. A macOS 1.15.0 capture confirms
ambient user `HOME/.subversion/config` discovery. Versioned-directory membership is covered by a
three-profile native fixture. A live Subversion 1.15.0/macOS comparison confirms an explicit
`--config-dir` suppresses a conflicting ambient user config in both native status and the policy;
the test also uses an isolated `APPDATA` config path on Windows for the hosted native suite.
Broader precedence profiles and traversal/path behavior remain open.
Fossil's 43-case
ignore-glob corpus is captured on 2.28/macOS arm64, 2.26/Linux aarch64 and x86_64, and 2.23/Ubuntu
24.04 x86_64: all 41 boolean
candidates agree, including range classes, Unicode `?`, case sensitivity, class-negation markers,
unmatched brackets, Unicode whitespace preservation, global fallback, local-over-global precedence,
versioned-over-local precedence, and the previously captured quote, separator, and traversal cases.
Nine malformed or escaped-token probes and fifteen ASCII-whitespace tokenizer probes match all
four profiles and the evaluator. The adjacent `"a"b` case confirms a suffix after a closing quote
starts another token. Opt-in membership discovery now combines structured Fossil JSON
directory and checkout-status results, keeping tracked membership separate from ignore decisions;
directories remain membership-unknown. A live Fossil 2.28/macOS fixture verifies native membership
for scheduled additions, missing files, edits, and renames, plus unknown for an absent unreported
path; ignore decisions remain unchanged. Membership-aware included, ignored, and all-file walks
now cover those states in both top-down and bottom-up order, keeping scheduled additions, edits,
renames, and missing tracked files separate from ignored unversioned files. Fossil selection now
retains its metadata-marker baseline by default, with explicit `initial_excludes` replacement. A
Fossil 2.28/macOS native comparison also confirms parent walks stop at a nested checkout opened
with `fossil open --nested`, in both top-down and bottom-up traversal. Cross-profile status and
broader traversal coverage remain open.
Breezy's corpus is now
captured on 3.3.24/macOS arm64, Linux aarch64 and x86_64, and Windows Server 2025 x86_64 with
isolated user configuration: all thirty-three boolean cases agree, including global-versus-branch
exception priority and built-in defaults without a user ignore file. The Windows capture seeds
nested anchors through Breezy's API because the client CLI misresolves nested add paths. Its
isolated `BRZ_HOME` avoids the runner's actual AppData directory. A guarded Windows CI probe resolves
the path through Breezy 3.3.24's `user_ignore_config_path()`, temporarily writes a marker, confirms
that native `brz ignored` and policy both report it, and restores the original file bytes. The
captured result is versioned in the Breezy oracle. This confirms the default path for that Windows
client profile; other native versions remain unverified. A child exception under an ignored directory
exposes sibling files as unknown in status.
The exception pattern opens the ignored directory even when its named target is absent.
The native regex exception case also opens an ignored parent in both traversal orders; its target
appears as unknown while sibling files remain ignored, and the matching no-exception control keeps
the subtree hidden. The policy walker matches both native path sets on all four profiles.
Named regex captures are rewritten with a warning; malformed RE patterns fail with exit code 3.
The initial Breezy evaluator and typed selection are implemented and pass all thirty-three boolean
candidate cases, including exact-path versus `/**` strong exclusions, `BRZ_HOME` global ignores,
exception-aware directory traversal, anchored RE matches, negative lookahead, scoped inline flags,
and named-capture normalization. A new native
status capture verifies that an exception under ignored `cache` exposes sibling files; policy walk
results match native unknown and ignored paths in both directions on all four profiles. Broader
RE semantics and source-location precedence remain open. A live Breezy 3.3.24/macOS fixture also
confirms parent walks stop at nested working trees in top-down and bottom-up order, matching
`brz status --short`. Native captures also show that the
documented global inline regex flag example is rejected with exit code 3 in all four pinned Breezy
profiles. Four additional regex cases now capture exact whole-path matching, `!!RE` priority, and
the 3.3.24 backslash normalization quirk on all four profiles. Other non-Git
candidate cases have
no captured native result. The November
7 checkpoint separately records seven Git probes. These captures do not establish complete
cross-platform behavior.

A fifth Breezy native profile now covers Debian 13 x86_64 with Breezy 3.3.11 and Python 3.13. Its 52
shared probes include 48 boolean candidates, all matching the portable evaluator, and three
source-precedence probes matching their expected winning patterns. Four explicitly profile-scoped
cases remain excluded, including root-anchored traversal probes and two Unicode regex probes. The
Unicode `\\w` and `\\d` probes remain scoped to Breezy 3.3.24/macOS: an exploratory 3.3.11/Linux run
under `LC_ALL=C` omitted the queried Unicode paths from both `brz ignored` and status when those regex
rules were present. Treat that as an unresolved native observation, not conformance evidence. Linux
native CI recaptures and checks this older client profile in a pinned Debian image, adding
cross-release evidence without claiming full RE or traversal conformance.

The initial Perforce evaluator and typed selection are now implemented for the caller-selected
workspace subset. It consumes explicit/environment `P4IGNORE` source lists or the two documented
default names, supports the captured wildcard/directory/exception syntax, and keeps ignored
directories traversable. All 37 boolean candidates and one filesystem-dependent case agree with
P4/P4 Server 2026.1 captures on macOS arm64, Debian 13 Linux x86_64, and Ubuntu 24.04 Linux x86_64.
Three add-command path-boundary cases are recorded separately; `p4 ignores -i -v` still exposes the
escaped-leading-`#` rule match when `p4 add -n` rejects that filename.
Captures compare `p4 add -n` with `p4 ignores -i -v` and cover source-list precedence, configured
`P4CONFIG` filenames, built-in `.p4root` exclusions, exception behavior, and ignore-file-root
anchoring. A recursive `p4 add -n ...` capture matches included and ignored policy walker results in
both traversal orders, including an exception beneath an ignored directory. Server-backed captures
record mapped, explicitly excluded, and unmapped local paths across three native profiles. Opt-in
client-view-aware walks filter files by those mappings while keeping directories traversable because
an unmapped directory can contain mapped descendants. P4IGNORE decisions and versioned membership
remain independent. The opt-in `membership_aware=True` query now combines the native `p4 have` list
with `p4 opened` records mapped by `p4 where`; present listed files are versioned (including files
opened for add, edit, or delete), present unlisted files are unversioned, and directories or missing
unlisted paths are unknown. Focused query-record tests confirm membership does not change ignore
decisions. A live disposable P4D test compares the policy against native `have`, `opened`, and
`where` queries across clean, modified, missing, opened-delete, pending-add, ignored-untracked,
directory, and missing-unlisted states. The live test passes with P4/P4D 2026.1 on macOS arm64 and
Ubuntu 24.04 x86_64 using the checksum-pinned Linux binaries from CI. The Windows test job now
downloads and checksum-verifies the official 2026.1 client/server executables before running this
test; its first hosted result is pending. On case-insensitive macOS filesystems, a case-only query
alias resolves to the listed tracked entry; case-sensitive Linux correctly leaves the absent
spelling unknown. Broader syntax and native workspace discovery edge cases remain open.

The initial [Fossil oracle notes](../../tests/oracles/fossil/README.md) and
[Breezy oracle notes](../../tests/oracles/breezy/README.md) describe the observed corpora and their
remaining open evaluator contracts.

The checkpoint's Git probes cover ignored-parent blocking, contents-only exceptions, two `**`
forms, same-layer precedence, and tracked-file behavior with and without `--no-index`. Retain these
as a control corpus when the generic walker or matcher contracts change. The seven native
checkpoint probes are versioned in `tests/oracles/git/checkpoint_cases.json` and exercised by
`tests/test_git_checkpoint.py`, with rule matching kept separate from tracked-index behavior. The
broader case mapping and capture details are in the
[Git research oracle notes](../../tests/oracles/git/README.md). The implementation handoff's 79 Git
cases are now imported, evidence-labeled, and routed to
`tests/test_git_research.py`; 72 portable-policy comparisons pass locally, and five config,
worktree, and tracked-membership cases pass against the native policy contract. One non-UTF-8 case is
Linux-only, and one malformed-rule case remains observation-only. Its pinned Git 2.47.3/ripgrep
14.1.1 Linux capture is retained under `tests/oracles/git/results/`. The 16 ripgrep cases are
separately classified under the [ripgrep scanner oracle notes](../../tests/oracles/ripgrep/README.md);
their pinned 14.1.1 capture has 16/16 passing observations. They are inventory evidence only and do
not imply a ripgrep policy is implemented.

The implementation handoff adds design constraints to this backlog: keep the caller traversal root,
VCS workspace root, physical source parent, matcher root, and effective rule scope distinct; parse
raw records and directives before compiling rules; scope cache entries by dialect, matcher root,
scope, syntax and environment; bound include graphs and source/pattern sizes; and prove pruning-on
and pruning-off walks select the same files while preserving semantic parent barriers. Its proposed
resource limits are starting values to measure, not compatibility facts or frozen API defaults.

## Where the work belongs

| Concern                        | Destination                                      | Intended responsibility                                                                       |
| ------------------------------ | ------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| Shared results and policy seam | `src/gitignore_walk/_policy.py`                  | Scheme, provenance, diagnostics, trace, and conservative pruning contract                     |
| Shared filesystem traversal    | `src/gitignore_walk/_walker.py`                  | Walk modes and filesystem safety; no dialect parsing                                          |
| Built-in selection             | `src/gitignore_walk/_selection.py`               | Typed scheme/config union and exhaustive selection; no dynamic plugin registry                |
| Per-scheme implementation      | `src/gitignore_walk/_schemes/<scheme>/`          | Discovery, parser/evaluator, native adapter, and scheme-specific policy                       |
| Public API                     | `src/gitignore_walk/__init__.py`                 | Stable exported policy, config, result, and helper types                                      |
| Unit and typing evidence       | `tests/` and `tests/typing/`                     | Deterministic semantics, traversal, failure, and downstream typing fixtures                   |
| Native oracle fixtures         | `tests/oracles/<scheme>/`                        | Disposable client-driven behavior probes, version/profile metadata, pass/skip results         |
| CI orchestration               | `scripts/ci.py` and `.github/workflows/ci.yml`   | Local entry points and pinned native-client jobs, keeping clients out of runtime dependencies |
| User and contributor guidance  | `README.md`, `docs/API.md`, `docs/contributing/` | Supported behavior, API, support matrix, limitations, research, and backlog                   |

The new research ZIP is an implementation handoff, not a required runtime asset. Its 88 non-Git
cases should be reviewed, corrected when native probes disprove an expectation, and copied into
version-controlled oracle fixtures with their evidence status. Do not turn its 36 source references
into timeless facts: pin mutable source revisions and review license terms before borrowing any
third-party implementation code.

Only add a shared abstraction when a concrete scheme needs it. Keep the first implementation inside
its own scheme directory even if its parser or discovery logic looks reusable; wait for a second real
consumer before extracting a shared helper.

## Candidate VCS roadmap

This is a proposed order for investigation, not a promise to implement every candidate. Mercurial is
the selected first candidate for native capture: its client is available locally, its ignore grammar
and nested-source model differ from Git, and disposable repositories can exercise it without a
server. The implemented subset has initial comparisons against three captured profiles, not full
conformance. SVN is second because its property and
inheritance model exercises another distinct source type. The order follows the implementation
handoff; revisit it if native feasibility or project priorities change.

| Order            | VCS                                                       | Intended feature slice                                                                            | Main oracle questions and gate                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ---------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1 (recommended)  | Mercurial                                                 | `.hgignore` regex, glob, root/configured sources; nested `include`/`subinclude`; explain and walk | The original 48 `debugignore` cases and six status-walk fixtures remain captured on macOS, Debian Linux aarch64/x86_64, Windows, and hosted Ubuntu (Mercurial 6.7.2). Eight byte-semantics cases match on macOS and both Debian Linux architectures. All fourteen regex-extension cases match on macOS arm64, hosted Ubuntu x86_64, Windows Server 2025 x86_64, and Debian 13 aarch64/x86_64; CI regenerates and validates both Debian profiles. Two symlink-source cases match on macOS and Debian Linux x86_64. Live-client tests compare the regex cases on client-enabled platforms. The Windows profile has 60 closed boolean comparisons and one matching structured invalid-syntax result, with four path skips. Nested `subinclude:` through an included file raises a native `AssertionError` on macOS, hosted Linux, Windows, and both Debian profiles; the portable evaluator still resolves it. Mercurial warns and skips file or directory symlink sources; the policy marks these sources unavailable, and all six Windows walk fixtures match, including repeated symlink scopes. NUL-delimited native status resolves the Unicode digit-class case whose `debugignore` output is unparseable. Include cycles remain a documented safe divergence; Linux byte-path walking matches native status, and `.hg` metadata remains a traversal boundary. See `tests/oracles/hg/results/`; broader syntax remains open.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| 2                | [SVN](../../tests/oracles/svn/README.md)                  | Bounded property-driven working-copy policy, including inherited directory properties             | The expanded status corpus matches native behavior on Subversion 1.15.0/macOS arm64, 1.14.5/Linux aarch64 and x86_64, and 1.14.5/SlikSvn Windows x86_64. This includes inherited `svn:global-ignores` above the checkout root and rules from listed externals, including nested externals. Versioned property rules stop at each external working-copy boundary. Sparse `empty` and `exclude` depths match across profiles; `files` and `immediates` fixtures match on macOS and Debian 13 Linux x86_64 and cover collapsed unversioned-directory traversal and depth-empty child properties. Nested working-copy boundaries and native-listed externals with repository-root-relative, parent-relative, absolute, server-root-relative, and scheme-relative URLs are covered. Windows skips the escaped-wildcard filename, which cannot be represented there, and the scheme-relative external because SlikSvn lacks `svnserve`. Captures and Registry evidence are retained under `tests/oracles/svn/results/`. Opt-in membership discovery classifies entries listed by verbose native status and keeps omitted paths unknown; its focused runtime suite passes on macOS arm64 and Linux aarch64/x86_64, Windows file-external membership now has a captured native result. Live transition tests cover eight status values on macOS 1.15.0, hosted Ubuntu 1.14.3, and Windows SlikSvn 1.14.5. The macOS native status result is committed in `tests/oracles/svn/results/svn-status-transitions-1.15.0-macos-arm64.json`; native CI also emits and checks a fresh transition capture for its artifacts. Broader status traversal remains open. Handoff has 13 status and 2 import-reference cases.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| 3                | Fossil and [Breezy](../../tests/oracles/breezy/README.md) | Mature Fossil and Breezy conformance; broaden regex, source, and traversal coverage               | Fossil: 43 oracle cases on 2.28/macOS arm64, 2.26/Linux aarch64 and x86_64, and 2.23/Ubuntu 24.04 x86_64. All 41 boolean candidates match, including range classes, Unicode `?`, case sensitivity, class-negation markers, unmatched brackets, preservation of Unicode whitespace, quoted separators, precedence, and ignored-directory descendant suppression. Nine captured malformed/escaped token decisions and fifteen ASCII-whitespace tokenizer probes, including quoted-token boundary trimming, are asserted against four native profiles and the evaluator. Its included/ignored walker selections match native `extras` for the captured directory fixture, including checkout-marker exclusion. Other glob, source, and traversal coverage remains open; `clean-glob`/`keep-glob` are out of scope. Breezy has an initial typed policy with 52 matching boolean candidates on macOS arm64, 36 on Linux aarch64, 33 checked on Linux x86_64 and Windows Server 2025 x86_64, and 48 on Debian Breezy 3.3.11. Captured behavior includes `BRZ_HOME`, exact-path strong exclusions, exception-aware traversal, negative lookahead, scoped inline flags, whole-path regex matching, `!!RE` priority, backslash normalization, and wildcard/regex nested exception scopes. A dedicated guarded Windows CI probe confirms that Breezy 3.3.24 resolves `%APPDATA%/breezy/ignore` and that native `brz ignored` agrees with the policy; its artifact is versioned. Three source-overlap probes now show global rules before built-in defaults and branch rules on all four Breezy 3.3.24 profiles and Debian Breezy 3.3.11. Two Breezy 3.3.24/macOS arm64 native fixtures cover root-anchored exception pruning: `!./cache/keep.tmp` keeps its ignored parent traversable, while unrelated `!./other/keep.tmp` leaves `cache` prunable. Top-down and bottom-up policy walks match native unknown paths; the negative case records Breezy status collapsing the ignored unversioned directory to `cache`. Broaden RE behavior, additional global configuration sources, cross-profile source-order checks, and pruning safety beyond these anchored-path cases. Other Windows client versions remain unverified. |
| 4                | [Perforce](../../tests/oracles/perforce/README.md)        | Mature the initial `P4IGNORE` evaluator and opt-in `P4CONFIG`/client-root discovery               | Three disposable local `p4d`/client profiles (macOS arm64, Debian 13 x86_64, Ubuntu 24.04 x86_64) match 42 boolean candidates plus one platform-dependent case. The added `**` captures verify cross-separator matching, empty substring matches, and significant neighboring separators. Three add-command path-boundary cases are recorded separately, with rule matching checked through `p4 ignores -i -v`. Captures cover configured `P4CONFIG` and `.p4root` exclusions, opt-in config discovery, config-over-environment precedence, nested config selection, tagged client-root discovery from a nested directory, and a parent P4CONFIG/P4IGNORE source outside the client root. Root-anchored rules resolve against their containing ignore file. New lexical captures confirm leading and trailing ASCII spaces are trimmed, tabs remain significant, and escaped leading `#` matches even though `p4 add` rejects `#` filenames. Client-view-aware walking filters files against captured native `p4 where` mappings while retaining directories for mapped descendants. Broader syntax and configuration edge cases remain open.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| 5                | Darcs and TFVC                                            | Mature native membership-aware Darcs candidate walking; investigate nested `.tfignore` profiles   | Darcs has eighteen closed oracle cases on 2.18.5/macOS arm64, 2.18.5/Debian Sid x86_64 and aarch64, and 2.18.4/Debian 13 x86_64 and arm64. The `[[:alpha:]]` class stays ASCII-only for an accented filename under `C` and `C.UTF-8` locales on all three profiles. A nested-repository probe also confirms that outer Darcs treats files inside a nested Darcs repository as add candidates; the walker excludes its `_darcs` metadata while following those files. Live Darcs walker tests verify included-only, ignored-only, and all-file selections in both traversal orders, including trailing-space and newline-bearing names on POSIX. Managed paths use NUL-delimited output, with targeted native add checks when candidate output becomes ambiguous. Darcs 2.18.4 and 2.18.5 captures show local rules remain active alongside configured `boringfile`, and global `~/.darcs/boring` remains active alongside local and configured sources; the policy delegates to Darcs without Python-side precedence. Global/local/configured-source overlap is now captured on all three profiles. The official [download page](https://darcs.net/Binaries) lists only the 2.16.3 Windows binary while the [project home page](https://darcs.net/) identifies 2.18.5 as current stable; the [team page](https://darcs.net/DarcsTeam) says the Windows packager role is unfilled. Do not count the old binary as current-release evidence. Broader platform and configuration coverage remain open. TFVC has seven unrun cases and still needs an automatable client.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| 6                | Sapling and Jujutsu                                       | Mature the initial read-only policies and broaden native profiles and path/source coverage        | Four disposable mode probes on Sapling 0.2.20261103/Jujutsu 0.47.1 match on macOS 26 arm64, Debian 13 Linux aarch64 and x86_64, and Windows Server 2025 x64. They show the same `.gitignore` behavior in Sapling `.git`/`.sl` modes and Jujutsu colocated/non-colocated modes. `.hgignore` and `.jjignore` do not suppress candidates. XDG Git ignores apply to Sapling `.git` mode and both Jujutsu modes; `.git/info/exclude` applies to Sapling `.git` and colocated Jujutsu only. Where all three sources are active, workspace `.gitignore` overrides `.git/info/exclude`, which overrides XDG ignore. Initial read-only policies and typed selection reuse the Git dialect while keeping workspace discovery and sources separate. A second matrix matches ignored-parent barriers, child negation, root anchoring, and recursive `**` on all four modes; direct decisions and walker selections replay those captured cases. Sapling's opt-in membership query uses NUL-delimited status. Jujutsu's opt-in query reads `jj file list --ignore-working-copy` to avoid snapshotting the workspace. The older Sapling 0.2.20261028 profile also matches the checked Windows source/configuration probes; `.sl` pattern discovery is explicitly excluded and remains unverified on Windows. Broader client versions and path coverage remain open.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| adjacent, opt-in | ripgrep and Docker                                        | Scanner/context policies outside the VCS scheme set                                               | Handoff has 16 native ripgrep cases. Keep opt-in and separate from VCS selection; Docker context rules need their own profile.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |

Breezy traversal follow-up: native 3.3.24/macOS arm64 and 3.3.11/Debian 13 x86_64 confirm that a deeper
`!cache/deep/keep.tmp` exception opens both ignored ancestors. With `cache/**`, the nested exception
also makes its containing directory and descendants unignored, while a sibling directly under
`cache` remains ignored. Variable directory scopes from `*`, `**`, and regex exceptions are captured
across those two client profiles. The policy walker matches the native path selections in both
traversal orders, and direct candidate tests ensure a wildcard scope does not unignore a sibling in
its ignored parent. See `tests/oracles/breezy/cases.json` and the two matching result files.

Breezy now also supports opt-in file-membership queries through its NUL-delimited versioned listing.
Present listed files are versioned, present unlisted files are unversioned, and missing files or
directories remain unknown. A live native fixture covers tracked ignored files, lexical membership
for file and directory symlinks, and both walk orders.

SVN now has a live status-transition test for normal, modified, added, deleted, missing, replaced,
obstructed, and conflicted entries, alongside ignored-unversioned files. The conflict uses two
working copies and overlapping edits. It checks native status membership, membership-aware walk
selection exactly in both traversal orders, including unversioned conflict sidecars, and traversal
through an obstructed directory. A separate check
confirms that an excluded-depth child omitted from verbose native status stays membership-unknown
and that the walker does not descend there. A directory-external check confirms outer `external`
status and membership scope from the external working copy. The transition test passes locally
against Subversion 1.15.0 and runs in the hosted Ubuntu 1.14.3 and Windows SlikSvn 1.14.5 native
integration jobs. A live membership test also roots the policy and walker at a nested versioned
directory and matches its membership with native status from that caller root. The macOS transition
capture is versioned, and both native CI jobs retain fresh captures with their artifacts; broader
status traversal remains open.

Reorder this list when user demand, supported client automation, or native probe results justify it.
Do not implement a candidate merely because a CLI is installed. Each implementation starts with a
scope record and reproducible oracle fixtures.

## Work sequence

### VCS-00 — Capture and select the first additional scheme

**Priority:** P0 · **Depends on:** none · **Status:** initial Mercurial capture complete; implementation
gate open

The runner in `tests/oracles/hg/` captures the original 48 cases on Mercurial 7.2.4/macOS arm64 and
7.0.1/Debian 13 Linux aarch64 and x86_64. Eight additional regex/glob byte-semantics cases are
captured on all three Unix profiles and are compared with each installed client by the native
integration test. All 46 original boolean expectations and the structured invalid-syntax
expectation match each native profile, and 46 `debugignore` queries exit normally.
`hg.subinclude-rebases` prints an ignored decision before
exiting with a source-formatting error; its rule behavior is independently corroborated by the
`hg.walk.subinclude-scope` status fixture on all three profiles. `hg.include-cycle` is recorded as a
safe divergence because the native client recurses until failure while the library detects the cycle
and reports incomplete discovery. See the per-case commands, exit codes,
normalized stdout/stderr, and client profiles in the three `hg-*.json` matching results. Six
additional walks compare `status --ignored` and `status --unknown`; all match on the three profiles
and are stored in the `hg-walk-*.json`
results. The default runner output also retains raw local stdout/stderr for auditing path
normalization.

These captures narrow but do not close VCS-00: they cover three client/platform profiles and basic
status enumeration, but not every advertised Mercurial release, platform, tracked-file workflow, or
all configuration precedence. Candidate expectations remain evidence-qualified. Keep command-line
file-selection patterns outside the ignore-policy contract; they are a separate Mercurial feature
from evaluating `.hgignore` and configured ignore sources. A 41-case Perforce native
capture verifies an isolated local server/client workflow on P4/P4 Server 2026.1 across macOS arm64,
Debian 13 Linux x86_64, and Ubuntu 24.04 Linux x86_64. The initial portable evaluator and typed
selector match all 37 boolean candidates plus one filesystem-dependent case; captures also record
the newline and wildcard-filename error boundaries. Separate native
`p4 ignores -i -v` results cover built-in exclusions, including the configured `P4CONFIG` filename;
opt-in config discovery and ignore-file-root anchoring also have captured tests. Broader syntax and
additional profiles remain open.
SVN's disposable repository fixture is captured on
macOS and Linux.

**Done when:** the selected profile, reasons, captured oracle results, and deferred candidates are
recorded. Candidate expectations and exploratory probes are not full conformance evidence.

### VCS-00a — Lock the Git baseline and import the research evidence

**Priority:** P0 · **Depends on:** VCS-00

**Status:** The seven checkpoint probes and 79-case Git research corpus are versioned and tested
against the portable and native evaluator contracts. Seventy-two portable comparisons and five
native-policy cases pass locally; the Linux-only byte-path case is skipped on macOS, and one
malformed-input probe is observation-only. Tracked-file probes deliberately distinguish ignore-rule
matching (`--no-index`) from Git's index-aware native status. The 16 ripgrep cases are classified,
captured separately, and checked for inventory/capture consistency; implementing a scanner policy
remains a distinct, optional product feature.

Review the imported Git mapping and keep the portable/native boundary explicit. Port applicable Git
counterexamples to tests against both policies before changing shared matching or walking behavior.
Keep the ripgrep inventory and native evidence separate as optional scanner-policy research, not a
Git or VCS scheme. Preserve the malformed-input observation as a deliberate safe-divergence
candidate, not a required emulation of NUL truncation.

**Done when:** each imported case has an evidence label and target suite; Git baseline regressions
pass against both portable and native library policies where applicable; ripgrep has its own
classified native evidence and is explicitly excluded from the current library scope; non-Git
expectations remain unasserted until captured or explicitly excluded from scope.

### VCS-01 — Freeze the shared walking contract against the chosen scheme

**Priority:** P0 · **Depends on:** VCS-00

**Status:** Initial contract is implemented and tested; tracked-state and cross-platform boundaries
remain open.

Map Mercurial behaviors to `IgnoreDecision`, `IgnoreDiagnostic`, `IgnoreTrace`, `IgnorePolicy`, and
`IgnoreWalker`. Keep caller traversal root, workspace root, physical source parent, matcher root and
effective rule scope distinct. Identify whether source origin, line/property, precedence, partial
discovery, versioned membership, or traversal cannot be represented. Keep membership separate from
rule matching and pruning. Add the smallest typed internal model demonstrated by evidence; do not
make internal source-reference records public API without a downstream need.

**Done when:** a contract table covers every required behavior, every gap has an accepted API/test
change or an explicit limitation, and the custom-policy typing fixture still describes the public
walker seam.

| Mercurial concern             | Current contract                                                                                   |
| ----------------------------- | -------------------------------------------------------------------------------------------------- |
| Caller root vs workspace root | Targets are bounded by the caller root; the nearest `.hg` marker above it supplies workspace scope |
| Root source                   | Only workspace-root `.hgignore` is discovered automatically                                        |
| Additional configuration      | Explicit paths or opt-in `hg config --debug ui` discovery through `MercurialPolicyConfig`          |
| `include`                     | Included patterns retain the current matcher root; nested include paths are workspace-relative     |
| `subinclude`                  | Included patterns are scoped under the included file's parent directory                            |
| Syntax and reducer            | `regexp`, unrooted `glob`, and `rootglob`; all matches are additive; no `!` negation               |
| Parent paths                  | A matching ancestor directory makes a descendant ignored                                           |
| Provenance and trace          | Decisions carry physical source, line, and logical scope; trace returns matching rules in order    |
| Incomplete source graph       | Missing/cyclic/over-limit includes return diagnostics and `discovery_complete=False`               |
| Membership                    | No dirstate lookup; ignored means rule match, not untracked/versioned state                        |
| Pruning                       | An ignored directory may be pruned because this supported rule set has no inclusion exceptions     |

The policy uses provisional graph guards (32 include levels, 256 source visits, 4 MiB per source,
32 MiB total, and 20,000 bytes per compiled pattern). Tests exercise each ceiling and verify
source-graph overflows report incomplete discovery while pattern overflow raises a contextual parse
error. A source-size measurement covered the
[Mercurial 7.2.4 release archive](https://www.mercurial-scm.org/release/mercurial-7.2.4.tar.gz)
(SHA-256 `85839e0f39e6cb893a88932aa36ef661759f3c5c5de4551ad26bd9df53cb71a2`), the
[evolve](https://foss.heptapod.net/mercurial/evolve) working tree at
`bcdd16c129b305f2383262f867515e77d3d2afd6`, [hg-git](https://foss.heptapod.net/mercurial/hg-git)
at `0fe9af40ab8e4e615d29e9b891f39d9cefb05e55`, and [PyPy `.hgignore`](https://foss.heptapod.net/pypy/pypy/-/raw/d8cbd8b59d6bc13f2fe25a640eac0de2217b0fc0/.hgignore).
Their root `.hgignore` files contain 1,188, 417,
134, and 2,885 bytes, with 77, 27, 11, and 105 parsed rules. The largest literal rule is 60 bytes
and the largest compiled expression is 66 bytes. None uses `include:` or `subinclude:`, so the
profiles establish over 1,400-fold headroom for per-source bytes and over 300-fold headroom for
compiled pattern size, but do not measure real graph depth or source count. Keep the graph ceilings
provisional until a representative include-heavy corpus is measured. Expose configuration only if
user need justifies it.

### VCS-02 — Build a reusable native conformance harness

**Priority:** P0 · **Depends on:** VCS-00

**Status:** Scheme-specific disposable-repository runners capture the individual VCS behaviors.
`scripts.ci native` coordinates the six default native backends and opt-in `compat` and `svn-config`
backends for Sapling/Jujutsu and Docker-isolated Subversion system/user precedence. It validates
closed candidate results and writes a fresh platform/client summary with explicit skips, including
single-observation capture formats. Windows CI also runs its checksum-pinned Sapling/Jujutsu clients
through `compat` and retains the shared summary. Older version-specific profiles keep their own
capture and checks. Keep fixture setup and observation schemas scheme-specific.

Import and adapt the research handoff's runner/case structure without treating it as library tests.
Create disposable repository/workspace fixtures and isolated client configuration. Capture native
client identity/version/platform, locale, exact command, raw output, stderr and exit status with each
result. The harness must distinguish rule matching from native add/list/status behavior and traversal
output. It must report missing clients as skipped, never passed, and keep captured fixtures
deterministic where live clients are unavailable.

**Done when:** one harness invocation runs selected probes, records captured/failed/skipped status
and client profile, and cannot read or mutate the developer's real VCS configuration or repository.
Captures must preserve enough raw data to audit a normalization step. The shared local gate now
fails on client errors and closed candidate mismatches; platform/version-specific hosted captures
remain separate where they need dedicated setup.

### VCS-03 — Specify source discovery and boundaries

**Priority:** P1 · **Depends on:** VCS-00, VCS-02

**Status:** Explicit source order and opt-in `hg config --debug ui` discovery are covered on both
captured platform profiles, including named global entries and repository-local config. Mercurial
also preserves ordered `HGRCPATH` files: when two configured ignore sources match, native
`debugignore` and policy traces identify the first source while retaining both matches.
When a named `ui.ignore` key is repeated across those files, a live native comparison confirms the
later configuration value replaces the earlier source instead of merging both values.
Another live comparison confirms relative global `ui.ignore` paths resolve from the workspace root,
not from the home directory containing `HGRCPATH`.
Configured paths also expand environment variables from the policy's supplied environment using
Mercurial's POSIX `$VAR`/`${VAR}` and Windows `%VAR%`/`$VAR` forms.
The native oracle captures POSIX configured-path expansion on Mercurial 7.2.4/macOS arm64; the live
client test continues to exercise platform-specific syntax on enabled CI clients.
7.2.4 also confirms the workspace `.hgignore` is reported before a configured `ui.ignore` file when
both supply the same matching rule; the policy trace retains both sources and the effective source.
This precedence probe is currently captured on macOS arm64 and Debian 13 Linux x86_64. Native
probes confirm warnings for missing `include` and configured `ui.ignore` files; Mercurial silently
skips a missing `subinclude`, while the policy conservatively reports incomplete discovery. A
symlinked `include` to a file outside the workspace is followed natively and by the policy, with
canonical source and workspace-root scope preserved. The policy also matches native behavior for an
include through a symlinked directory outside the workspace and marks a dangling symlink source as
incomplete; both cases are captured on macOS and Linux x86_64. POSIX ownership trust is captured by
the Linux oracle: untrusted repository `.hg/hgrc` settings are ignored by both Mercurial and opt-in
policy discovery. Native probes also confirm unreadable included files are warned about and skipped;
the policy preserves the false match result while marking source discovery incomplete. Broader platform
and configuration-precedence profiles remain open.

Document Mercurial root `.hgignore`, configured `ui.ignore` files, explicit `include` and
`subinclude` edges, source order, syntax reset per file, root discovery, symlinks, include cycles and
unreadable/missing sources. Do not auto-load nested `.hgignore` files absent a native-supported
discovery edge. Native documentation and the current oracle confirm that `.hgignore` supports
file-based `include:` and `subinclude:` directives. Mercurial's command-line `include:` path
notation belongs to file selection and remains outside this ignore-policy feature.

**Done when:** source-discovery tests compare expected source/provenance and discovery diagnostics
with the native client for the supported profile; all unsupported discovery paths are explicit.

### VCS-04 — Implement the scheme parser/evaluator

**Priority:** P1 · **Depends on:** VCS-01, VCS-02, VCS-03

**Status:** The portable evaluator and captured-profile tests are implemented. The latest full test
module run on macOS passes with 631 passed and 11 skipped. Earlier Debian 13 runs passed with 446
passed and 11 skipped on each aarch64/x86_64 container; rerun those profiles when extending native
coverage.
Regex rules compile and match UTF-8 path bytes with `surrogateescape`, matching native ASCII
character-class and
case-folding behavior; glob `?` byte width is also confirmed by native captures. Include loading
uses bounded regular-file reads and reports non-regular sources as unavailable; broader dialect and
platform conformance remains open.

Implement the Mercurial parser as a dialect pipeline: physical byte records; comments, escapes and
whitespace; syntax directives and include edges; scoped typed rules; compiler; raw matches; reducer
and ancestor semantics; then decisions/traces. Support regex, glob and rootglob only to the captured
profile. Do not reuse Git parsing or assume Git negation semantics. Begin with correctness-first
portable evaluation; retain a native-only route only if a specific unsupported feature requires it.
Reject malformed/unsupported rules or report explicit incomplete discovery; never silently weaken a
pattern. Add measured include-depth, source-count, per-source/total-byte and pattern-size limits;
The initial guardrails (32 levels, 256 source visits, 4 MiB/source, 32 MiB total, 20,000 bytes per
compiled pattern) are provisional and need repository measurement before they become public defaults.

**Done when:** parser/evaluator fixtures cover syntax boundaries, malformed rules, path encoding,
rule order, nested scope, and exceptions; differential results match the selected native profile
for the supported corpus.

### VCS-05 — Implement walking and pruning behavior

**Priority:** P1 · **Depends on:** VCS-01, VCS-04

**Status:** Shared walker and pruning semantics are wired to Mercurial. Six fixtures compare
included, ignored, and all-file walks in top-down and bottom-up modes against Mercurial 7.2.4/macOS
arm64 and 7.0.1/Linux aarch64 and x86_64 `status --unknown` and `status --ignored` output. The
parent walk stops before a
nested `.hg` workspace, matching native status. One case reaches the same physical
ignore source through symlink aliases under two `subinclude` roots and confirms both scopes match.
An explicit pruning-on/pruning-off comparison now produces identical included-file sets across all
six fixtures in both traversal orders, while both walks retain nested-workspace boundaries. The
root `.hg` metadata directory is also a hard traversal boundary, and a separate Linux test compares
an undecodable filename with native NUL-delimited ignored status on aarch64 and x86_64. These
comparisons keep tracked membership separate; broader path and client-profile comparisons remain
open.

An opt-in `membership_aware` mode now captures `hg status --all --unknown --ignored -0` once per
direct batch or walk and annotates status-listed files as versioned (`C`, `M`, `A`, `R`, `!`) or
unversioned (`?`, `I`). A live disposable-repository comparison covers clean, modified, missing,
staged, scheduled-removal, ignored, and unknown files. It now checks included, ignored, and all-file
walk selections in both orders; a tracked file matching `.hgignore` stays included, while the
ignored unversioned file appears only in ignored/all selection. Paths omitted by native status remain
unknown. Nested untracked descendants are listed at their exact file paths and remain walkable under
the status snapshot. Membership lookup retains the lexical query path for tracked symlinks, so a
dangling tracked link remains versioned even when the policy resolves it for rule evaluation; this is
covered with native Mercurial status and `explain`, `trace`, and `iter_explain`. Native Mercurial
7.1.2 on Windows reports this tracked dangling link as modified (`M`) rather than clean (`C`) as on
POSIX; both status classes indicate versioned membership and are included in the live cross-platform
test. Broader sparse, symlink, and cross-profile membership behavior remains open.
On POSIX, the live membership fixture also checks NUL-delimited status records for filenames
containing a tab or newline: the tab-bearing `*.tmp` path is ignored, while the newline-bearing
`.txt` path remains unignored and unversioned. Both names survive status parsing and both traversal
orders intact. Windows rejects control characters in filenames, so its native run uses equivalent
representable names for the ignored and unignored membership cases.

A live sparse-checkout regression now covers a committed file removed by
`hg debugsparse --exclude`. Mercurial omits the absent file from
`hg status --all --unknown --ignored -0`, even when its path matches `.hgignore`; the policy keeps
the rule match and unknown membership separate. A physically present untracked file outside the
active sparse profile is also omitted by native status and membership-aware walks, while its direct
policy decision remains membership-unknown. A membership-aware policy rooted at the sparse subtree
also matches repository-root-relative status records. Included-file walks in both traversal orders
only return paths present in the sparse working tree. The fixture is verified locally on Mercurial
7.2.4/macOS arm64 and in hosted Windows and Ubuntu native-backed policy jobs for commit `def07df`.
The same fixture now deletes that exclusion through `hg debugsparse --delete`, verifies Mercurial
restores the file and reports it as versioned, and reuses the policy and walker to confirm the
membership-aware walk includes the ignored tracked file. This covers one sparse update transition;
an enabled, committed `.hgsparse` profile is also tested switching inclusion from one subtree to
another across commits, with native status and membership-aware walking checked before and after.
Its overlapping `[include]` and `[exclude]` patterns confirm that the native exclusion takes
precedence, including after the profile update. A tracked `%include` sparse-profile source that
Mercurial omits from disk and native status remains membership-unknown, while the membership-aware
walk matches native status for the files selected by the profile. Disabling the active profile
restores all committed files; the same policy refreshes their membership and the walker matches the
expanded native status set. The same profile transition now includes ignored and ordinary untracked
files in both subtrees: native status reports `I` and `?` only inside the active sparse scope, while
physically present files outside that scope stay membership-unknown. Included, ignored, and
all-file walks match those native status classes in top-down and bottom-up order before the switch,
after the switch, and after disabling the profile.
The sparse status-transition fixture also covers `hg add -s` outside the active profile: native
status reports the new path as added and restores an existing tracked sibling in that directory.
The membership-aware walker follows both statuses immediately, then matches native `C` statuses
after commit in both traversal orders. Updating back to the earlier revision removes the sparse-added
file from native status and makes its membership unknown again; updating forward restores both the
file and its versioned membership, with the reused walker matching native status in each state.
A POSIX FIFO and Unix-domain socket matching `.hgignore` are omitted by native status and all-file
walks, while direct policy evaluation still reports the ignore match and unknown membership. This
confirms that ignore decisions do not turn special filesystem nodes into regular-file walk results.
An additional sparse fixture confirms native status reports in-profile symlinks as ignored (`I`) or
unknown (`?`), while omitting a physically present symlink outside the active profile. Direct policy
matching uses the symlink's lexical path even when its target is outside the workspace; membership
comes from native status, and the regular-file walker does not follow or yield symlinks. The fixture
runs in both traversal orders and skips only when the host cannot create the required symlinks.
Broader sparse-profile and special-file coverage remains open.

Test included-only, ignored-only, and all-entry walks in top-down and bottom-up modes. Cover ignored
parents with included descendants, contents-only exclusions, nested rule sources, symlinks, special
files, tracked/versioned paths, and nested workspace boundaries. Override pruning only when native
semantics prove the subtree cannot contain a selected descendant.

**Done when:** traversal results are independently compared with the native client across the
supported corpus; pruning tests prove that exceptions are not hidden. Matching tests alone do not
satisfy this item.

### VCS-06 — Add typed selection and public API

**Priority:** P1 · **Depends on:** VCS-04, VCS-05

**Status:** Mercurial's tagged config, selection, public exports, docs, and downstream typing fixture
are implemented, including opt-in discovery through the installed Mercurial client and opt-in
membership queries. Broader config trust, include, and platform behavior remain open.

Add a scheme-specific config/selection variant to the explicit union and exhaustive switch. Keep
fallback within the selected scheme; never fall from one VCS grammar to another. Export and document
the policy/config/result types, provenance, failure modes, and whether native or portable evaluation
is available. Extend downstream type-check fixtures.

**Done when:** runtime tests prove every config selects the intended scheme/backend, all error and
fallback cases are explicit, and static typing narrows each selection to its policy.

### VCS-07 — Cross-platform and packaging readiness

**Priority:** P1 · **Depends on:** VCS-02 through VCS-06

**Status:** Versioned native observations span macOS arm64 and Linux aarch64 and x86_64. Hosted
Ubuntu and Windows capture jobs are wired. The reviewed Windows profiles are Mercurial 7.1.2 and
SlikSvn Subversion 1.14.5 on Windows Server 2025 x86_64; their captures and explicit skips are
versioned under the oracle result directories. Mercurial's captured Windows matching and walk
observations are replayed by the differential library tests; four path cases remain explicit skips.
Windows Mercurial skips symlinked ignore sources with a warning, and the policy mirrors that result
as incomplete discovery. POSIX undecodable-byte command arguments and permission cases remain
skipped there. The broader Python/platform matrix remains open.

Run the supported Python/platform matrix with native-client probes where clients are available.
Cover path separators, case behavior, Unicode and undecodable names where supported, symlinks, and
client-version differences. Verify wheel/sdist contents, installed API imports, docs, and user-facing
limitations.

**Done when:** the support matrix lists exact client versions/platforms, passes and skips; package
checks pass; no skipped native comparison is described as conformance.

### VCS-08 — Stabilize and release the first additional scheme

**Priority:** P1 · **Depends on:** VCS-07

**Status:** Complete for the initial release scope; publication remains a separate release action.
The README and changelog describe the explicit selection contract, opt-in Mercurial config query,
tested profiles, skips, and known divergences. Case-level findings link to versioned native captures
in `tests/oracles/hg/results/`; the changelog is included in the source archive. Local full CI and
the hosted matrix pass on the documented branch state.

Review the public contract, limitations, migration impact, README examples, API docs, and release
notes. Record known divergences and link each one to a test or issue. Keep the wheel name decision
separate unless the new scope makes a product rename necessary.

**Done when:** public docs and release artifacts match the tested support profile and all release
checks are green.

### VCS-09 — Add later schemes one at a time

**Priority:** P2 · **Depends on:** VCS-08

**Completed slice:** Sapling/Jujutsu configs accept either an explicit `global_excludes_file` or
opt-in `read_git_config=True`. The latter uses a caller-selectable Git executable to resolve
system/user `core.excludesFile` settings and ordinary config includes; the user value overrides the
system value, unset values use the XDG default, and an explicitly empty user value disables the
global source. Missing Git and config lookup failures are reported instead of falling back. Native
captures cover both scopes on Sapling `.git` mode and both Jujutsu modes; Sapling `.sl` mode does
not read Git global sources. Native `gitdir`, `onbranch:main`, and matching
`hasconfig:remote.*.url` conditional includes are also captured on macOS and Debian 13 Linux
aarch64/x86_64. Repository-local `core.excludesFile` precedence is captured for Sapling `.git` mode
and both Jujutsu modes; Sapling `.sl` ignores Git config. The Jujutsu policy supplies its internal
Git store as condition context for non-colocated workspaces unless the caller provides `GIT_DIR`.
With a caller-provided `GIT_DIR` pointing at a separate `.git` directory, Git resolves a matching
global include while native Sapling and Jujutsu still leave the workspace probe visible. This
divergence is now captured across macOS arm64, Git 2.56/macOS arm64, and Debian 13 Linux aarch64 and
x86_64; Windows CI asserts the Jujutsu behavior. The library's `read_git_config=True` option follows
Git's resolution as specified.
Case-insensitive `gitdir/i` matching is additionally captured on macOS and Debian 13 Linux: an
uppercase path pattern matches Sapling `.git` mode and colocated Jujutsu, while Sapling `.sl` and
non-colocated Jujutsu do not match. Windows capture validates the Jujutsu modes in native CI.
Git 2.56's `worktree:` and case-insensitive `worktree/i:` conditionals are captured on Git 2.54,
2.47, and 2.56 profiles. With Git 2.56, Sapling `.git` mode follows both included
`core.excludesFile` values, while Jujutsu 0.47.1 colocated mode does not honor either include
natively even though `git config` resolves them; the read-Git-config policy follows Git's result.
Non-colocated Jujutsu does not match because its internal store is bare. The policy contract now
documents this concrete divergence. Broader client/platform profiles remain open. Full Jujutsu
0.45.1 captures extend the configuration matrix to the pre-0.46 client on macOS arm64 and Debian 13
x86_64; their captured global, conditional, environment, repository-local, and pattern probes match
the candidate behavior, while the expected legacy symlink-following result is recorded explicitly.
Native CI recaptures this full profile with the pinned release asset and verifies it alongside the
focused 0.45.1/0.46.0 symlink boundary. The full 0.46.0 configuration and pattern capture is now
committed and replayed for Windows as well as macOS and Debian x86_64. The 0.47.0 macOS and Windows
full captures also replay the supported configuration subset. Committed Windows captures assert the
version boundary: 0.45.1 follows nested symlinked `.gitignore` files, while
0.46.0 and 0.47.1 skip them. Fresh run artifacts are retained for seven days; symlink creation may
be explicitly skipped by the runner.

**Additional configuration evidence:** an isolated Sapling/Jujutsu workspace sets
`GIT_CONFIG_GLOBAL` before initialization. Sapling `.git` mode and both Jujutsu modes use the
alternate config file; Sapling `.sl` mode does not. `read_git_config=True` follows Git's
environment-selected config. The behavior is captured on macOS arm64, Debian 13 Linux aarch64 and
x86_64 with Git 2.47.3, Debian 13 x86_64 with Git 2.56.0, and Windows Jujutsu. This adds one
environment-selected config path; it does not close the wider client/version/profile coverage gap.
Native live checks now also cover `GIT_CONFIG_COUNT` entries for `core.excludesFile`: Sapling `.git`
mode and both Jujutsu modes honor the injected value, while Sapling `.sl` mode ignores it. The
`read_git_config=True` policies follow Git's resolution of the same environment entries. The
compatibility oracle now records this injected-config result in every Sapling/Jujutsu storage mode,
and its pinned-client CI captures fail if any mode diverges from the recorded behavior. Broader
environment-variable and client-version profiles remain open. A new `GIT_CONFIG_NOSYSTEM=1` probe
with an explicit `GIT_CONFIG_SYSTEM` path confirms the system ignore is suppressed across all four
Sapling/Jujutsu modes on macOS 26 arm64; native Linux and Windows capture jobs now verify the same
profile behavior.

A focused Sapling release profile now compares 0.2.20261028, 0.2.20261102, and 0.2.20261103 using
identical Debian 13 ARM64 fixtures. It probes directory-only `target/` rules below missing and empty
`.gitignore` files, plus a nested ignore file below an empty parent source. In the older capture,
Sapling `.sl` mode leaves all four paths visible while `.git` mode ignores them; in the later
captures, both modes ignore all four. This is a bounded observed release/mode difference, not a claim
of full release-to-release dialect conformance. The official [0.2.20261102 release notes](https://github.com/meta/sapling/releases/tag/0.2.20261102-153821%2Ba53273dc)
identify the missing/empty `.gitignore` behavior as a fix. The 0.2.20261102 profile matches all four
probes in both modes on Debian 13 ARM64; native CI also recaptures the fix release on Windows x64.

The 0.2.20261028 Sapling client also has Debian 13 ARM64 and x86_64 source/configuration captures
alongside Jujutsu 0.47.1. Dedicated isolated probes now confirm that both tested path-pattern groups
panic with `StripPrefixError` (exit 101) in `.sl` mode on Debian 13 ARM64 and x86_64 as well as
Windows Server 2025 x64; these are client errors, not candidate matches. The same 13 cases match in
`.git` storage mode. Combined captures skip only `sapling.sl-mode.pattern_discovery` while checking
the full pattern matrix in `.git` mode plus source discovery, global and conditional configuration,
environment-selected configuration, and repository-local precedence. Jujutsu's pattern group runs
normally. Native CI recaptures the profiles from checksum-pinned Sapling and Jujutsu clients.

The nested-workspace boundary probe now confirms that Sapling stops at nested workspaces using the
same storage marker, but traverses into a child using the other marker. Jujutsu stops at nested
`.jj` workspaces for all colocated/non-colocated parent and child combinations. The portable
walkers now follow those boundaries and keep traversal out of `.jj`, `.git`, and the applicable
`.sl` metadata. Disposable native captures cover macOS arm64 and Debian 13 Linux aarch64/x86_64;
Jujutsu's nested `.jj` behavior is additionally captured on version 0.46.0/macOS arm64 and Debian
13 x86_64. Native CI recaptures the Linux profile and checks Jujutsu on Windows.
These results cover workspace boundaries only, not VCS membership.

The Git-compatible rule matrix now also checks escaped leading `#`/`!`, zero-directory `**/`
matching, and `?` inside recursive path components, with a length-control path. Native Sapling and
Jujutsu 0.47.1 results match on macOS arm64 and Debian 13 Linux aarch64/x86_64; Jujutsu 0.46.0
matches on macOS arm64 and Debian 13 x86_64. Both Jujutsu releases are recaptured in CI where the
pinned client is available. Walker and direct-decision tests replay these cases. The matrix remains
a focused syntax sample rather than complete Git-ignore dialect coverage.

Sapling's optional membership-aware walk now uses `sl status --all --print0` and compares native
status states with policy decisions and walker selections in both traversal orders. The live
fixture covers clean, modified, added, removed, missing, ignored, and unknown paths; a tracked file
matching `.gitignore` remains selected as included because membership is independent from rule
matching. The check runs with the client-enabled native integration suite. Jujutsu now has an
opt-in membership query based on `jj --ignore-working-copy file list` rather than `jj status`,
which snapshots the working copy. The saved `@` tree identifies versioned paths; present files
missing from that tree are unversioned, while missing unlisted paths and directories remain
unknown. A live fixture checks policy selections in both walk orders and confirms the operation ID
does not change during membership queries. Both scheme adapters retain the lexical query path for
membership lookup, so tracked dangling symlinks remain versioned even though the policy resolves
their targets for rule evaluation. Sapling/Jujutsu broader client and configuration profiles
remain open.

The nested symlinked `.gitignore` probe now confirms a source-layout difference: Sapling `.sl` mode
follows a symlink to an ignore file outside the workspace, while Sapling `.git` and Jujutsu skip
that source. The portable Sapling policy follows this only in `.sl` mode. Committed macOS and Debian
13 Linux aarch64/x86_64 captures retain all four native outcomes; a Windows Server 2025 capture
confirms the two Sapling results and both Jujutsu 0.47.1 modes. Unsupported symlink creation is
reported as a skip. Jujutsu 0.45.1 follows the same nested symlink in both modes; 0.46.0 changed to
skip it, which 0.47.1 also does. The Jujutsu config now exposes
`follow_symlinked_gitignore=True` for the older behavior. Focused 0.45.1 and 0.46.0 captures are
retained on macOS arm64 and Debian 13 x86_64, with CI recapturing the Linux release boundary.
The full Jujutsu policy corpus is also captured against 0.46.0 on Debian 13 x86_64; native CI
recaptures it and checks both workspace modes, source precedence, pattern decisions, and config
probes against the candidate contract.

The Git-compatible path corpus now includes five additional probes for character-class ranges,
nested basename matching, and directory-only rules with a same-named file control. All five match
on macOS for Sapling 0.2.20261103 and Jujutsu 0.45.1/0.47.1, and on Windows for Sapling 0.2.20261103
and Jujutsu 0.45.1/0.46.0/0.47.1. Debian 13 ARM64 and x86_64 captures match for Sapling
0.2.20261103/Jujutsu 0.47.1; x86_64 captures also match for Jujutsu 0.45.1 and 0.46.0. The results
are incorporated into the versioned compatibility profiles. Broaden these path probes further only
where native behavior or a concrete consumer need identifies a meaningful gap.

**Linked Git worktree source layout:** native captures now confirm Git and Sapling `.git` mode read
`info/exclude` from the shared Git directory, while colocated Jujutsu reads the linked worktree's
own Git directory. The policy metadata retains both paths and each scheme selects its captured
source. This is covered on macOS arm64 and Debian 13 Linux aarch64/x86_64.
The Jujutsu-only linked-worktree probe is also captured on macOS arm64 and Windows Server 2025 x64;
the Windows job recaptures it against pinned Jujutsu 0.47.1 and checks the Git/Jujutsu distinction.

**Next unfinished slice:** broaden Mercurial sparse profile and status-transition coverage, then
compare remaining workspace-membership and configuration behavior across the captured VCS profiles.
Sapling and Jujutsu already have pinned cross-version profiles: Sapling
0.2.20261028/0.2.20261102/0.2.20261103 and Jujutsu
0.45.1/0.46.0/0.47.0/0.47.1. The full Sapling 0.2.20261102 profile matches on Debian 13 ARM64,
x86_64, and Windows Server 2025 x64. The Jujutsu 0.47.0 profile matches on macOS arm64 and Windows
Server 2025 x64; Linux is excluded because the published 0.47.0 Linux binary has a dependency error
fixed in 0.47.1. The full Jujutsu 0.45.1 profile now replays configuration and legacy symlink
behavior on macOS arm64, Debian 13 x86_64, and Windows Server 2025 x64. Broader cross-version
configuration coverage remains open. TFVC remains
deferred until its workspace/server fixture is reproducible. Darcs walking has native
membership-aware selection checks in both traversal orders
and a cross-profile nested-repository case. Its local/global/configured source overlap matches on
macOS arm64 and Debian Linux aarch64/x86_64. Darcs 2.16.3 is now captured on Windows and matches
17/18 closed candidates; the sole version-specific difference is the documented `boringfile`
override of local boring rules. The official download page lists 2.16.3 as its Windows binary,
while 2.18.5 is current stable and the Windows packager role is unfilled, so current-release Windows
conformance remains unverified. TFVC's
seven research cases are source-derived/open; Microsoft's TFVC add and workspace docs require a
configured workspace for `.tfignore` behavior ([TFVC-DOC]). This repository has neither a TFVC
server/workspace fixture nor a configured server, so
keep those cases unrun instead of treating Visual Studio availability as a native oracle.

The Windows workflow now adds a separate probe for Sapling 0.2.20261028 `.sl` path-pattern
behavior. It records the 13-path and extended pattern commands as matched, mismatched, or native
client errors without treating an error as a conformance result. The Windows capture now confirms
both commands panic with `StripPrefixError` (exit 101), matching the Debian observations; both
probes have `candidate_matches: null`. The result is retained as
`tests/oracles/compat/results/sapling-0.2.20261028-sl-patterns-windows-x64.json`. The full legacy
`.sl` matrix remains excluded because the native client fails before returning path matches; the
newer Sapling `.sl` profile continues to provide the conformance evidence for that mode.

The SVN baseline is retained below for reference: its initial property policy, inherited
`svn:global-ignores` discovery, switched-subtree scoping, sparse-depth boundaries, listed externals,
and opt-in membership are implemented. The 21-case oracle includes all 13 status-profile probes from
the handoff; the two import-reference probes remain outside the status-walking contract. Live
membership comparisons cover normal, modified, added, deleted, missing, replaced, obstructed, and
conflicted entries, plus ignored unversioned entries. The transition fixture checks exact included
and ignored file selections in both traversal orders, including Subversion's unversioned conflict
sidecars. A scheduled directory deletion retains native
membership for its deleted directory and tracked descendant while leaving a new child unversioned.
Versioned directories and file/directory
externals have separate native evidence. A new membership-aware walker check matches native
selections inside directory externals in both traversal orders, using each external working copy's
own status. A live interrupted-checkout probe records native `incomplete` status on the checkout
root; membership discovery keeps that root versioned, and the walker selection matches the remaining
native versioned file entries. Paths omitted by sparse status remain unknown by design.
An absent queried candidate omitted from verbose status also remains membership-unknown even when
an ignore property matches its name. At sparse `depth=empty`, a tracked file omitted by status stays
unknown, while a local unversioned file that native status lists remains walkable in both traversal
orders. The result also holds when the policy and walker are rooted at the sparse subtree. This
differs from Mercurial's sparse-profile omission of physically present untracked files.
Further work is broader native status traversal and configuration-precedence profiles; do not
classify omitted paths as unversioned without new native evidence.

Repeat VCS-00 through VCS-08 for each additional system. Reuse the conformance harness and shared
contracts, but keep each scheme's source discovery, semantics, configuration, and limitations
independent. Reassess shared abstractions only after at least two real implementations expose a
repeated need.

## Research-specific probes to carry forward

The chosen system's probe list in the checkpoint is the starting corpus. Preserve its named edge
cases: Mercurial regex/glob/rootglob and scoped subinclude (keeping command-line file-selection
patterns separate from ignore policy); Perforce default versus explicit
`P4IGNORE`, order and `P4CONFIG`; SVN inherited properties above the checkout root and sparse working
copies; TFVC nested
`.tfignore`; Fossil's separate ignore/clean/keep behavior; Breezy exception and regex forms;
remaining Darcs regex locale and platform cases; and
Sapling/Jujutsu behavior beyond the captured `.gitignore`, XDG ignore, `.git/info/exclude`,
`core.excludesFile`, and source-precedence subset remains a research question until exercised against
additional pinned native clients and platform profiles. Primary
Mercurial references: [ignore-file syntax](https://www.mercurial-scm.org/help/topics/hgignore) and
[file patterns](https://mercurial-scm.org/help/topics/patterns).

For Mercurial, Windows case-sensitive glob behavior is now captured. Regex extension probes cover
unanchored search, start anchoring, inline flags, newline matching, lookahead/lookbehind, word
boundaries, and backreferences. Three more probes capture ASCII (`a`), locale (`L`), and verbose
(`x`) inline flags against Mercurial 7.2.4/macOS arm64, 6.7.2/hosted Ubuntu x86_64, and 7.1.2/Windows
x86_64. They match the evaluator, including the Windows-specific `(?L)` result for `é`; live-client
differential tests exercise them on client-enabled profiles. Captured regex and
source-precedence results for additional profiles remain open. A
self-referential include-source symlink loop is now
captured on macOS arm64 and Windows x86_64: Mercurial warns and skips the source, and the policy
reports incomplete discovery. The warning differs by platform (`Too many levels of symbolic links`
on macOS and `Invalid argument` on Windows). Mercurial 7.2.4 on macOS also raises an assertion when
a `subinclude:` inside an included pattern file is evaluated; the portable loader currently discovers
and evaluates that nested source. This is captured as a known native-client divergence, not as
conformance with the failing native result. Mercurial's
command-line `include:` notation
reads patterns from a file; it does not execute a command. That file-selection feature is separate
from this ignore-policy expansion. Native help documents regex/glob/rootglob and says an ignore
rule may match a path or any prefix directory. Pattern-file `include:` and directory-scoped
`subinclude:` have separate documented behavior.
Native captures confirm an undecodable byte in a glob pattern on macOS and Linux; an actual
undecodable filename walk is verified on Linux and skipped on the tested macOS filesystem, which
rejects those names.

The original versioned 48-case captures confirm root `.hgignore` `include:` loads patterns without
rebasing, `subinclude:` scopes them to its directory, nested `.hgignore` files are
not auto-loaded, and syntax switches reset in included sources. They also confirm prefix-directory
matches, glob braces, embedded `**`, question-mark matching across separators, the client's
invalid-syntax warning behavior, unanchored regex search, start-anchor behavior, and scoped inline
regex flags. Lexical
comments/backslash parity, trailing whitespace rules, glob negation behavior, include cycles,
configured-source ordering, repeated physical sources under distinct scopes, tracked-path
distinctions, and unreadable sources already have probes; preserve their captured outcomes rather
than treating them as open questions.
The earlier observation that `include:rules.txt` failed was not reproducible in a fresh repository.
The native include-cycle case instead recursed until Mercurial raised `RecursionError`; the library
reports a bounded incomplete-discovery diagnostic. The subinclude native case returned an ignored
result but then crashed while formatting provenance. Refer to the per-case capture, not this summary,
for exact process status and normalized output.

## Exit criteria for claiming support

- The supported client/version/platform profile is named.
- Source discovery, rule evaluation, and traversal each have independent native comparisons.
- Provenance and incomplete discovery are represented accurately.
- Version-control membership is not conflated with ignore matching.
- Directory pruning is proven safe for the supported semantics.
- Public API, typing, package, and local/hosted CI checks pass.
- Skips and known divergences are published alongside the support claim.
