# Perforce native oracle

The oracle exercises `P4IGNORE` through both `p4 add -n` and `p4 ignores -i -v`, using a disposable
local `p4d`, workspace, client, depot, home directory, and ticket file for each case. The first
command checks add eligibility; the second reports the matched ignore rule, including built-in
defaults. It creates and authenticates a temporary super user and never reads the developer's P4
configuration or server state. The capture stores both command outputs and exact client and server
versions.

Run from the repository root:

```sh
python -m scripts.ci oracle-p4 --output /tmp/p4-oracle.json
```

The 37 boolean candidates, one platform-dependent case, and three add-command path-boundary cases
are captured with P4 and P4 Server 2026.1 on macOS arm64, in a Debian 13 x86_64 Docker container,
and in an Ubuntu 24.04 x86_64 container. `p4 add -n` rejects a newline-bearing filename and names
containing `#` before candidate evaluation; a separate `p4 ignores -i -v` query still reports the
escaped-leading-`#` rule match. These are native path-boundary observations, not boolean
add-eligibility comparisons.
The captures include eight checks for built-in `.p4config`, custom `P4CONFIG`, and `.p4root`
exclusions, including activation, exception precedence, descendant behavior, and filesystem case
sensitivity. They also include three
P4CONFIG probes for config-based `P4IGNORE`, config-over-environment precedence, and a nested config
selecting a different ignore source. All three profiles cover
basename wildcards matching nested files, `*` versus `**` separator behavior, directory-only
patterns, same-file negation, configured-list and default-file precedence, nested-source precedence,
explicit `P4IGNORE` list replacement, root-anchored patterns, and the fact that `.p4ignore` is not
itself implicitly ignored. All 37 boolean candidates and the platform-specific observation match
their expected results in all three profiles. A recursive `p4 add -n ...` capture also matches the
policy walk's included and ignored file sets in both top-down and bottom-up modes, including an
exception beneath an ignored directory. These results
are native evidence for these client/server profiles, not broad Perforce conformance. Lexical
probes confirm that leading and trailing ASCII spaces are trimmed, interior spaces are preserved,
and a trailing tab is significant. A leading-space comment remains a comment after trimming. The
observed precedence is: closest
directory source wins; at the same directory, the first configured file wins; within that file, the
last matching line wins. An exception can make a child addable beneath an ignored directory. The
config-backed mode is opt-in and obtains effective settings from `p4 set`; broader path edge cases
remain open. An additional `p4 -ztag info` probe confirms that client-root discovery from a nested
directory reports the configured workspace root. A separate config-scope case finds a relative
P4IGNORE file above the client root. The Linux profile uses binaries fetched from the official
Perforce 2026.1 release path and pinned by SHA-256 in CI.

| Capture file                              | Environment                   | Python  | Cases matching              |
| ----------------------------------------- | ----------------------------- | ------- | --------------------------- |
| `p4-2026.1-macos-arm64.json`              | macOS 26.6.2 arm64            | 3.12.16 | 37/37 + platform + 3 errors |
| `p4-2026.1-linux-x86_64.json`             | Debian 13 x86_64 in Docker    | 3.13.18 | 37/37 + platform + 3 errors |
| `p4-2026.1-linux-ubuntu24.04-x86_64.json` | Ubuntu 24.04 x86_64 in Docker | 3.12.3  | 37/37 + platform + 3 errors |

Perforce documents the syntax and file-list behavior in the [P4IGNORE reference](https://help.perforce.com/helix-core/server-apps/cmdref/current/Content/CmdRef/P4IGNORE.html?Highlight=workspace+root).
