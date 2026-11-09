# Breezy native oracle

`cases.json` carries cases from the implementation research handoff and follow-up probes. The runner
creates a disposable standalone tree for each case, isolates `HOME` and `XDG_CONFIG_HOME`, disables
plugins, and records both `brz ignored` rule results and short status output. Nested file probes add
a tracked anchor in the parent directory so the native command actually visits the target below it.

Run from the repository root:

```sh
python -m scripts.ci oracle-brz --output /tmp/brz-oracle.json
```

Three captured Breezy 3.3.24 profiles are committed: macOS 26 arm64 with the Homebrew client, Linux
aarch64, and Linux x86_64 under Python 3.12. Twenty-nine boolean candidates and three explicit
regex/error cases are recorded across all three profiles. The boolean cases include exception
priority, `!!` strong-exclude priority, trailing slash normalization, basename matching,
slash-rooted matching, whitespace preservation, no nested `.bzrignore` auto-discovery, global versus
branch exception priority, and built-in Python cache ignores without a user ignore file. A child
exception under an ignored directory makes both the exception path and a sibling path appear as
unknown in status, even when the exception target does not exist. Slash-containing strong patterns
match the full path: `!!cache/private` does not match a deeper file, while
`!!cache/private/**` does. `BRZ_HOME/breezy/ignore` is recognized as a global-ignore source. The
default-rule listing is captured separately in each result. Named capture groups are rewritten to
non-capturing groups with a warning; a native query confirms the normalized pattern still matches.
Anchored path regexes, negative lookahead, and scoped inline flags match and reject captured paths as
expected. Malformed RE patterns
fail `ignored` and `status` with exit code 3. The published global inline flag example
`RE:(?i)foo` also fails with exit code 3 in all three pinned profiles; preserve this observed native
behavior until a supported client version demonstrates otherwise. In both traversal orders, the
policy walker matches
captured status unknown/ignored paths when an exception opens an ignored parent and exposes its
siblings. A regex exception also opens an ignored parent in top-down and bottom-up walks: its target
appears as unknown while sibling files remain ignored. Without that exception, native status keeps
the ignored subtree hidden. The local policy is checked against all 29 boolean candidate cases on all
three profiles.
Broader regex behavior,
source precedence, and pruning safety beyond these cases remain open. Breezy's documented pattern
rule says that a
slash or regular expression is compared with the workspace-relative path, while a pattern without
a slash is compared with the final path component; the policy follows that contract.

These results establish candidate behavior for the pinned fixtures only. They do not establish all
Breezy global configuration locations, future versions, tracked-file traversal, path encodings, or
complete exception semantics. In particular, status unknown/ignored membership is recorded
separately from rule matching.

The probes are informed by Breezy's [ignore command reference](https://www.breezy-vcs.org/doc/en/user-reference/ignore-help.html),
[pattern reference](https://www.breezy-vcs.org/doc/en/user-reference/patterns-help.html), and
[working tree registration guide](https://www.breezy-vcs.org/doc/en/user-guide/controlling_registration.html).
