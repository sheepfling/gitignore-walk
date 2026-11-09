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
Subversion property policy is implemented, and its first expanded matching corpus passes on both
captured profiles; broader discovery and working-copy conformance remain open. The
implementation research handoff records 94 native assertions against Git 2.47.3 and ripgrep 14.1.1
on Linux, plus one malformed-input observation. It also supplies 88 non-Git candidate cases: 67
documentation/source-derived and 21 open questions. The Mercurial native corpus has 48 path
probes and six traversal fixtures, captured with Mercurial 7.2.4 on macOS arm64 and 7.0.1 on Linux
aarch64 and x86_64. All 46 boolean expectations and the structured invalid-syntax expectation agree
across all three profiles, as do all six walk fixtures; parent walks stop at nested `.hg`
workspaces and root walks stop at `.hg` metadata.
An undecodable glob pattern matches native `debugignore` on all three profiles, and actual byte-path
walks match native status on both Linux architectures; the walk test skips macOS because its
filesystem rejects such names. Mercurial also compares Unicode paths by exact code-point spelling: an
NFC glob does not match the equivalent NFD query. Forty-six `debugignore` queries exit normally.
One other query prints an ignored decision, then exits with a
formatting error; that `subinclude` behavior is independently confirmed by a matching native
`status --ignored` walk fixture on all three profiles. The include-cycle case is a documented safe
divergence: the native client recurses and errors, while the library detects the cycle and reports
incomplete discovery. Results are recorded
under `tests/oracles/hg/`. The initial SVN property policy evaluates `svn:ignore`, inherited
`svn:global-ignores`, Subversion's built-in default global patterns, patterns from an explicit
`config_dir/config` runtime file, and additional caller-supplied global patterns after native
property discovery. An explicit runtime setting replaces built-in defaults; ambient configuration
files and machine/user Registry values are discovered on Windows. Registry read failures carry
diagnostics; the dedicated disposable Windows Registry/native comparison has been reviewed and
captured against Subversion 1.14.5 SlikSvn on Windows Server 2025 x86_64. Live native status
comparisons on the development client cover built-in defaults and per-user file precedence; the
dedicated SVN job runs the same policy integration tests
on its Linux client before capturing the broader oracle fixture.
The initial SVN property fixture covers seven ignored paths and local, inherited, nested, runtime,
negation, case, and tracked-file distinctions; native results match on Subversion 1.15.0/macOS arm64
and 1.14.5/Linux aarch64. A sparse-depth `empty` fixture confirms directory properties remain
available and apply to new files; an excluded-depth fixture confirms status stops at the excluded
directory and its properties are unavailable. Both match on all three profiles, and policy walks
stop at excluded roots while explaining direct queries there as incomplete. A separate native case
confirms parent `svn status` reports a nested working-copy directory but does not enumerate files
beneath it; the policy walk excludes unrelated nested `.svn` roots and descends into externals listed
by native status, including repository-root-relative URLs with and without pinned revisions,
parent-relative URLs, absolute URLs, server-root-relative URLs, and scheme-relative URLs served by a
loopback-only disposable `svnserve` repository.
Explicit and standard file-based runtime-config discovery plus built-in defaults
are implemented; Windows Registry precedence needs native confirmation, while versioned directory
membership and broader traversal/path behavior remain open. Fossil's eleven-case
ignore-glob corpus is captured on 2.28/macOS arm64 and 2.26/Linux aarch64: ten boolean candidates
agree, including hash-leading patterns, literal backslashes, and ignored-directory descendant
suppression; additional tokenizer edges remain open. Breezy's corpus is now
captured on 3.3.24/macOS arm64 and Linux aarch64 with isolated user configuration: twenty-four boolean
cases agree, including global-versus-branch exception priority and built-in defaults without a user
ignore file. A child exception under an ignored directory exposes sibling files as unknown in status.
The exception pattern opens the ignored directory even when its named target is absent.
Named regex captures are rewritten with a warning; malformed RE patterns fail with exit code 3.
The initial Breezy evaluator and typed selection are implemented and pass all twenty-four boolean
candidate cases, including exact-path versus `/**` strong exclusions, `BRZ_HOME` global ignores,
exception-aware directory traversal, anchored RE matches, and named-capture normalization. A new native
status capture verifies that an exception under ignored `cache` exposes sibling files; policy walk
results match native unknown and ignored paths in both directions on both profiles. Broader
RE semantics, Windows configuration paths, and
source-location precedence remain open. Native captures also show that the documented global inline
regex flag example is rejected with exit code 3 in both pinned Breezy profiles. Other non-Git
candidate cases have
no captured native result. The November
7 checkpoint separately records seven Git probes. These captures do not establish complete
cross-platform behavior.

