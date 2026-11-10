# Preparing another ignore scheme

This project supports Git, an initial portable Mercurial ignore policy, an initial Breezy
pattern-evaluation policy, an initial Fossil effective-setting policy, and an initial
native-discovery Subversion property policy. These additional schemes remain under conformance
development. This note records the extension boundary and evidence needed before adding further VCS
formats; it does not add a runtime plugin API.

The dependency-ordered implementation plan is in the [VCS expansion backlog](vcs-expansion-backlog.md).

## Keep four responsibilities separate

1. **Source discovery** finds the applicable files, properties, configuration, repository boundary,
   and defaults for a target.
2. **Dialect evaluation** parses and applies that scheme's matching, precedence, anchoring, and
   exception rules.
3. **Execution backend** evaluates the dialect, whether through a native client or a portable
   implementation. Unsupported behavior must be explicit; fallback must not silently change the
   scheme.
4. **Traversal** decides which entries to return and whether an ignored directory can be pruned
   without hiding an included descendant.

Implement a new scheme as a policy and a tagged config/selection variant. Keep its matcher and config
types scheme-specific. Extend the exhaustive config switch, exports, typing contract, and behavior
tests together. `IgnorePolicy` is the built-in walker boundary, not a third-party policy plugin
promise.

Built-in implementations are grouped under `src/gitignore_walk/_schemes/<scheme>/`. Shared policy
contracts, selection, and traversal stay directly under `src/gitignore_walk/`. Keep scheme-specific
parsers, source discovery, native adapters, and policy code inside their scheme package. For Git,
`native.py` and `portable.py` are the execution backends; the `_ignore_*` and `_patterns.py` modules
hold Git-dialect parsing and types. Selection remains an explicit typed union and exhaustive switch;
it is not a dynamic registration mechanism.

`IgnoreDecision.ignored` answers only whether the scheme's ignore rules match. It does not say whether
the path is already versioned, whether an add command would accept it, or whether traversal can skip
its subtree. Preserve provenance where available (`scheme`, `source`, line or property, scope,
reason); report incomplete discovery with diagnostics. Keep traversal pruning as a separate,
conservative policy capability.

## Conformance evidence required

Test rule evaluation and directory traversal separately: one cannot establish the other. For each
supported client/version/platform profile, compare results with the native client and record the
profile and skipped tests. Do not call a skipped native test a pass or claim native equivalence from
documentation alone.

Build focused fixtures for at least:

- parent-directory exclusion versus excluding only its contents, with a child exception;
- rule order, negation/exception precedence, nested rule scope, and path anchoring;
- source discovery precedence, global/config sources, and boundaries at nested repositories or
  working copies;
- tracked/versioned paths separately from ignore-rule matching;
- symlinks, path encoding, case behavior, and platform-specific path handling;
- incomplete or unavailable sources and the resulting diagnostics;
- safe pruning, including ignored parents whose descendants can be included;
- native and portable backends, with unsupported syntax or behavior made explicit.

Add scheme-specific edge cases from that VCS's own documentation and client behavior. For example,
Mercurial include/subinclude scoping and regex/glob modes, SVN inherited directory properties,
Perforce's configured ignore-file list, and TFVC nested `.tfignore` rules each require distinct
discovery and traversal fixtures; they should not be assumed to behave like Git negation.

## Current research checkpoint

