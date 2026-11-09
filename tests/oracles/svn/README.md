# Subversion native oracle

`cases.json` contains 20 isolated local-repository probes. They cover directory `svn:ignore`,
inherited `svn:global-ignores` (including a property above a subtree checkout), nested properties,
APR glob syntax, sparse depths, and working-copy boundaries. External fixtures exercise
repository-root-relative, parent-relative, absolute, server-root-relative, and scheme-relative URLs.
One external fixture gives the external repository its own `svn:global-ignores` property, declares a
second external inside it, and checks that rules stay within each external working-copy boundary.
The collapsed-unversioned-directory case records that native status reports an unversioned
directory as one entry rather than listing its files. A rule-only decision for a known child can
still match an ignore pattern, but the child's native membership remains unknown.
The ignored-directory fixture records that default status omits an ignored unversioned directory,
while `--no-ignore` lists it once and still omits its descendants. The policy evaluates descendants
against the inherited rule, leaves their native membership unknown, and the walker continues through
the directory.
The APR default-flags fixture verifies that `*.tmp` matches `hidden/.hidden.tmp` and that
`case.tmp` matches `lower/case.tmp` but not `upper/CASE.TMP`. Separate directories keep this
case-sensitivity check valid on case-insensitive filesystems.

Run the capture from the repository root:

```sh
python -m scripts.ci oracle-svn --output /tmp/svn-oracle.json
```

The command also writes `/tmp/svn-oracle.transitions.json`, a separate disposable-working-copy
capture for native membership transitions. The `scripts.ci native --backends svn` command checks
both outputs and retains them as CI artifacts.

The runner creates a temporary repository and working copy, writes an isolated Subversion config,
and records both native status listings, the client versions, commands, and exit codes. The
scheme-relative URL case starts `svnserve` on loopback with anonymous access limited to that
temporary repository and shuts it down after capture. The runner does not access a user's existing
working copy or Subversion configuration. GitHub Actions runs the same coordinator and uploads its
output as an artifact.

The property fixtures cover local, inherited, nested, and external-working-copy properties; runtime
configuration; Git-style negation; ignored directories; and versioned files whose names match ignore
rules. A file external appears in native status as a normal versioned file with `file-external="true"`;
even when `svn:ignore` matches its name, it is not reported as ignored. The policy reports rule matches
separately from versioned membership. Set `membership_aware=True` on `SubversionPolicyConfig` to
query `svn status --xml --verbose --no-ignore --depth infinity`; known versioned and unversioned
entries populate `IgnoreDecision.membership`, and the walker selects known versioned entries as
included even when their rules match. Membership remains `None` for paths omitted by native status,
including paths beneath some sparse working-copy depths. The default stays rule-only and does not
run this extra status query. Sparse-depth fixtures confirm a versioned directory at depth
`empty` retains its `svn:ignore` property, while an excluded directory is reported as one unversioned
path without listing files beneath it. A switched-subtree case confirms that inherited
`svn:global-ignores` are discovered at the switched root and do not leak to sibling paths. The
original 19-case corpus is captured on Subversion 1.15.0/macOS arm64, 1.14.3/Ubuntu 24.04 x86_64, and
1.14.5/SlikSvn Windows Server 2025 x86_64; the ignored-directory case is currently captured on macOS
while matching Ubuntu and Windows captures are pending. Platform-constrained cases are recorded as
skips. The APR build lines are retained for these profiles: 1.7.6, 1.7.2, and 1.7.5, respectively. The
16 earlier cases also match on Subversion 1.14.5/Linux aarch64 and x86_64. The
file-external case is captured on macOS, both Linux architectures, and Windows Server
2025 x86_64. The Windows oracle job explicitly skips the
newline-and-tab case because those filenames are not representable there. The focused runtime
Subversion suite, including the opt-in file-external membership and walker assertions, passes with
107 passed and 4 skipped on macOS arm64,
Linux x86_64, and Linux aarch64. The SlikSvn Windows CI job also passes these live membership
assertions. The SlikSvn Windows suite passed with 99 passed and 12 skipped in the latest hosted run;
the Windows file-external result is in `results/svn-1.14.5-windows-x86_64.json`.
Captures are stored in `results/`.

A live membership transition test creates and mutates a disposable working copy, then compares the
policy with `svn status --xml --verbose --no-ignore --depth infinity`. It covers `normal`, `modified`,
`added`, `deleted`, `missing`, `replaced`, `obstructed`, and `conflicted` entries alongside an ignored
unversioned entry. The conflict is produced by overlapping edits in two disposable working copies,
then a native update. The test also checks that ignored versioned files remain in the walker's
`included` selection, while the ignored unversioned file appears in its `ignored` selection. The
obstructed directory case confirms that the walker traverses the directory and reports its ignored
child. This exercises the tested status values without claiming that every Subversion working-copy
status is covered. A separate excluded-depth check confirms that a child omitted from verbose native
status remains membership-unknown, that discovery remains incomplete, and that the walker does not
descend into the excluded subtree. The directory-external membership check confirms the containing
working copy reports the external root as `external`; the policy treats that root as versioned and
reads descendant status from the external working copy itself.
This live transition test passed locally with Subversion 1.15.0 and runs in the hosted Ubuntu
Subversion 1.14.3 and Windows SlikSvn 1.14.5 integration jobs. The native status sequence is also
stored in `results/svn-status-transitions-1.15.0-macos-arm64.json`; each native CI run writes its
own transition capture alongside the standard Subversion oracle artifact.

