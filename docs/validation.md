# Validation record

Date: 2026-11-07. Status: dependency-removal follow-on in progress.
Repository: <https://github.com/sheepfling/gitignore-walk> (private).
This work branches from the merged `main`; mdrepo remains untouched.

## Current resolver follow-on

- 60 tests passed on CPython 3.15.2 on Windows. Eight cases were skipped because symlink creation
  requires unavailable privileges and Windows disallows trailing CR/LF directory names.
- Ruff lint, Ruff format, and strict Pyright passed.
- The portable parser and matcher were compared directly with Git for anchored and unanchored
  rules, negation, directory-only rules, recursive `**`, escaping, and character classes.
- `python -m build` could not create an isolated build environment because this runner cannot
  resolve `pypi.org`. Hosted CI must verify package builds and the full OS/Python matrix.

## Merged-main baseline

Before this branch, 58 tests passed locally and all 19 hosted CI jobs passed on the merged PR head.
That state still used a runtime ignore-pattern library; the follow-on replaces it with the bundled
resolver and adds a Git differential corpus.

## Not yet established for this branch

- Hosted CI on the new branch, including Linux/macOS symlink cases and all Python 3.10–3.15 jobs.
- Fresh sdist/wheel builds, Twine validation, and installed-wheel tests after removing the runtime
  dependency.
- Performance measurements on large pattern sets and realistic repositories.
- Exact parity for all Git-ignore edge cases. The matcher remains gated by the differential suite;
  unsupported differences should be documented and tested before merging.
- mdrepo integration or approval to migrate mdrepo.

The portable policy intentionally does not parse Git configuration or honor custom
`core.excludesFile` paths. See [migration gates](migration.md) and the [API/defaults](../README.md).
