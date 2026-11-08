# Agent instructions

## Start here

- Work from the repository root. The library supports Python 3.10 and newer.
- Read [README.md](README.md) for the public behavior and [validation.md](docs/validation.md) for
  the local CI workflow.
- Before changing files, inspect `git status --short --branch` and the relevant staged and unstaged
  diffs. Preserve existing user changes; do not reset, revert, or stage unrelated work.

## Repository map

- `src/gitignore_walk/` contains the public package, portable matcher, Git-backed policy, and
  traversal implementation.
- `tests/test_policies.py` covers parser, matching, explanation, traversal, and Git behavior.
- `scripts/ci.py` coordinates local checks and is also the entry point called by hosted CI.
- `docs/validation.md` documents the pre-push command and verification scope.

## Development workflow

Create and activate a Python 3.12 virtual environment from the repository root:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
```

In Windows PowerShell, use:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Then install the development tools into that environment:

```sh
python -m pip install -e '.[dev]'
```

Before pushing, run the full local check:

```sh
python -m scripts.ci all
```

It runs pytest, Ruff lint and formatting, strict Pyright, rumdl, mdrepo on Python 3.11+, and
package validation. The runner labels each phase and stops at the first failure. To isolate a
failure, rerun `python -m scripts.ci test`, `python -m scripts.ci quality`, or
`python -m scripts.ci package`.

When editing Markdown, run the fixers before the read-only checks:

```sh
rumdl check --fix .
python -m mdrepo fix .  # Python 3.11+
python -m scripts.ci all
```

GitHub Actions calls the same runner: matrix entries run `test`, and Ubuntu Python 3.12 runs
`all`. This is the repository's hosted full-check job; do not infer hosted CI status from local
results.

## Implementation notes

- Keep text files UTF-8 with LF endings; `.editorconfig` and `.gitattributes` enforce this.
- Keep the portable Python policy and Git-native policy behavior distinct; do not add silent
  fallback between them.
- Keep the shared policy, decision, trace, and walker contracts scheme-neutral. The Git-prefixed
  decision, trace, walk-entry, and walker names are compatibility aliases.
- Treat future VCS ignore formats as separate policies and tagged config variants. Keep
  `GitIgnoreMatcher` scoped to matcher implementations for Git syntax; extend the config and
  selection unions, exhaustive resolver switch, exports, typing contract, and behavior tests as a
  unit. A fallback must not silently change ignore schemes. `IgnorePolicy` is the built-in walker
  seam, not a third-party scheme plugin API.
- Keep type annotations compatible with Python 3.10 and pass strict Pyright.
- Add or update focused tests in `tests/test_policies.py` when changing observable behavior.
- Keep user-facing guidance in README/docs. Use this file for durable repository conventions and
  agent entry points.

Claude Code imports these instructions through [CLAUDE.md](CLAUDE.md). Codex and Grok read this
`AGENTS.md` directly.
