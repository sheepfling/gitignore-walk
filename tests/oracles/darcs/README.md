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

The current corpus has nineteen probes across macOS arm64 Darcs 2.18.5, Debian 13 x86_64, and Debian
13 arm64 with Darcs 2.18.4 on both Linux profiles. Eighteen closed candidates cover ERE alternation,
a POSIX character class, global boring rules, a configured boringfile, managed-file behavior, and
lexical rules, a nested-repository walking case, and overlap between local, global, and configured
boring sources. All three profiles agree on all eighteen.
Native probes confirm a `#` comment only at
the start of a rule, leading/trailing spaces
and tabs remain part of the regex, and `#` inside a rule is data. UTF-8 literal regexes match NFC
names, distinguish NFD spellings, and keep `[[:alpha:]]` ASCII-only under both `LC_ALL=C` and
`LC_ALL=C.UTF-8`. Linux CI captures both architectures under Debian 13, using QEMU for the ARM64
client on its x86_64 runner. The final
probe captures how an invalid regular expression is reported.

The [Darcs configuration guide](https://darcs.net/Using/Configuration) says `boringfile` overrides
`_darcs/prefs/boring`. In both current captures, a file matching the local rules remains boring while
a file matching the configured boringfile is also boring. The observation was repeated after
recording the preference on Darcs 2.18.5. The client behavior therefore differs from its own docs;
the policy delegates this behavior to native Darcs and does not need a Python-side precedence rule.
New overlapping-source probes also show that the global `~/.darcs/boring` remains active alongside
non-matching local rules and a configured `boringfile`, on all three profiles.
The captured invalid pattern emits a warning and is ignored. Other regex error messages, locales,
and native pattern/path encodings remain untested.

Darcs boring rules control add-candidate discovery, not a membership-free filesystem ignore
decision: already managed files are exempt. `DarcsBoringPolicy` preserves that distinction by
combining native add-candidate and managed-path inventories; it does not evaluate ERE patterns in
Python. Candidate summaries use line delimiters, so ambiguous summaries fall back to a targeted
`darcs add --dry-run --reserved-ok` query. Native walker tests cover included-only, ignored-only,
and all-file selections in both traversal orders, plus trailing-space and newline names on POSIX;
broader configuration, platform behavior, and other Darcs versions remain open.

The nested-repository probe records an important boundary behavior: outer `darcs whatsnew` still
lists a file inside a nested Darcs repository as an outer add candidate. The walker follows that
directory while excluding the nested `_darcs` metadata. This behavior matches all three captured
profiles and both traversal orders.

| Capture file                      | Environment                   | Darcs version | Closed candidates |
| --------------------------------- | ----------------------------- | ------------- | ----------------- |
| `darcs-2.18.5-macos-arm64.json`   | macOS 26.6.2 arm64            | 2.18.5        | 18/18             |
| `darcs-debian13-x86_64.json`      | Debian 13 x86_64 in Docker    | 2.18.4        | 18/18             |
| `darcs-debian13-arm64.json`       | Debian 13 arm64 in Docker     | 2.18.4        | 18/18             |

The current profile set does not establish behavior on Windows or older Darcs releases. The
[official download page](https://darcs.net/Binaries) lists Darcs 2.16.3 as its Windows binary while
the [project home page](https://darcs.net/) identifies 2.18.5 as the current stable release; the
[team page](https://darcs.net/DarcsTeam) lists the Windows packager role as unfilled. Do not treat
the 2.16.3 binary as current-release conformance. Other POSIX regular-expression implementations
also remain untested.