The initial Perforce evaluator and typed selection are now implemented for the caller-selected
workspace subset. It consumes explicit/environment `P4IGNORE` source lists or the two documented
default names, supports the captured wildcard/directory/exception syntax, and keeps ignored
directories traversable. All 30 boolean candidates and one filesystem-dependent case agree with
P4/P4 Server 2026.1 captures on macOS arm64, Debian 13 Linux x86_64, and Ubuntu 24.04 Linux x86_64.
Captures compare `p4 add -n` with `p4 ignores -i -v` and cover source-list precedence, configured
`P4CONFIG` filenames, built-in `.p4root` exclusions, exception behavior, and ignore-file-root
anchoring. Native workspace discovery and broader syntax remain open.

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

| Order                     | VCS                                                       | Intended feature slice                                                                            | Main oracle questions and gate                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| ------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1 (recommended)           | Mercurial                                                 | `.hgignore` regex, glob, root/configured sources; nested `include`/`subinclude`; explain and walk | Captured 48 `debugignore` cases and six status walk fixtures on 7.2.4/macOS arm64 and 7.0.1/Linux aarch64 and x86_64, plus Mercurial 7.1.2/Windows Server 2025 x86_64. On Windows, 42 candidate comparisons match with no differences; the include-cycle observation remains a documented safe divergence. Five path cases and one symlink-dependent walk are explicitly skipped, while five walk fixtures match. On the other profiles, all 46 boolean expectations and the structured invalid-syntax expectation agree. Include cycles are a documented safe divergence: the native client recurses, while the library returns an incomplete-discovery diagnostic. Linux byte-path walking matches native status, and `.hg` metadata is a traversal boundary. Windows evidence and skips are retained under `tests/oracles/hg/results/`; broader syntax remains open. |
| 2                         | [SVN](../../tests/oracles/svn/README.md)                  | Bounded property-driven working-copy policy, including inherited directory properties             | Six status cases pass on Subversion 1.15.0/macOS arm64 and 1.14.5/Linux aarch64 and x86_64. Sparse `empty` and `exclude` depths, nested working-copy boundaries, and native-listed externals with repository-root-relative, parent-relative, absolute, server-root-relative, and scheme-relative URLs are covered. The Windows Registry capture on Subversion 1.14.5 SlikSvn confirms Registry-only lookup and user-INI precedence against native status; the reviewed capture is retained under `tests/oracles/svn/results/`. Versioned membership and broader path behavior remain open. Handoff has 13 status and 2 import-reference cases.                                                                                                                                                                                                                          |
| 3                         | Fossil and [Breezy](../../tests/oracles/breezy/README.md) | Mature Fossil and Breezy conformance; broaden regex, source, and traversal coverage               | Fossil has an initial effective-setting evaluator and eleven oracle cases on 2.28/macOS arm64 and 2.26/Linux aarch64. Ten boolean cases match native results, including hash-leading patterns and literal backslashes. Its included/ignored walker selections match native `extras` for the captured directory fixture, including checkout-marker exclusion. Broaden lexical/path and workspace profiles; Fossil `clean-glob`/`keep-glob` remain out of scope. Breezy has an initial typed policy that matches all 24 boolean candidates on two 3.3.24 profiles, including `BRZ_HOME`, exact-path strong exclusions, and exception-aware traversal. Resolve broader RE behavior, platform configuration, source precedence, and pruning safety.                                                                                                                         |
| 4                         | [Perforce](../../tests/oracles/perforce/README.md)        | Mature the initial `P4IGNORE` evaluator and opt-in `P4CONFIG` resolution                          | Three disposable local `p4d`/client profiles (macOS arm64, Debian 13 x86_64, Ubuntu 24.04 x86_64) match all 30 boolean candidates plus a platform-dependent case. Native rule checks capture `p4 ignores -i -v` separately from `p4 add -n`, including built-in configured `P4CONFIG` filename and `.p4root` exclusions. Opt-in config resolution uses `p4 set` and covers config discovery, config-over-environment precedence, and nested config selection. Root-anchored rules resolve against the containing ignore file, including nested rules. Broaden paths and configuration edge cases.                                                                                                                                                                                                                                                                       |
| 5                         | Darcs and TFVC                                            | Mature native membership-aware Darcs candidate walking; investigate nested `.tfignore` profiles   | Darcs has six closed oracle cases on 2.18.5/macOS arm64 and 2.18.4/Debian 13 x86_64. Walker output matches native ignored and managed file behavior in both traversal orders, including trailing-space and newline-bearing names on POSIX. Managed paths use NUL-delimited output, with targeted native add checks when candidate output becomes ambiguous. Both clients keep local rules active alongside `boringfile`, contrary to current docs; the policy delegates to Darcs, so no Python precedence rule is needed. Broaden platform/configuration coverage. TFVC has seven unrun cases and still needs an automatable client.                                                                                                                                                                                                                                    |
| 6 (compatibility studies) | Sapling and Jujutsu                                       | Reuse Git-ignore evaluation where modes share the tested dialect; keep storage discovery separate | Four disposable mode probes on Sapling 0.2.20261103/Jujutsu 0.47.1 macOS arm64 show the same `.gitignore` behavior in Sapling `.git`/`.sl` modes and Jujutsu colocated/non-colocated modes. `.hgignore` and `.jjignore` do not suppress candidates. Jujutsu status snapshots its workspace, so do not use it as a read-only evaluator on user repositories. Global excludes, mode discovery, and broader paths remain open; no extra scheme policy is justified by these probes.                                                                                                                                                                                                                                                                                                                                                                                        |
| adjacent, opt-in          | ripgrep and Docker                                        | Scanner/context policies outside the VCS scheme set                                               | Handoff has 16 native ripgrep cases. Keep opt-in and separate from VCS selection; Docker context rules need their own profile.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |

