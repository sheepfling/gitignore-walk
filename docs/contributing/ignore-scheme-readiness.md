# Preparing another ignore scheme

This project currently supports Git ignore rules only. This note records the extension boundary and
the evidence needed before adding another VCS format. It does not claim compatibility with another
VCS and does not add a runtime plugin API.

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

The November 7, 2026 research checkpoint exercised seven native Git probes on Git 2.47.3/Linux. It
confirmed parent blocking versus contents-only exceptions, recursive `**/` behavior, last-match
precedence, and the difference between ordinary tracked-file handling and `--no-index` ignore-rule
matching. These probe results describe Git itself; they are not tests of this library. No non-Git VCS
client was exercised, so future support still needs native conformance evidence.
