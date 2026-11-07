# Local and CI verification

Install development tools from the checkout:

```sh
python -m pip install -e '.[dev]'
```

## Commands

| Command | Checks |
|---|---|
| `python -m scripts.ci test` | Test the active interpreter |
| `python -m scripts.ci all` | Tests, lint, type checks, and package validation |
| `python -m scripts.ci matrix` | Test locally installed Python 3.10–3.15 interpreters |
| `python -m scripts.ci local` | Windows Python matrix and Linux Docker matrix |
| `python -m scripts.test_python_matrix` | Windows Python matrix only; accepts `--windows-versions MAJOR.MINOR ...` |
| `python -m scripts.ci quality` | Ruff lint/format and strict Pyright |
| `python -m scripts.ci package` | Build wheel/sdist, run Twine, import the installed wheel |

Narrow a matrix with `--versions`, `--windows-versions`, or `--linux-versions`. Use
`--skip-windows` or `--skip-linux` to run one platform. The Windows environments install only
pytest; Linux containers install Git so the Git differential tests run. Linux Python 3.12 also runs
quality and package checks. macOS testing runs in GitHub Actions and requires a macOS host.

## Latest local run

On 2026-11-07, `python -m scripts.ci local` passed:

- Windows CPython 3.10–3.15: 74 passed and 10 platform-specific skips per interpreter.
- Linux Docker CPython 3.10, 3.12, and 3.15: 84 passed per interpreter.
- Linux Python 3.12: Ruff lint/format, strict Pyright (0 errors), source and wheel builds, Twine,
  and installed-wheel import all passed.

The portable matcher was compared directly with Git across the tested glob, character-class,
escape, negation, nested-ignore, global-ignore, and info/exclude cases. This is broad differential
coverage, not a proof of parity for every possible Git-ignore input. Portable mode intentionally
does not read Git configuration or custom `core.excludesFile` paths; use `GitStandardPolicy` when
Git's configured behavior is required.
