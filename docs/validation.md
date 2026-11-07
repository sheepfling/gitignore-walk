# Local and CI verification

Repository-specific coding-agent instructions are in [AGENTS.md](../AGENTS.md); Claude Code
loads the same instructions through [CLAUDE.md](../CLAUDE.md).

Create and activate a Python 3.12 virtual environment from the repository root:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
```

In Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
```

Install development tools into the activated environment:

```sh
python -m pip install -e '.[dev]'
```

Before pushing, run the complete local check from the repository root:

```sh
python -m scripts.ci all
```

This runs, in order, `pytest tests -q`, `ruff check .`, `ruff format --check .`, `pyright`,
`rumdl check .`, then `python -m mdrepo check .` on Python 3.11 or newer. Package validation then
builds a wheel and source archive, checks both with Twine, installs the wheel into a temporary
directory, and imports it there. Each step uses the active Python interpreter, and the command
stops at the first failure. The test suite includes portable matcher tests and Git differential
tests when Git is available.

Each phase prints a named `PASSED` or `FAILED` result and the command it ran. The run stops at the
first failure. To narrow a failure, rerun its phase alone with `python -m scripts.ci test`,
`python -m scripts.ci quality`, or `python -m scripts.ci package`.

When editing Markdown, apply safe fixes before the read-only check:

```sh
rumdl check --fix .
python -m mdrepo fix .  # Python 3.11+
python -m scripts.ci all
```

## Commands

| Command                                | Checks                                                                                                           |
|----------------------------------------|------------------------------------------------------------------------------------------------------------------|
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
