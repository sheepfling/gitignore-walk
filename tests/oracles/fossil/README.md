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
Fossil version, platform, command result, listed paths, and candidate comparison. The 30-case
captures cover Fossil 2.28/macOS arm64, Fossil 2.26/Linux aarch64 and x86_64, and Fossil
2.23/Ubuntu 24.04 x86_64. Twenty-nine
boolean candidate cases,
including hash-leading patterns, literal backslashes, ignored-directory descendant suppression,
quoted commas, single-quoted spaces, quoted trailing spaces, literal quotes, and ASCII-only whitespace
separators. Follow-up glob probes establish range classes, Unicode `?` matching, case
sensitivity, the distinction between `!` and `^` inside character classes, and unmatched
bracket behavior.
Global fallback plus local/versioned setting precedence also match all three profiles.
Eight malformed-quote,
adjacent-token, escaped-separator, and empty-token
probes also match captured native decisions on all three profiles and are checked against the local
evaluator. Other tokenizer boundaries remain open. A missing
Fossil executable is recorded as skipped, not passed.

The `fossil.directory-inheritance` case includes ignored descendants and visible siblings. The
policy walk's included and ignored selections are checked against all three `fossil extras`
capture for that untracked fixture. The Fossil checkout marker is excluded from the walker baseline.
This does not establish tracked-file membership or general traversal conformance.
