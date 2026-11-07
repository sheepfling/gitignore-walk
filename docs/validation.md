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
- All 18 hosted CI jobs passed on resolver commit `396b2a8`, covering Python 3.10-3.15 on Ubuntu,
  macOS, and Windows, as well as package builds, Twine validation, and installed-wheel checks.
- An earlier isolated local build could not create its build environment because this runner
  could not resolve `pypi.org`; a later no-isolation build passed with the development build tools
  installed.

## Repeatable CI runner

`scripts/ci.py` is the shared verification entry point for local runs and GitHub Actions:

- `python scripts/ci.py test --backend vanilla` runs tests on the active interpreter.
- `python scripts/ci.py matrix --backend vanilla` runs tests on every locally installed supported
  interpreter. Use `--versions 3.10 3.12 3.15` to choose a smaller local matrix.
- `python scripts/ci.py test --backend pathspec|re2|hyperscan` requires the named optional engine
  before pytest starts, preventing an absent engine from silently skipping its parity check.
- `python scripts/ci.py quality` runs Ruff and strict Pyright.
- `python scripts/ci.py package` builds both distributions, runs Twine checks, and imports the
  wheel from an isolated target directory.
- `python scripts/ci.py all` runs tests, quality checks, and package verification for one
  interpreter.

The PowerShell matrix helper delegates to the Python runner. The GitHub workflow uses its `test`,
`quality`, and `package` commands, so local and hosted verification execute the same checks.

### Latest local verification

- The local Windows matrix passed on CPython 3.10-3.14 with 69 tests passing and 9 skipped on each;
  CPython 3.15 passed 70 tests with 9 skipped.
- PathSpec `simple` and `best` parity checks ran across all six Python versions. Hyperscan parity
  passed on CPython 3.15 (70 passed, 9 skipped).
- Ruff lint/format, strict Pyright, wheel and source builds, Twine validation, and isolated wheel
  import passed on Windows with CPython 3.15.
- RE2 remains unverified locally because package installation cannot reach PyPI from this runner.
- The current workflow defines Linux, Windows, and macOS coverage, but the updated remote matrix
  needs a successful run before its cross-platform result can be claimed.

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
