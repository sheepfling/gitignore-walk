# Validation record

Date: 2026-11-06. Status: unreleased alpha review candidate.
Repository: <https://github.com/sheepfling/gitignore-walk> (private).
No mdrepo checkout, branch or PR was modified.

## Passed locally on Linux

- 52 isolated unittest cases on Python 3.10.22 with the minimum `pathspec==1.0.0`.
- The same 52 cases on Python 3.12.14 with `pathspec==1.1.1`.
- Git 2.52.0 is the native oracle and executable for these runs.
- Ruff 0.17.4 lint and formatting checks.
- Pyright 1.1.414 strict source checking targeting Python 3.10.
- Source distribution and universal wheel builds; Twine metadata validation.
- Installed-wheel tests outside the source tree, including `py.typed` presence.

The tests cover portable API shape, ordered batches, provenance, hard baselines, missing targets,
nested rules/negation, explicit filtering/pruning, baseline dependency compatibility, and documented
legacy walk behavior. Isolated native tests cover quoted paths, includes and conditional includes,
last-value precedence, unrelated sections, global/local/system/worktree config, environment
configuration, tilde/relative paths, XDG fallback, missing optional excludes, info/exclude, linked
worktrees and separate Git dirs, malformed config, timeouts, diagnostics, invalid bytes, NUL framing,
tracked-file rule evaluation, bounded roots and final/intermediate symlinks. The portable pattern
corpus is compared directly with Git under isolated configuration.

Independent source review identified three defects in the new native code: trimming path characters
from unusual roots, dereferencing final symlink query targets, and classifying directory symlinks as
directories for hard baseline patterns. These were fixed and given regression coverage. A malformed
mock frame was also corrected so the unexpected-echo check is genuinely exercised.

## Not yet established

- No package release or PyPI publication has occurred.
- Cross-platform GitHub CI must be checked for the exact review commit; local Linux results do not
  establish Windows/macOS results. The proposed matrix is Python 3.10–3.14 on all three platforms.
- This is not mdrepo integration testing or approval to migrate it.
- No performance benchmark, hostile concurrent-filesystem safety claim, persistent subprocess,
  parallel traversal, or atomic whole-tree snapshot is included.
- The two documented legacy portable behaviors remain compatibility limitations, not fixes.

See [migration gates](migration.md) and the [API/defaults](../README.md) before adoption.
