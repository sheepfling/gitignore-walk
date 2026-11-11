# Fossil native oracle

`cases.json` contains a native Fossil corpus based on the supplied implementation research and
follow-up probes. It probes
`ignore-glob` tokenization, filename/path matching, versioned setting precedence, and whether an
ignored directory suppresses descendants in `fossil extras`.

Run from the repository root:

```sh
python -m scripts.ci oracle-fossil --output /tmp/fossil-oracle.json
```

Each case creates a disposable repository, checkout, and isolated home directory. It records the
Fossil version, platform, command result, listed paths, and candidate comparison. The 43-case
captures cover Fossil 2.28/macOS arm64, Fossil 2.26/Linux aarch64 and x86_64, and Fossil
2.23/Ubuntu 24.04 x86_64. Forty-one
boolean candidate cases,
including hash-leading patterns, literal backslashes, ignored-directory descendant suppression,
quoted commas, single-quoted spaces, quoted trailing spaces, literal quotes, and ASCII-only whitespace
separators. Follow-up glob probes establish range classes, Unicode `?` matching, case
sensitivity, the distinction between `!` and `^` inside character classes, unmatched brackets,
and that only ASCII whitespace separates or trims list tokens. Unicode whitespace remains pattern
data.
Global fallback plus local/versioned setting precedence also match all four profiles.
Nine malformed-quote,
adjacent-token, escaped-separator, and empty-token
probes also match captured native decisions on all four profiles and are checked against the local
evaluator. They confirm that plain text immediately after a closing quote starts a separate token
(for example, `"a"b` matches both `a` and `b`). Fifteen additional native probes cover the complete
ASCII whitespace separator set, unquoted boundary trimming, whitespace around a quoted token, and
an all-whitespace setting; these match all four profiles and the portable tokenizer. Other tokenizer
boundaries remain open. A missing Fossil executable is recorded as skipped, not passed.

The native syntax reference defines whitespace as TAB, LF, VT, FF, CR, and SPACE; the
[pinned Fossil 2.28 glob documentation](https://fossil-scm.org/home/doc/80ea65af53c5aefc/www/globs.md)
covers this tokenizer contract.

The `fossil.directory-inheritance` case includes ignored descendants and visible siblings. The
policy walk's included and ignored selections are checked against all three `fossil extras`
capture for that untracked fixture. The Fossil checkout marker is a baseline exclusion, so included
walks omit it while ignored and all-file selections may still return it. Native-backed walk tests
also open a nested checkout with `fossil open --nested` and verify that the parent `fossil extras`
and policy walk stop before its files in top-down and bottom-up traversal. This boundary is
currently verified against Fossil 2.28/macOS arm64; broader client-profile evidence remains open.
Opt-in membership discovery uses `fossil json dir --checkin current` for the target's parent and
`fossil json status` for staged or missing files. A live native test checks tracked, newly added,
untracked, and directory targets while asserting that membership does not change ignore decisions.
The test also checks native status entries for scheduled additions (`new`), missing files, edits
(`edited`), and renames (`["missing", "renamed"]`), and confirms those paths remain versioned while
an absent, unreported path stays unknown. Directory membership remains unknown. This status-shape
capture is currently exercised by the live Fossil 2.28/macOS test; broader cross-profile status and
traversal conformance remain open.
Membership-aware walking keeps ignored directories traversable because they may contain versioned
descendants. The Fossil 2.28/macOS live fixture checks that a tracked child is selected as included
while `fossil extras` omits its ignored untracked sibling, in both traversal orders.