Reorder this list when user demand, supported client automation, or native probe results justify it.
Do not implement a candidate merely because a CLI is installed. Each implementation starts with a
scope record and reproducible oracle fixtures.

## Work sequence

### VCS-00 — Capture and select the first additional scheme

**Priority:** P0 · **Depends on:** none · **Status:** initial Mercurial capture complete; implementation
gate open

The runner in `tests/oracles/hg/` captures 48 cases on Mercurial 7.2.4/macOS arm64 and 7.0.1/Debian
13 Linux aarch64 and x86_64. All 46 boolean expectations and the structured invalid-syntax
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
from evaluating `.hgignore` and configured ignore sources. A 31-case Perforce native
capture verifies an isolated local server/client workflow on P4/P4 Server 2026.1 across macOS arm64,
Debian 13 Linux x86_64, and Ubuntu 24.04 Linux x86_64. The initial portable evaluator and typed
selector match all 30 boolean candidates plus one filesystem-dependent case. Separate native
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
32 MiB total, and 20,000 bytes per compiled pattern). Tests now exercise each ceiling and verify
source-graph overflows report incomplete discovery while pattern overflow raises a contextual parse
error. These are safety ceilings, not compatibility promises; measure them with representative
repositories and expose configuration only if user need justifies it.

### VCS-02 — Build a reusable native conformance harness

**Priority:** P0 · **Depends on:** VCS-00

**Status:** Scheme-specific disposable-repository runners capture Mercurial matching and walking,
Subversion status, and Fossil extras on native profiles. Thin `scripts.ci oracle-*` commands run
locally and in dedicated hosted jobs with retained artifacts. A cross-scheme harness contract remains
open; keep dialect setup and observation schemas scheme-specific until repeated needs are demonstrated.

Import and adapt the research handoff's runner/case structure without treating it as library tests.
Create disposable repository/workspace fixtures and isolated client configuration. Capture native
client identity/version/platform, locale, exact command, raw output, stderr and exit status with each
result. The harness must distinguish rule matching from native add/list/status behavior and traversal
output. It must report missing clients as skipped, never passed, and keep captured fixtures
deterministic where live clients are unavailable.