The November 7, 2026 research checkpoint exercised seven native Git probes on Git 2.47.3/Linux. The
seven probe definitions are versioned under `tests/oracles/git/checkpoint_cases.json`, and a focused
test replays pattern candidates while separately exercising tracked-index behavior. The 79-case Git
corpus is now tested against portable and native policy contracts, and the 16 ripgrep scanner cases
have a separate captured inventory; see the [Git oracle notes](../../tests/oracles/git/README.md) and
[ripgrep oracle notes](../../tests/oracles/ripgrep/README.md). These cases confirmed parent blocking
versus contents-only exceptions, recursive `**/` behavior, last-match precedence, and the difference
between ordinary tracked-file handling and `--no-index` ignore-rule matching. The current Mercurial
capture covers the original 48 `hg debugignore` cases and six native status walk fixtures on macOS
arm64 with Mercurial 7.2.4, Linux aarch64 and x86_64 with Mercurial 7.0.1, and Windows Server 2025
x86_64 with Mercurial 7.1.2. Eight regex/glob byte-semantics cases are now captured on macOS and
Linux aarch64/x86_64; tests compare them against the installed client on client-enabled profiles.
Three additional inline-flag probes (`a`, `L`, and `x`) match Mercurial 7.2.4/macOS arm64 and
6.7.2/hosted Ubuntu x86_64, as well as the portable evaluator. Mercurial 7.1.2/Windows x86_64 also
matches these probes, with a platform-specific `(?L)` result for `é`. Live comparisons run on
client-enabled profiles; committed captures for other client versions remain open.
The full Mercurial test module passes in Debian 13 Linux containers on both architectures. The
differential library tests replay captured observations for each profile, while native-skipped
observations remain test skips. The
Windows oracle capture has 59 closed boolean comparisons and one matching structured invalid-syntax
result, with four explicit path skips. The Unicode digit-class query has no parseable `debugignore`
output, so native NUL status membership resolves its result; the include-cycle divergence remains open.
Windows Mercurial warns
and skips file or directory symlink sources, which the policy reports as incomplete discovery. Its
walk capture has six matching fixtures, including the repeated-source symlink-scope case. See the
[Mercurial oracle](../../tests/oracles/hg/README.md), the
[macOS matching results](../../tests/oracles/hg/results/hg-7.2.4-macos-arm64.json), the
[Linux matching results](../../tests/oracles/hg/results/hg-7.0.1-linux-aarch64.json), and the
[Linux x86_64 matching results](../../tests/oracles/hg/results/hg-7.0.1-linux-x86_64.json), the
[Windows matching results](../../tests/oracles/hg/results/hg-7.1.2-windows-x86_64.json), and the
[walk results](../../tests/oracles/hg/results/). On each Unix profile, 46 boolean cases and the
structured invalid-syntax expectation agree; the include-cycle query remains a documented safe
divergence. All six Unix walk cases agree, including case-sensitive matching, exact Unicode
normalization-form matching, undecodable pattern bytes, unreadable-source warnings with incomplete
discovery, and stopping walks at `.hg` metadata and nested workspaces. An actual byte-path walk
matches native status on Linux aarch64 and x86_64; the filesystem skips that case on macOS. A
separate subinclude query prints an ignored decision and then fails while formatting its trace. The
Windows captures confirm case-sensitive glob matching but do not establish full Windows conformance,
particularly for the skipped POSIX byte, permission, and symlink fixtures.

