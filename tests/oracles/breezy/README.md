# Breezy native oracle

`cases.json` carries cases from the implementation research handoff and follow-up probes. The runner
creates a disposable standalone tree for each case, isolates user configuration, disables plugins,
and records both `brz ignored` rule results and short status output. POSIX captures use a temporary
`XDG_CONFIG_HOME`; Windows captures use a temporary `BRZ_HOME`. Nested file probes add a tracked
anchor in the parent directory so the native command actually visits the target below it. On
Windows, the anchor is seeded with Breezy's working-tree API because `brz add` misresolves nested
paths; rule and status observations still come from the native CLI.

Run from the repository root:

```sh
python -m scripts.ci oracle-brz --output /tmp/brz-oracle.json
```

Four captured Breezy 3.3.24 profiles are committed: macOS 26 arm64 with the Homebrew client, Linux
aarch64, Linux x86_64, and Windows Server 2025 x86_64 under Python 3.12. The original twenty-nine
boolean candidates match on all four profiles, and three explicit regex/error cases are recorded
across the profiles. Four additional regex cases now have native captures on macOS arm64 and Linux
aarch64; hosted Linux x86_64 and Windows captures are pending. The boolean cases include exception
priority, `!!` strong-exclude priority, trailing slash
normalization, basename matching,
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
`RE:(?i)foo` also fails with exit code 3 in all four pinned profiles; preserve this observed native
behavior until a supported client version demonstrates otherwise. In both traversal orders, the
policy walker matches
captured status unknown/ignored paths when an exception opens an ignored parent and exposes its
siblings. A regex exception also opens an ignored parent in top-down and bottom-up walks: its target
appears as unknown while sibling files remain ignored. Without that exception, native status keeps
the ignored subtree hidden. The local policy is checked against all 29 boolean candidate cases on all
four profiles.
Broader regex behavior,
source precedence, and pruning safety beyond these cases remain open. Breezy's documented pattern
rule says that a
slash or regular expression is compared with the workspace-relative path, while a pattern without
a slash is compared with the final path component; the policy follows that contract.
The new probes establish whole-path regex matching rather than substring search, `!!RE` priority over
an `!RE` exception, and the pinned 3.3.24 normalization quirk that changes backslashes in `!!RE`
patterns to path separators. The portable policy mirrors these observed decisions.

The Windows capture sets a temporary `BRZ_HOME` to isolate each case. Breezy resolves its default
Windows application-data directory through the Windows shell-folder API, so changing only the
`APPDATA` process variable does not redirect the native client. The Windows-only policy test checks
the `%APPDATA%/Breezy/ignore` path selected by Breezy 3.3.24's native resolver; older published
documentation describes a `Breezy/3.0/ignore` path. A captured Windows Server 2025 probe confirms
the native resolver path, shell-folder agreement, and marker match in both `brz ignored` and the
policy; see `results/brz-3.3.24-windows-default-config.json`. The Windows CI job runs
`windows_default_config.py`, which resolves the real roaming folder through Shell32, temporarily
writes a marker rule at the path returned by `breezy.bedding.user_ignore_config_path()`, checks native
`brz ignored` against the policy, and restores the previous file bytes. Its artifact reports whether
the process `APPDATA` agrees with the shell folder and preserves normalized command output. The probe
requires the explicit
`--allow-user-config-mutation` flag and is only for the disposable Windows CI account; the default
`oracle-brz` command remains isolated from the user's config. These results establish candidate
behavior for Breezy 3.3.24 on the captured Windows runner only; they do not establish future versions,
tracked-file traversal, path
encodings, or complete exception semantics. In particular, status unknown/ignored membership is
recorded separately from rule matching.

The probes are informed by Breezy's [ignore command reference](https://www.breezy-vcs.org/doc/en/user-reference/ignore-help.html),
[pattern reference](https://www.breezy-vcs.org/doc/en/user-reference/patterns-help.html), and
[working tree registration guide](https://www.breezy-vcs.org/doc/en/user-guide/controlling_registration.html).
