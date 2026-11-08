# Local and CI verification

Repository-specific coding-agent instructions are in [AGENTS.md](../AGENTS.md); Claude Code
loads the same instructions through [CLAUDE.md](../CLAUDE.md).

## Quick start

Run these commands from the repository root. Install Python 3.12 and Git first. The virtual
environment keeps this project's tools separate from your system Python. These commands call its
Python directly, so activating it is optional.

macOS or Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m scripts.ci all
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m scripts.ci all
```

If `.venv` already exists, verify it uses Python 3.12 before reusing it. If you prefer activation, run
`source .venv/bin/activate` on macOS/Linux or `.\.venv\Scripts\Activate.ps1` in PowerShell, then
use `python -m scripts.ci all` instead of the explicit `.venv` Python path.

The development install (`.[dev]`) supplies pytest, Ruff, Pyright, rumdl, mdrepo, and package-build
tools. Git is needed for the tests that compare results against Git's own ignore matcher.

`all` is the complete local pre-push check. It runs these phases in order:

1. Tests (`pytest tests -q`), including Git comparisons when Git is installed.
2. Ruff lint (`ruff check .`) and formatting (`ruff format --check .`).
3. Strict type checking (`pyright`).
4. Markdown style (`rumdl check .`) and, when installed, repository policy
   (`python -m mdrepo check .`).
5. Package validation: build a wheel and source archive, check both with Twine, install the wheel in
   a temporary directory, and import it there.

The development extra installs mdrepo on Python 3.11 and newer. The runner uses the active Python,
stops at the first failure, and exits nonzero on failure. Each phase prints `PASSED:` or `FAILED:`
and the command it ran. Use the matching command below to rerun one phase by itself.

When editing Markdown, run the formatters before the read-only checks:

```sh
.venv/bin/rumdl check --fix .
.venv/bin/python -m mdrepo fix .
.venv/bin/python -m scripts.ci all
```

In PowerShell, use `.\.venv\Scripts\rumdl.exe check --fix .`, then
`.\.venv\Scripts\python.exe -m mdrepo fix .` and
`.\.venv\Scripts\python.exe -m scripts.ci all`.

## Commands

| Command                                | Checks                                                                                                           |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `python -m scripts.ci test`            | Test the active interpreter                                                                                      |
| `python -m scripts.ci all`             | Pre-push checks on the active interpreter: pytest, Ruff, strict Pyright, Markdown checks, and package validation |
| `python -m scripts.ci matrix`          | Test locally installed Python 3.10–3.15 interpreters                                                             |
| `python -m scripts.ci local`           | Windows Python matrix and Linux Docker matrix                                                                    |
| `python -m scripts.test_python_matrix` | Windows Python matrix only; accepts `--windows-versions MAJOR.MINOR ...`                                         |
| `python -m scripts.ci quality`         | Ruff lint/format, strict Pyright, rumdl, and mdrepo (Python 3.11+)                                               |
| `python -m scripts.ci package`         | Build wheel/sdist, run Twine, import the installed wheel                                                         |

GitHub Actions uses this same coordinator: matrix entries call `test`, and the Ubuntu Python 3.12
entry calls `all`. Thus the hosted full check and the local pre-push check use the same ordered
steps; the other matrix entries add platform and interpreter test coverage.

The commands in the table assume the virtual environment is active. If it is not, replace `python`
with `.venv/bin/python` on macOS/Linux or `.\.venv\Scripts\python.exe` in PowerShell.

Narrow a matrix with `--versions`, `--windows-versions`, or `--linux-versions`. Use
`--skip-windows` or `--skip-linux` to run one platform. The Windows environments install only
pytest; Linux containers install Git so the Git differential tests run. Linux Python 3.12 also runs
quality and package checks. macOS testing runs in GitHub Actions and requires a macOS host.

## Previously recorded local run

The 2026-11-07 run below predates the rumdl and mdrepo checks added to the shared quality phase:

- Windows CPython 3.10–3.15: 74 passed and 10 platform-specific skips per interpreter.
- Linux Docker CPython 3.10, 3.12, and 3.15: 84 passed per interpreter.
- Linux Python 3.12: Ruff lint/format, strict Pyright (0 errors), source and wheel builds, Twine,
  and installed-wheel import all passed.

The portable matcher was compared directly with Git across the tested glob, character-class,
escape, negation, nested-ignore, global-ignore, and info/exclude cases. This is broad differential
coverage, not a proof of parity for every possible Git-ignore input. Portable mode intentionally
does not read Git configuration or custom `core.excludesFile` paths; use `GitStandardPolicy` when
Git's configured behavior is required.
