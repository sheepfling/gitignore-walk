# Fossil native oracle

`cases.json` starts a native Fossil corpus based on the supplied implementation research. It probes
`ignore-glob` tokenization, filename/path matching, versioned setting precedence, and whether an
ignored directory suppresses descendants in `fossil extras`.

Run from the repository root:

```sh
python -m scripts.ci oracle-fossil --output /tmp/fossil-oracle.json
```

Each case creates a disposable repository, checkout, and isolated home directory. It records the
Fossil version, platform, command result, listed paths, and candidate comparison. The captures cover
Fossil 2.28/macOS arm64 and 2.26/Linux aarch64. Ten boolean candidate cases, including hash-leading
patterns, literal backslashes, and ignored-directory descendant suppression, match both profiles.
Malformed-quote and escaped-separator probes are checked against captured native decisions on both
profiles; the full tokenizer contract remains open. A missing
Fossil executable is recorded as skipped, not passed.

The `fossil.directory-inheritance` case includes ignored descendants and visible siblings. The
policy walk's included and ignored selections are checked against the two-profile `fossil extras`
capture for that untracked fixture. The Fossil checkout marker is excluded from the walker baseline.
This does not establish tracked-file membership or general traversal conformance.