Mercurial's documented `.hgignore` syntax distinguishes regexp, unrooted glob, and rootglob rules;
its pattern docs distinguish `include` from directory-scoped `subinclude`. The implementation uses
those public contracts and native captures, not Mercurial source code. See the
[ignore-format documentation](https://mercurial-scm.org/help/topics/hgignore) and
[pattern documentation](https://www.mercurial-scm.org/help/topics/patterns).

The initial Subversion policy discovers versioned directory properties with `svn` and evaluates
`svn:ignore`, inherited `svn:global-ignores`, and caller-supplied runtime global patterns locally.
Its property, nested-working-copy, external, and sparse-depth fixtures agree with native
`svn status` on 1.15.0/macOS arm64 and 1.14.5/Linux aarch64 and x86_64. A versioned directory at
depth `empty` retains its `svn:ignore` property for new files; an excluded-depth path stops the walk
and direct decisions beneath it report incomplete property discovery. The policy walker also stops
at unrelated nested `.svn` roots and follows native-listed externals. It queries properties from
each listed external working-copy root and stops containing-working-copy property rules at that
boundary. Opt-in membership discovery uses verbose native status to classify listed entries while
keeping rule matches independent. The file-external case is captured on Subversion 1.15.0/macOS
arm64, 1.14.5/Linux aarch64 and x86_64, and 1.14.5/SlikSvn Windows x86_64. Live membership tests
pass on all four profiles. Paths omitted by sparse status remain unknown; broader status traversal
remains open. A collapsed unversioned-directory fixture confirms that `svn status` reports the
directory without enumerating its children on Subversion 1.15.0/macOS arm64, 1.14.3/Ubuntu 24.04
x86_64, and 1.14.5/SlikSvn Windows x86_64. A rule match for a physical child remains available,
while its native membership is unknown and the walker traverses independently of status omission.
The SVN oracle also includes newline- and tab-bearing filenames: the macOS native capture confirms
XML numeric-reference decoding, and top-down/bottom-up policy walks preserve both paths. Windows
skips this case because those filenames are not representable there; Subversion 1.14.5 Linux arm64
and x86_64 captures also confirm the paths and walks.
See the [Subversion oracle
notes](../../tests/oracles/svn/README.md).

The initial Fossil policy asks the native client for effective `ignore-glob` settings and evaluates
whole workspace-relative paths with SQLite `GLOB`. Its 43-case corpus was captured against Fossil
2.28/macOS arm64, 2.26/Linux aarch64 and x86_64, and 2.23/Ubuntu 24.04 x86_64. Native-backed
policy tests cover separator and quote forms, hash-leading patterns, literal backslashes, range
classes, Unicode `?`, case
sensitivity, class-negation markers, unmatched brackets, ASCII-only token separators, preservation
of Unicode whitespace, no-negation behavior, effective-setting discovery, and ignored-directory
pruning. A captured extras fixture checks included and ignored walk results against native output
across macOS and both Linux profiles, including exclusion of the Fossil workspace marker from
included results. Opt-in file-membership discovery uses structured Fossil JSON directory and
checkout-status responses, independently of ignore decisions; directories remain
membership-unknown. Other tokenizer boundaries and broader native/platform profiles remain open.
See the [Fossil oracle notes](../../tests/oracles/fossil/README.md) and
[Fossil glob documentation](https://fossil-scm.org/home/doc/trunk/www/globs.md).

The initial Breezy evaluator queries the native client for built-in rules, then loads its standard
user ignore file and root `.bzrignore`. Its 29 boolean candidates pass against Breezy 3.3.24/macOS
arm64, Linux aarch64 and x86_64, and Windows Server 2025 x86_64. The Windows capture uses an
isolated `BRZ_HOME`. A dedicated Windows 3.3.24 probe confirms the default AppData shell-folder
lookup: `breezy.bedding.user_ignore_config_path()` resolves `%APPDATA%/breezy/ignore`, and a marker
there appears in both native `brz ignored` output and the policy result. The probe report is
versioned in the Breezy oracle results. The native status fixture
verifying that a child exception opens an ignored parent and exposes sibling files matches policy
walk results in both traversal orders. Native
captures also include exact-path versus `/**` strong exclusions. The matcher follows Breezy's
documented rule that slash-containing patterns and regexes
match the complete workspace-relative path while other globs match the last path component. The
captured RE subset now covers anchored path matching and named-capture normalization. All four pinned
3.3.24 clients reject `RE:(?i)foo` with an invalid-pattern error, despite the published guide example.
Broader regex flags and restrictions and additional native Windows client profiles remain open.
See the [Breezy oracle notes](../../tests/oracles/breezy/README.md), [Breezy pattern
reference](https://www.breezy-vcs.org/doc/en/user-reference/patterns-help.html), and [Breezy ignore
reference](https://www.breezy-vcs.org/doc/en/user-reference/ignore-help.html).

The initial Perforce policy evaluates the caller-selected root without invoking a P4 client by
default. It reads the configured `P4IGNORE` list or checks `.p4ignore` and `p4ignore.txt`, supports
the captured wildcard, directory-only, and exception forms, and conservatively keeps ignored
directories traversable. Its 37 boolean cases agree with isolated P4/P4 Server 2026.1 captures on
macOS arm64, Debian 13 Linux x86_64, and Ubuntu 24.04 Linux x86_64, including configured-file order,
nested-source precedence, root-anchored matching relative to nested ignore files, and opt-in
`P4CONFIG` resolution. Three additional path-boundary cases separate `p4 add` rejection from rule
matching reported by `p4 ignores -i -v`. Lexical cases verify ASCII-space trimming and preservation
of tabs and interior spaces. Opt-in client-root discovery uses tagged `p4 -ztag info` data while
keeping the caller's traversal bound. Server views, broader path grammar, and other platform
profiles remain open. See the
[Perforce oracle notes](../../tests/oracles/perforce/README.md).

Darcs now has an initial native candidate policy. It combines `darcs whatsnew --look-for-adds` with
`darcs show files`, preserving the distinction between untracked add candidates, boring paths, and
already managed paths. Captures on Darcs 2.18.5/macOS arm64 and 2.18.4/Debian 13 x86_64 agree on
fifteen closed candidates, including an ASCII-only `[[:alpha:]]` result under both `C` and `C.UTF-8`
locales. The policy walker matches a native ignored-directory and tracked-file fixture in
included-only, ignored-only, and all-file selection modes in both traversal orders. Managed
inventory uses `darcs show files --null`; ambiguous candidate
summaries fall back to path-specific `darcs add --dry-run --reserved-ok` checks. This preserves
trailing spaces and handles newline-bearing names without parsing their display output. The policy
delegates ERE parsing and preference discovery to Darcs and holds one inventory for each walk. Darcs
2.18.4 and 2.18.5 keep local boring rules active alongside the configured `boringfile`, contrary to
the [configuration guide](https://darcs.net/Using/Configuration); this is recorded as a native
documentation discrepancy, not a Python-side rule. Broader path and platform coverage remain open.
Invalid ERE lines produce a native warning and are skipped. See the
[Darcs oracle notes](../../tests/oracles/darcs/README.md).

Sapling `.git` and `.sl` modes and Jujutsu colocated and non-colocated modes share the tested
Git-ignore dialect. Read-only ignore evaluation reuses that matcher with mode-specific source
discovery. Sapling can optionally query NUL-delimited native status for membership; Jujutsu can
read its saved working-copy tree using `jj file list --ignore-working-copy`, avoiding the
snapshotting `jj status` command. XDG Git ignores, `.git/info/exclude`, and Git config precedence
are captured on macOS 26 arm64, Debian 13 Linux aarch64/x86_64, and Windows Server 2025 x64. The
Windows profile covers Sapling 0.2.20261103 in both storage modes and Jujutsu 0.47.1 in both
workspace modes, including the shared rule-pattern and configuration probes. Other client versions
and broader platform boundaries remain open. An older Sapling 0.2.20261028/Jujutsu 0.47.1 Windows
profile also matches the checked source and configuration probes; `.sl` path-pattern probes are
explicitly excluded, so the Windows profile makes no claim about that version's `.sl` pattern
behavior. See the
[compatibility probe notes](../../tests/oracles/compat/README.md).
