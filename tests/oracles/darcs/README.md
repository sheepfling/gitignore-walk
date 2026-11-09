# Darcs native oracle

The oracle creates a disposable Darcs repository and isolated home directory for every case. It
uses `darcs whatsnew --look-for-adds --summary` to capture untracked add candidates and
`darcs show files --null` to distinguish managed paths from boring paths without relying on newline
as a path delimiter. It does not add files to the project repository or read the developer's Darcs
preferences.

Run from the repository root:

```sh
python -m scripts.ci oracle-darcs --output /tmp/darcs-oracle.json
```

The current corpus has seven probes across macOS arm64 Darcs 2.18.5 and Debian 13 x86_64 Darcs
2.18.4. The six closed candidates cover ERE alternation, a POSIX character class, global boring
rules, a configured boringfile, and the fact that already managed files remain managed when their
path matches a boring rule. Both profiles agree on all six. The final probe captures how an invalid
regular expression is reported.

The [Darcs configuration guide](https://darcs.net/Using/Configuration) says `boringfile` overrides
`_darcs/prefs/boring`. In both current captures, a file matching the local rules remains boring while
a file matching the configured boringfile is also boring. The observation was repeated after
recording the preference on Darcs 2.18.5. The client behavior therefore differs from its own docs;
the policy delegates this behavior to native Darcs and does not need a Python-side precedence rule.
The captured invalid pattern emits a warning and is ignored; exact comment, whitespace, encoding, and
regex error behavior still need probes.

Darcs boring rules control add-candidate discovery, not a membership-free filesystem ignore
decision: already managed files are exempt. `DarcsBoringPolicy` preserves that distinction by
combining native add-candidate and managed-path inventories; it does not evaluate ERE patterns in
Python. Candidate summaries use line delimiters, so ambiguous summaries fall back to a targeted
`darcs add --dry-run --reserved-ok` query. Native walker tests cover trailing-space and newline names
on POSIX; broader configuration, platform behavior, and other Darcs versions remain open.

| Capture file                      | Environment                   | Darcs version | Closed candidates |
| --------------------------------- | ----------------------------- | ------------- | ----------------- |
| `darcs-2.18.5-macos-arm64.json`   | macOS 26.6.2 arm64            | 2.18.5        | 6/6               |
| `darcs-debian13-x86_64.json`      | Debian 13 x86_64 in Docker    | 2.18.4        | 6/6               |

The local capture does not establish behavior on Windows, older Darcs releases, or all POSIX
regular-expression implementations.