**Done when:** one harness invocation runs selected probes, records captured/failed/skipped status
and client profile, and cannot read or mutate the developer's real VCS configuration or repository.
Captures must preserve enough raw data to audit a normalization step. The current GitHub job only
captures Mercurial observations; client errors and candidate differences remain review data until a
versioned behavioral gate is defined.

### VCS-03 — Specify source discovery and boundaries

**Priority:** P1 · **Depends on:** VCS-00, VCS-02

**Status:** Explicit source order and opt-in `hg config --debug ui` discovery are covered on both
captured platform profiles, including named global entries and repository-local config. Native
probes confirm warnings for missing `include` and configured `ui.ignore` files; Mercurial silently
skips a missing `subinclude`, while the policy conservatively reports incomplete discovery. A
symlinked `include` to a file outside the workspace is followed natively and by the policy, with
canonical source and workspace-root scope preserved. POSIX ownership trust is captured by the
Linux oracle: untrusted repository `.hg/hgrc` settings are ignored by both Mercurial and opt-in policy
discovery. Native probes also confirm unreadable included files are warned about and skipped; the
policy preserves the false match result while marking source discovery incomplete. Broader platform
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

**Status:** Initial portable evaluator and captured-profile tests are implemented. Include loading now
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
are implemented, including opt-in discovery through the installed Mercurial client. Broader config
trust, include, and platform behavior remain open.

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
versioned under the oracle result directories. Mercurial's POSIX undecodable-byte command argument,
POSIX permissions, and symlink-source cases remain skipped there. The broader Python/platform
matrix remains open.

Run the supported Python/platform matrix with native-client probes where clients are available.
Cover path separators, case behavior, Unicode and undecodable names where supported, symlinks, and
client-version differences. Verify wheel/sdist contents, installed API imports, docs, and user-facing
limitations.

**Done when:** the support matrix lists exact client versions/platforms, passes and skips; package
checks pass; no skipped native comparison is described as conformance.

### VCS-08 — Stabilize and release the first additional scheme

**Priority:** P1 · **Depends on:** VCS-07

Review the public contract, limitations, migration impact, README examples, API docs, and release
notes. Record known divergences and link each one to a test or issue. Keep the wheel name decision
separate unless the new scope makes a product rename necessary.

**Done when:** public docs and release artifacts match the tested support profile and all release
checks are green.

### VCS-09 — Add later schemes one at a time

**Priority:** P2 · **Depends on:** VCS-08

Repeat VCS-00 through VCS-08 for each additional system. Reuse the conformance harness and shared
contracts, but keep each scheme's source discovery, semantics, configuration, and limitations
independent. Reassess shared abstractions only after at least two real implementations expose a
repeated need.

## Research-specific probes to carry forward

The chosen system's probe list in the checkpoint is the starting corpus. Preserve its named edge
cases: Mercurial regex/glob/rootglob and scoped subinclude (keeping command-line file-selection
patterns separate from ignore policy); Perforce default versus explicit
`P4IGNORE`, order and `P4CONFIG`; SVN inherited properties and sparse working copies; TFVC nested
`.tfignore`; Fossil's separate ignore/clean/keep behavior; Breezy exception and regex forms; the
remaining Darcs boring-file lexical cases; and Sapling/Jujutsu global excludes and
mode discovery beyond the captured in-tree `.gitignore` subset. These remain research questions
until exercised against pinned native clients. Primary
Mercurial references: [ignore-file syntax](https://www.mercurial-scm.org/help/topics/hgignore) and
[file patterns](https://mercurial-scm.org/help/topics/patterns).

For Mercurial, remaining probes include Windows case behavior; regex features beyond the captured
unanchored search, start anchor, inline flags, and newline matching; and additional include-source
symlink boundary forms. Mercurial's command-line `include:` notation reads patterns from a file; it
does not execute a command. That file-selection feature is separate from this ignore-policy
expansion. Native help documents regex/glob/rootglob and says an ignore rule may match a path or any
prefix directory; pattern-file `include:` and directory-scoped `subinclude:` have separate
documented behavior.
Native captures confirm an undecodable byte in a glob pattern on macOS and Linux; an actual
undecodable filename walk is verified on Linux and skipped on the tested macOS filesystem, which
rejects those names.

The versioned 48-case captures on all three profiles confirm root `.hgignore` `include:` loads
patterns without rebasing, `subinclude:` scopes them to its directory, nested `.hgignore` files are
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
