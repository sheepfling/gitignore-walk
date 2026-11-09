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

`all` is the core check on the active interpreter. It runs these phases in order:

1. Tests (`pytest tests -q`), including Git comparisons when Git is installed.
2. Ruff lint (`ruff check .`) and formatting (`ruff format --check .`).
3. Strict type checking (`pyright`).
4. Markdown style (`rumdl check .`) and, when installed, repository policy
   (`python -m mdrepo check .`).
5. Package validation: build a wheel and source archive, check both with Twine, install the wheel in
   a temporary directory, and import it there.

Each test invocation owns a unique temporary directory, so simultaneous local runs cannot erase
one another's fixtures. Successful runs clean that directory up on a best-effort basis; failed runs
retain it for diagnosis at the path printed in the pytest command.

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

`python -m scripts.ci pre-push` is the full host/backend gate; `python -m scripts.ci native`
runs only the native captures. Both accept `--backends` and `--output-dir`, as explained below.

| Command                                | Checks                                                                                                       |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `python -m scripts.ci test`            | Test the active interpreter                                                                                  |
| `python -m scripts.ci all`             | Core checks on the active interpreter: pytest, Ruff, strict Pyright, Markdown checks, and package validation |
| `python -m scripts.ci matrix`          | Test locally installed Python 3.10–3.15 interpreters                                                         |
| `python -m scripts.ci local`           | Windows Python matrix and Linux Docker matrix                                                                |
| `python -m scripts.test_python_matrix` | Windows Python matrix only; accepts `--windows-versions MAJOR.MINOR ...`                                     |
| `python -m scripts.ci quality`         | Ruff lint/format, strict Pyright, rumdl, and mdrepo (Python 3.11+)                                           |
| `python -m scripts.ci package`         | Build wheel/sdist, run Twine, import the installed wheel                                                     |
| `python -m scripts.ci oracle-hg`       | Capture Mercurial behavior in fresh disposable repositories; requires `hg`                                   |
| `python -m scripts.ci oracle-svn`      | Capture Subversion ignore status in a disposable local repository; requires `svn` and `svnadmin`             |
| `python -m scripts.ci oracle-fossil`   | Capture Fossil ignore-glob and extras behavior in a disposable checkout; requires `fossil`                   |
| `python -m scripts.ci oracle-brz`      | Capture Breezy ignore and status behavior in isolated disposable working trees; requires `brz`               |
| `python -m scripts.ci oracle-darcs`    | Capture Darcs boring-file behavior; requires `darcs`                                                         |
| `python -m scripts.ci oracle-p4`       | Capture `P4IGNORE` behavior using a disposable local server and workspace; requires `p4` and `p4d`           |

## Full local pre-push gate

After installing the development extra, put Git and the native clients on `PATH`: `hg`, `svn`,
`svnadmin`, `fossil`, `brz`, `darcs`, `p4`, and `p4d`. `svnserve` is optional; without it, only
protocol-based Subversion fixtures are recorded as explicit skips. Use the platform's trusted
installers; the local runner does not download clients or alter the machine's configuration. Then
run:

```sh
python -m scripts.ci pre-push
```

This runs the core `all` phases and then all six native backend captures. Missing selected required
clients fail before tests start, rather than producing an apparently successful skipped oracle.
Subversion fixtures that specifically need `svnserve` are reported as case-level skips when it is
unavailable. A nonzero
capture command, missing or invalid output, failed capture, or closed candidate mismatch fails the
native gate. Every selected backend is attempted even if an earlier backend fails. These are native
observations plus the policy regression suite, not certification of every client version or mode.

Each invocation writes fresh captures and `summary.json` below `.local/ci/native-*`, including client
versions, platform, mismatches, and explicit skips. Fresh directories prevent stale output from
hiding a failed run. Platform-specific case skips and the optional Mercurial ownership/trust probe
are reported as `passed_with_skips`, never as fully executed coverage. The trust probe is omitted
by default locally because it changes disposable-file ownership and requires noninteractive
privileges. On an isolated runner, opt in with `--include-trust`; hosted Linux always does so.
Ordinary local pre-push never launches the trust probe or asks for sudo. The Windows Registry/INI
probe likewise stays on an ephemeral hosted Windows runner: local pre-push does not mutate the
user's registry.

