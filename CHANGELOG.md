# Changelog

Notable user-facing changes are recorded here.

## Unreleased

### Added

- Scheme-neutral policy and traversal contracts with typed, explicit selection for Git, Mercurial,
  Subversion, Perforce, Fossil, Breezy, and Darcs.
- Initial portable Mercurial `.hgignore` evaluation for regexp, glob, rootglob, `include`, and
  `subinclude`, with optional read-only discovery of configured `ui.ignore` files through `hg`.
- Initial scheme-specific policies for Subversion properties, Perforce `P4IGNORE`, Fossil ignore
  globs, Breezy ignore rules, and Darcs boring-file candidates.
- Native-oracle fixtures and profile-specific result captures for matching, discovery, and walking.

### Selection and compatibility

- VCS selection is explicit. The default `select_policy(root)` remains portable Git; selecting
  Mercurial or another built-in scheme requires its tagged config. Ignore rules never fall back
  across VCS grammars. The existing opt-in `PreferGitPolicyConfig` remains the only cross-backend
  fallback and only falls back when the Git executable is confirmed missing.
- Mercurial matching remains local and portable. Reading Mercurial's configured `ui.ignore` list is
  opt-in and requires the `hg` executable. Ignore decisions describe rule matches, not tracked or
  versioned membership.
- Mercurial native captures cover 7.2.4 on macOS arm64, 7.0.1 on Linux aarch64 and x86_64, and
  7.1.2 on Windows Server 2025 x86_64. The Windows profile has five explicit path skips and one
  symlink-dependent walk skip. Include cycles remain a bounded safe divergence; a native
  `debugignore` subinclude query also exits with a trace-formatting error after reporting a match.
  See the [Mercurial oracle notes](tests/oracles/hg/README.md) for the case-level captures.
- All additional VCS policies are initial implementations. Their tested profiles, native skips,
  unsupported behavior, and known divergences are documented in the [VCS expansion backlog](docs/contributing/vcs-expansion-backlog.md)
  and the corresponding [native oracle notes](tests/oracles/).

### Validation

- The local pre-push workflow is `python -m scripts.ci all`; see [validation instructions](docs/validation.md).
- Hosted CI uses the same coordinator and adds Python/platform test jobs plus native-client oracle
  captures where those clients are available.