The package's initial `SubversionIgnorePolicy` uses the native client for working-copy and
versioned-property discovery and receives the isolated runtime config directory explicitly; it then
evaluates the supported glob rules in Python. Its matcher follows captured SVN/APR behavior for
backslash quoting, both `!` and `^` character-class negation markers, malformed opening brackets,
and unsupported POSIX character classes. Native cases also confirm that spaces in `svn:ignore` and
`svn:global-ignores` property values are not list separators; each CR/LF-delimited line remains one
pattern. These cases are captured on Subversion 1.15.0/macOS arm64 and 1.14.5/Linux x86_64. The
Windows SlikSvn 1.14.5 profile skips the escaped-wildcard filename, which Windows cannot represent,
and the scheme-relative external because the installer does not include `svnserve`. A separate
newline-and-tab path case confirms that XML status encodes both characters as numeric references and
that the policy walk preserves the decoded names; it matches on Subversion 1.15.0/macOS arm64 and
1.14.5/Linux aarch64 and x86_64. Windows skips these unrepresentable filenames. In Subversion 1.14.5,
[`status.c`](https://github.com/apache/subversion/blob/1.14.5/subversion/libsvn_wc/status.c)
collects working-copy ignore patterns, and
[`util.c`](https://github.com/apache/subversion/blob/1.14.5/subversion/libsvn_wc/util.c) delegates
their matching to the Subversion glob helper. The committed native captures remain the behavior
evidence. In both source tags, `svn_cstring_match_glob_list` calls `apr_fnmatch` with flags `0`
([1.14.5](https://github.com/apache/subversion/blob/1.14.5/subversion/libsvn_subr/string.c#L3586-L3601),
[1.15.0](https://github.com/apache/subversion/blob/1.15.0/subversion/libsvn_subr/string.c#L3586-L3601)).
Status passes the basename to that helper, so `APR_FNM_PATHNAME` is irrelevant to status ignore
matching ([`status.c`](https://github.com/apache/subversion/blob/1.14.5/subversion/libsvn_wc/status.c#L3727-L3756)).
The macOS 1.15.0 native case confirms leading-period wildcard matching and case sensitivity with
APR 1.7.6; the capture records this under `client.svn.apr_build`. Equivalent cases have not yet
been captured on the other platform profiles. The
policy reads the selected config file's
`[miscellany] global-ignores`, uses the built-in defaults when that setting is absent, and honors an
explicit empty value. A live native comparison covers those built-in defaults on the installed
client. The default list follows Apache Subversion's
[`SVN_CONFIG_DEFAULT_GLOBAL_IGNORES`](https://svn.apache.org/repos/asf/subversion/site/staging/docs/api/1.15/svn__config_8h_source.html)
for the tested 1.15 client profile. Without an explicit config directory, it reads standard
system and per-user INI files; a live comparison verifies per-user settings against native status.
The policy reads machine and user Windows Registry values during ambient discovery. The opt-in
`windows_registry.py` probe sets and restores the current user's `global-ignores` value on an
ephemeral Windows runner, compares registry-only behavior with native status, then checks that the
user INI file overrides the Registry value. Run it only with `--allow-registry-mutation`; it is
wired into the Windows CI job. That job also runs the full Subversion integration suite and captures
the disposable status corpus with SlikSvn. The reviewed Subversion 1.14.5 SlikSvn capture on Windows
Server 2025 x86_64 is committed as `results/svn-1.14.5-windows-x86_64.json`; unsupported filename
and server cases are explicitly skipped. The separate Registry capture is committed as
`results/svn-1.14.5-windows-registry.json`: native status and the policy both honor the Registry-only
pattern, then both honor the user INI pattern over the Registry value.
Membership-aware decisions use native status item values for listed entries and leave unlisted paths
unknown; they do not claim add/status command equivalence beyond these fixtures. The default policy
does not query membership. It keeps ignored directories traversable, stops at unrelated nested
`.svn` working copies, and follows external roots reported by native status across repository-root-relative,
parent-relative, absolute, server-root-relative, and scheme-relative URLs, with and without pinned
revisions. Each listed external working copy supplies its own versioned property snapshot, including
nested externals reported by recursive native status. Versioned rules stop at each external boundary;
runtime global patterns remain active throughout.
Sparse `empty`-depth properties and excluded directory traversal barriers are covered. Additional
configuration precedence profiles, client/platform versions, and a reusable cross-scheme oracle
contract remain open before calling this mature support.

The ambient configuration precedence probe runs in a disposable Debian 13 x86_64 Docker container.
It gives `/etc/subversion/config` a system-only pattern and the isolated user's
`~/.subversion/config` a different pattern. Native status and the policy both select only the user
pattern, confirming that the user value replaces the system value for this captured Subversion
1.14.5 profile. Run `python -m scripts.ci oracle-svn-config`; its normalized capture is
`results/svn-config-precedence-debian-13-x86_64.json`. The temporary `/etc` file lives only inside
the container, so the host's Subversion files are not modified.
