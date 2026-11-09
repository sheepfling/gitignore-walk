# Subversion native oracle

`cases.json` contains isolated local-repository probes. The property case compares `svn status --xml`
with `svn status --xml --no-ignore` for directory `svn:ignore`, inherited `svn:global-ignores`, a
nested ignore property, and one versioned file whose name matches an ignore pattern. A second case
checks that parent status reports a nested working-copy root but does not list files inside it. A
third case checks that parent status lists files beneath declared externals using unpinned,
operative-revision, peg-revision, parent-relative, absolute, and server-root-relative URLs. A sixth
case serves an isolated repository over loopback `svnserve` and checks a scheme-relative external
URL that inherits the working copy's scheme and authority.

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

The property fixture covers directory-local `svn:ignore`, nested and inherited
`svn:global-ignores`, a `global-ignores` pattern from the isolated runtime config, a Git-style negation
counterexample, ignored directories, and a versioned file whose name matches an ignore rule. The
sparse-depth fixtures confirm a versioned directory at depth `empty` retains its `svn:ignore`
property, while an excluded directory is reported as one unversioned path without listing files
beneath it. All five cases match on Subversion 1.15.0/macOS arm64 and 1.14.5/Linux aarch64 and
x86_64; the scheme-relative external is also captured on these profiles. Captures are stored in
`results/`.

The package's initial `SubversionIgnorePolicy` uses the native client for working-copy and
versioned-property discovery and receives the isolated runtime config directory explicitly; it then
evaluates the supported glob rules in Python. It reads the selected config file's
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
the six-case disposable status corpus with SlikSvn. The reviewed Subversion 1.14.5 Registry capture
on Windows Server 2025 x86_64 is committed as `results/svn-1.14.5-windows-registry.json`: native
status and the policy both honor the Registry-only pattern, then both honor the user INI pattern over
the Registry value. The current Windows status capture is exploratory until its client profile and
results are reviewed.
The policy does not
determine versioned membership or claim add/status command equivalence beyond these fixtures. It
keeps ignored directories traversable, stops at unrelated nested `.svn` working copies,
and follows external roots reported by native status across repository-root-relative,
parent-relative, absolute, server-root-relative, and scheme-relative URLs, with and without pinned
revisions.
Sparse `empty`-depth properties and excluded directory traversal barriers are covered. Broader
configuration precedence, additional client/platform versions, and a reusable cross-scheme oracle
contract remain open before calling this mature support.
