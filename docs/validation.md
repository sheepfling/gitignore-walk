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
- All 18 hosted CI jobs passed on resolver commit `396b2a8`, covering Python 3.10–3.15 on Ubuntu,
  macOS, and Windows, as well as package builds, Twine validation, and installed-wheel checks.
- The local `python -m build` attempt could not create an isolated build environment because this
  runner cannot resolve `pypi.org`; the hosted build jobs passed.

## Merged-main baseline

Before this branch, 58 tests passed locally and all 19 hosted CI jobs passed on the merged PR head.
That state still used a runtime ignore-pattern library; the follow-on replaces it with the bundled
resolver and adds a Git differential corpus.

## Remaining release gates

- Performance measurements on large pattern sets and realistic repositories.
- Exact parity for all Git-ignore edge cases. The matcher remains gated by the differential suite;
  unsupported differences should be documented and tested before merging.
- A package release or PyPI publication.
- mdrepo integration or approval to migrate mdrepo.

The portable policy intentionally does not parse Git configuration or honor custom
`core.excludesFile` paths. See [migration gates](migration.md) and the [API/defaults](../README.md).