For a deliberately narrower check, select backends and a report directory explicitly:

```sh
python -m scripts.ci pre-push --backends hg svn brz
python -m scripts.ci native --backends hg svn brz --output-dir .local/ci
```

The first is a partial backend gate, not full backend coverage. `native` runs captures only; it does
not replace tests, lint, typing, or packaging. `all` remains useful for quick iteration when native
clients are unavailable, but is not the full pre-push gate. Sapling/Jujutsu probes remain research
commands, outside both the local and hosted acceptance matrix.

The commands assume the virtual environment is active. Otherwise replace `python` with
`.venv/bin/python` on macOS/Linux or `.\.venv\Scripts\python.exe` in PowerShell.

## Interpreter and platform coverage

Before publishing a substantial change, also run the available local Python matrix:

```sh
python -m scripts.ci matrix --versions 3.10 3.11 3.12 3.13 3.14 3.15
```

Each interpreter needs pytest. Missing interpreters fail the command; they are not silently counted
as coverage. This tests the host platform only. The `local` command can provision a Windows Python
matrix on Windows and a Linux Docker matrix on either host. Use `--skip-windows` or `--skip-linux`
and the corresponding version options to narrow those runs explicitly. Linux containers install
Git, Mercurial, and Subversion for native-backed tests; Python 3.12 also runs quality and package
checks. Those containers do not yet run the full six-backend oracle gate. A macOS result is not
Windows or Linux evidence, and Docker is not a substitute for native Windows or macOS execution.

## What stays on GitHub Actions

Hosted CI checks clean environments and differences that a developer's machine cannot establish:

- Five unchanged core lanes: Linux Python 3.10, 3.12, and 3.15; Windows and macOS Python 3.12.
  Linux Python 3.12 runs `all`; the other lanes run tests with only pytest installed.
- One Linux native lane runs the native-backed policy suite and checks Mercurial
  matching/walking/trust, Subversion, Fossil, Breezy, and Perforce. Darcs runs in a Debian 13
  container because Ubuntu 24.04 no longer packages the required executable.
- One Windows native lane installs clients once, runs Mercurial/Subversion/Breezy policy tests,
  checks those three captures, and retains the explicit Registry/INI precedence probe. Protocol
  based Subversion cases are explicit skips when the SlikSVN installer does not provide `svnserve`.

This keeps every previous OS/Python and backend/platform pairing in seven jobs instead of fourteen.
The two native jobs share installation work, keep running remaining checks after test failures,
and upload captures and summaries even on failure. Perforce's Linux binaries remain pinned to
2026.1 with SHA-256 verification, and Breezy remains pinned to 3.3.24. Artifacts expire after seven
days; import reviewed conformance evidence into version control when it needs a longer lifetime.

Automatic runs happen for pull requests and pushes to `main`. Branch-only iteration is local;
use **Run workflow** for a branch before opening a PR when hosted evidence is needed. There is no
second branch-push run alongside a PR run, and newer runs cancel superseded work for that event
and ref. A typical open-PR push therefore starts seven jobs rather than two sets of fourteen:
75% fewer job starts, not a measured 75% reduction in runtime or charges. With no open PR, feature
branch pushes start no jobs automatically. Consolidating native work may lengthen elapsed time and
makes a full native job the retry unit; backend names remain visible in logs and summaries.

Before adopting the workflow, check repository rulesets or branch protection for old native-job
names. Replace any required old native contexts with `native-linux` and `native-windows` through
an explicitly authorized settings change. Core matrix check names are unchanged. No settings
change is made by the workflow itself. Only a hosted run against the exact updated revision can
verify the new workflow on GitHub.

Standard GitHub-hosted runners in public repositories normally do not consume private-repository
included minutes. Job counts alone cannot identify the cause of an account billing block; verify
account-level Actions usage, artifact/cache storage, repository visibility history, and any larger
runner usage before attributing charges to this repository. This workflow does not change billing.

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
