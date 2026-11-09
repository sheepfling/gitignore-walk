# Subversion native oracle

`cases.json` contains 16 isolated local-repository probes. They cover directory `svn:ignore`,
inherited `svn:global-ignores` (including a property above a subtree checkout), nested properties,
APR glob syntax, sparse depths, and working-copy boundaries. External fixtures exercise
repository-root-relative, parent-relative, absolute, server-root-relative, and scheme-relative URLs.
One external fixture gives the external repository its own `svn:global-ignores` property, declares a
second external inside it, and checks that rules stay within each external working-copy boundary.

Run the capture from the repository root:

```sh
python -m scripts.ci oracle-svn --output /tmp/svn-oracle.json
```

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
path without listing files beneath it. All 16 cases match on Subversion 1.15.0/macOS arm64 and
1.14.5/Linux aarch64 and x86_64. The file-external case is captured on macOS and both Linux
architectures. The Windows oracle job explicitly skips the newline-and-tab case because those
filenames are not representable there. The focused runtime Subversion suite, including the opt-in
file-external membership and walker assertions, passes with 107 passed and 4 skipped on macOS arm64,
Linux x86_64, and Linux aarch64. Windows runtime membership remains for hosted CI to confirm.
Captures are stored in `results/`.

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
evidence. The policy reads the selected config file's
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
Sparse `empty`-depth properties and excluded directory traversal barriers are covered. Broader
configuration precedence, additional client/platform versions, and a reusable cross-scheme oracle
contract remain open before calling this mature support.
