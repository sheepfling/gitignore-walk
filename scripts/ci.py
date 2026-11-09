"""Run the same verification steps locally and in CI."""

from __future__ import annotations

import argparse
import importlib.util
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Final


class EnvVar:
    """Environment-variable names used by the local CI tooling."""

    DEBIAN_FRONTEND: Final = "DEBIAN_FRONTEND"
    LOCALAPPDATA: Final = "LOCALAPPDATA"
    PYTHONHOME: Final = "PYTHONHOME"
    PYTHONPATH: Final = "PYTHONPATH"
    TEMP: Final = "TEMP"
    TMP: Final = "TMP"
    TMPDIR: Final = "TMPDIR"
    USERPROFILE: Final = "USERPROFILE"
    UV_CACHE_DIR: Final = "UV_CACHE_DIR"


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def project_src() -> Path:
    return project_root() / "src"


def is_windows() -> bool:
    """Return whether the current Python process runs on Windows."""
    return os.name == "nt"


def _writable_temp_root() -> Path:
    candidates: list[Path] = []
    if is_windows():
        user_profile = os.environ.get(EnvVar.USERPROFILE)
        if user_profile:
            candidates.append(Path(user_profile) / "AppData" / "Local" / "Temp")
        local_app_data = os.environ.get(EnvVar.LOCALAPPDATA)
        if local_app_data:
            candidates.append(Path(local_app_data) / "Temp")
    for variable in (EnvVar.TMPDIR, EnvVar.TEMP, EnvVar.TMP):
        value = os.environ.get(variable)
        if value:
            candidates.append(Path(value))
    candidates.append(Path(tempfile.gettempdir()))

    for candidate in dict.fromkeys(path.resolve() for path in candidates):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=candidate) as temporary:
                Path(temporary, "probe").write_text("", encoding="utf-8")
        except OSError:
            continue
        return candidate
    raise RuntimeError("no writable temporary directory is available")


def temp_root() -> Path:
    return _writable_temp_root()


def test_temp() -> Path:
    return temp_root() / "gitignore-walk-ci"


def setup_env() -> None:
    TEMP_ROOT = temp_root()
    os.environ[EnvVar.TEMP] = str(TEMP_ROOT)
    os.environ[EnvVar.TMP] = str(TEMP_ROOT)
    if not is_windows():
        os.environ[EnvVar.TMPDIR] = str(TEMP_ROOT)


def main(argv: Sequence[str] | None = None) -> int:
    setup_env()
    DEFAULT_PYTHON_VERSIONS: Final = ("3.10", "3.11", "3.12", "3.13", "3.14", "3.15")
    DEFAULT_LINUX_DOCKER_VERSIONS: Final = ("3.10", "3.12", "3.15")

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("test", help="run the test suite")

    matrix_command = commands.add_parser(
        "matrix", help="run tests on locally installed Python versions"
    )
    matrix_command.add_argument(
        "--versions", nargs="+", default=DEFAULT_PYTHON_VERSIONS, metavar="MAJOR.MINOR"
    )

    local_command = commands.add_parser(
        "local",
        help="run Windows interpreter and Linux Docker matrices available on this machine",
    )
    local_command.add_argument(
        "--windows-versions",
        nargs="+",
        default=DEFAULT_PYTHON_VERSIONS,
        metavar="MAJOR.MINOR",
    )
    local_command.add_argument(
        "--linux-versions",
        nargs="+",
        default=DEFAULT_LINUX_DOCKER_VERSIONS,
        metavar="MAJOR.MINOR",
    )
    local_command.add_argument("--skip-windows", action="store_true")
    local_command.add_argument("--skip-linux", action="store_true")

    commands.add_parser("quality", help="run lint, format, and strict type checks")
    commands.add_parser("package", help="build and validate the wheel and source archive")

    oracle_command = commands.add_parser(
        "oracle-hg", help="capture Mercurial behavior in isolated disposable repositories"
    )
    oracle_command.add_argument("--hg", default="hg", help="Mercurial executable")
    oracle_command.add_argument(
        "--output",
        type=Path,
        default=project_root() / "tests" / "oracles" / "hg" / "capture.local.json",
        help="path for the native observation capture",
    )
    oracle_command.add_argument(
        "--walk-output",
        type=Path,
        default=project_root() / "tests" / "oracles" / "hg" / "capture.walk.local.json",
        help="path for the native ignored-file walk capture",
    )
    oracle_command.add_argument(
        "--trust-output",
        type=Path,
        default=project_root() / "tests" / "oracles" / "hg" / "capture.trust.local.json",
        help="path for the native repository-config trust capture",
    )

    svn_oracle_command = commands.add_parser(
        "oracle-svn", help="capture Subversion ignore behavior in an isolated local repository"
    )
    svn_oracle_command.add_argument("--svn", default="svn", help="Subversion executable")
    svn_oracle_command.add_argument("--svnadmin", default="svnadmin", help="svnadmin executable")
    svn_oracle_command.add_argument(
        "--output",
        type=Path,
        default=project_root() / "tests" / "oracles" / "svn" / "capture.local.json",
        help="path for the native observation capture",
    )

    fossil_oracle_command = commands.add_parser(
        "oracle-fossil", help="capture Fossil ignore-glob behavior in an isolated checkout"
    )
    fossil_oracle_command.add_argument("--fossil", default="fossil", help="Fossil executable")
    fossil_oracle_command.add_argument(
        "--output",
        type=Path,
        default=project_root() / "tests" / "oracles" / "fossil" / "capture.local.json",
        help="path for the native observation capture",
    )

    brz_oracle_command = commands.add_parser(
        "oracle-brz", help="capture Breezy ignore behavior in isolated working trees"
    )
    brz_oracle_command.add_argument("--brz", default="brz", help="Breezy executable")
    brz_oracle_command.add_argument(
        "--output",
        type=Path,
        default=project_root() / "tests" / "oracles" / "breezy" / "capture.local.json",
        help="path for the native observation capture",
    )

    darcs_oracle_command = commands.add_parser(
        "oracle-darcs", help="capture Darcs boring-file behavior in disposable repositories"
    )
    darcs_oracle_command.add_argument("--darcs", default="darcs", help="Darcs executable")
    darcs_oracle_command.add_argument(
        "--output",
        type=Path,
        default=project_root() / "tests" / "oracles" / "darcs" / "capture.local.json",
        help="path for the native observation capture",
    )

    compatibility_oracle_command = commands.add_parser(
        "oracle-compat", help="probe Sapling/Jujutsu Git-ignore compatibility modes"
    )
    compatibility_oracle_command.add_argument("--sl", default="sl", help="Sapling executable")
    compatibility_oracle_command.add_argument("--jj", default="jj", help="Jujutsu executable")
    compatibility_oracle_command.add_argument(
        "--output",
        type=Path,
        default=project_root() / "tests" / "oracles" / "compat" / "capture.local.json",
        help="path for the native observation capture",
    )

    p4_oracle_command = commands.add_parser(
        "oracle-p4", help="capture P4IGNORE behavior with a disposable local P4 server"
    )
    p4_oracle_command.add_argument("--p4", default="p4", help="Perforce client executable")
    p4_oracle_command.add_argument("--p4d", default="p4d", help="Perforce server executable")
    p4_oracle_command.add_argument(
        "--output",
        type=Path,
        default=project_root() / "tests" / "oracles" / "perforce" / "capture.local.json",
        help="path for the native observation capture",
    )

    commands.add_parser("all", help="run tests, quality checks, and package validation")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "test":
            return _test(sys.executable)
        if arguments.command == "matrix":
            return _matrix(arguments.versions)
        if arguments.command == "local":
            return _local(
                windows_versions=arguments.windows_versions,
                linux_versions=arguments.linux_versions,
                skip_windows=arguments.skip_windows,
                skip_linux=arguments.skip_linux,
            )
        if arguments.command == "quality":
            return _quality()
        if arguments.command == "package":
            return _package()
        if arguments.command == "oracle-hg":
            return _oracle_hg(
                arguments.hg, arguments.output, arguments.walk_output, arguments.trust_output
            )
        if arguments.command == "oracle-svn":
            return _oracle_svn(arguments.svn, arguments.svnadmin, arguments.output)
        if arguments.command == "oracle-fossil":
            return _oracle_fossil(arguments.fossil, arguments.output)
        if arguments.command == "oracle-brz":
            return _oracle_brz(arguments.brz, arguments.output)
        if arguments.command == "oracle-darcs":
            return _oracle_darcs(arguments.darcs, arguments.output)
        if arguments.command == "oracle-compat":
            return _oracle_compat(arguments.sl, arguments.jj, arguments.output)
        if arguments.command == "oracle-p4":
            return _oracle_p4(arguments.p4, arguments.p4d, arguments.output)
        if arguments.command == "all":
            result = _test(sys.executable)
            if result:
                return result
            result = _quality()
            if result:
                return result
            result = _package()
            if result:
                return result
            return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"CI verification failed: {error}", file=sys.stderr)
        return 1
    return 2


def _test(python: str) -> int:
    version = _python_version(python)
    TEST_TEMP: Final = test_temp()
    basetemp = TEST_TEMP / f"pytest-{version}"
    basetemp.parent.mkdir(parents=True, exist_ok=True)
    environment = _environment_with_source()
    print(f"Running pytest on Python {version}", flush=True)
    return _run(
        [
            python,
            "-m",
            "pytest",
            "tests",
            "-q",
            "--basetemp",
            str(basetemp),
        ],
        label=f"pytest on Python {version}",
        environment=environment,
    )


def _matrix(versions: Sequence[str]) -> int:
    for version in versions:
        python = _find_python(version)
        result = _test(python)
        if result:
            print(f"Python {version} failed with exit code {result}", file=sys.stderr)
            return result
    return 0


def _local(
    *,
    windows_versions: Sequence[str],
    linux_versions: Sequence[str],
    skip_windows: bool,
    skip_linux: bool,
) -> int:
    if skip_windows and skip_linux:
        raise ValueError("at least one local platform must be selected")

    if not skip_windows:
        if os.name != "nt":
            print("Skipping Windows matrix: run this command on Windows to test Windows.")
        else:
            for version in windows_versions:
                base_python = _find_python(version)
                python = _prepare_windows_test_environment(base_python, version)
                result = _test(python)
                if result:
                    print(
                        f"Windows Python {version} failed with exit code {result}",
                        file=sys.stderr,
                    )
                    return result

    if not skip_linux:
        docker = shutil.which("docker")
        if not docker:
            raise RuntimeError(
                "Docker is required for the Linux matrix; pass --skip-linux to omit it"
            )
        for version in linux_versions:
            result = _docker_linux_matrix(docker, version)
            if result:
                print(
                    f"Linux Docker Python {version} failed with exit code {result}",
                    file=sys.stderr,
                )
                return result
    return 0


def _prepare_windows_test_environment(base_python: str, version: str) -> str:
    """Create and provision a reusable isolated pytest venv for one Windows interpreter."""
    environment = test_temp() / "local-venvs" / version
    python = environment / "Scripts" / "python.exe"
    if not python.is_file():
        result = _run([base_python, "-m", "venv", str(environment)])
        if result:
            raise RuntimeError(f"could not create the local Python {version} environment")
    if _python_version(str(python)) != version:
        raise RuntimeError(f"the local Python {version} environment has a different interpreter")
    result = _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "pytest>=8.3",
        ]
    )
    if result:
        raise RuntimeError(f"could not install pytest for Python {version}")
    return str(python)


def _docker_linux_matrix(docker: str, version: str) -> int:
    commands = [
        "set -eu",
        f"export {EnvVar.DEBIAN_FRONTEND}=noninteractive",
        "apt-get update -qq",
        "apt-get install -y -qq git libatomic1 subversion >/dev/null",
        (
            "python -m pip install --disable-pip-version-check "
            "-e '.[dev]' >/tmp/gitignore-walk-pip.log"
        ),
        "python -m scripts.ci test",
    ]
    if version == "3.12":
        commands.extend(
            [
                "python -m scripts.ci quality",
                "python -m scripts.ci package",
            ]
        )
    script = " && ".join(commands)
    mount = f"type=bind,source={project_root()},target=/work"
    return _run(
        [
            docker,
            "run",
            "--rm",
            "--mount",
            mount,
            "-w",
            "/work",
            f"python:{version}-slim",
            "sh",
            "-lc",
            script,
        ]
    )


def _find_python(version: str) -> str:
    current_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    if version == current_version:
        return sys.executable

    candidates = [f"python{version}", f"python{version.replace('.', '')}"]
    for candidate in candidates:
        executable = shutil.which(candidate)
        if executable and _python_version(executable) == version:
            return executable

    uv = shutil.which("uv")
    ROOT = project_root()
    if uv:
        environment = os.environ.copy()
        environment.setdefault(EnvVar.UV_CACHE_DIR, str(ROOT / ".uv-cache-gitignorewalk"))
        result = subprocess.run(
            [uv, "python", "find", version],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            executable = result.stdout.strip().splitlines()[-1]
            if _python_version(executable) == version:
                return executable

    raise RuntimeError(
        f"CPython {version} was not found. Install it, put python{version} on PATH, "
        "or install uv and run `uv python install <version>`."
    )


def _quality() -> int:
    for label, command in (
        ("Ruff lint", [sys.executable, "-m", "ruff", "check", "."]),
        ("Ruff format", [sys.executable, "-m", "ruff", "format", "--check", "."]),
        ("Pyright", [sys.executable, "-m", "pyright", "--pythonpath", sys.executable]),
        ("Markdown style (rumdl)", ["rumdl", "check", "."]),
    ):
        result = _run(command, label=label)
        if result:
            return result
    # The dev extra only installs mdrepo on interpreters supported by that release.
    if importlib.util.find_spec("mdrepo") is not None:
        return _run(
            [sys.executable, "-m", "mdrepo", "check", "."],
            label="Markdown repository policy (mdrepo)",
        )
    print("Skipping mdrepo repository checks: mdrepo is not installed for this interpreter.")
    return 0


def _oracle_hg(executable: str, output: Path, walk_output: Path, trust_output: Path) -> int:
    """Delegate Mercurial matching, walking, and trust captures to oracle runners."""
    oracle_root = project_root() / "tests" / "oracles" / "hg"
    for runner, capture_path, label in (
        (oracle_root / "run.py", output, "Capture native Mercurial ignore observations"),
        (oracle_root / "walk.py", walk_output, "Capture native Mercurial ignored-file walks"),
        (oracle_root / "trust.py", trust_output, "Capture native Mercurial config trust behavior"),
    ):
        result = _run(
            [sys.executable, str(runner), "--hg", executable, "--output", str(capture_path)],
            label=label,
        )
        if result:
            return result
    return 0


def _oracle_svn(executable: str, svnadmin: str, output: Path) -> int:
    """Delegate Subversion capture to its isolated, scheme-specific oracle runner."""
    runner = project_root() / "tests" / "oracles" / "svn" / "run.py"
    return _run(
        [
            sys.executable,
            str(runner),
            "--svn",
            executable,
            "--svnadmin",
            svnadmin,
            "--output",
            str(output),
        ],
        label="Capture native Subversion ignore observations",
    )


def _oracle_fossil(executable: str, output: Path) -> int:
    """Delegate Fossil behavior capture to its isolated, scheme-specific oracle runner."""
    runner = project_root() / "tests" / "oracles" / "fossil" / "run.py"
    return _run(
        [sys.executable, str(runner), "--fossil", executable, "--output", str(output)],
        label="Capture native Fossil ignore-glob observations",
    )


def _oracle_brz(executable: str, output: Path) -> int:
    """Delegate Breezy behavior capture to its isolated, scheme-specific oracle runner."""
    runner = project_root() / "tests" / "oracles" / "breezy" / "run.py"
    return _run(
        [sys.executable, str(runner), "--brz", executable, "--output", str(output)],
        label="Capture native Breezy ignore observations",
    )


def _oracle_darcs(executable: str, output: Path) -> int:
    """Delegate Darcs boring-file capture to its isolated native oracle runner."""
    runner = project_root() / "tests" / "oracles" / "darcs" / "run.py"
    return _run(
        [sys.executable, str(runner), "--darcs", executable, "--output", str(output)],
        label="Capture native Darcs boring-file observations",
    )


def _oracle_compat(sapling: str, jj: str, output: Path) -> int:
    """Delegate Git-compatible Sapling/Jujutsu probes to their disposable oracle runner."""
    runner = project_root() / "tests" / "oracles" / "compat" / "run.py"
    return _run(
        [sys.executable, str(runner), "--sl", sapling, "--jj", jj, "--output", str(output)],
        label="Capture Sapling/Jujutsu ignore compatibility modes",
    )


def _oracle_p4(p4: str, p4d: str, output: Path) -> int:
    """Delegate P4IGNORE capture to its isolated, server-backed oracle runner."""
    runner = project_root() / "tests" / "oracles" / "perforce" / "run.py"
    return _run(
        [sys.executable, str(runner), "--p4", p4, "--p4d", p4d, "--output", str(output)],
        label="Capture native Perforce ignore observations",
    )


def _package() -> int:
    TEST_TEMP = test_temp()
    TEST_TEMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="package-", dir=TEST_TEMP) as temporary:
        artifact_dir = Path(temporary)
        result = _run(
            [
                sys.executable,
                "-m",
                "build",
                "--no-isolation",
                "--outdir",
                str(artifact_dir),
            ],
            label="Build wheel and source archive",
        )
        if result:
            return result

        artifacts = sorted(artifact_dir.glob("*.whl")) + sorted(artifact_dir.glob("*.tar.gz"))
        if len(artifacts) != 2:
            raise RuntimeError(f"expected one wheel and one source archive, found {artifacts}")

        result = _run(
            [sys.executable, "-m", "twine", "check", *(str(p) for p in artifacts)],
            label="Twine metadata validation",
        )
        if result:
            return result

        wheel = next(path for path in artifacts if path.suffix == ".whl")
        install_dir = artifact_dir / "site-packages"
        result = _run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--target",
                str(install_dir),
                str(wheel),
            ],
            label="Install built wheel into isolated target",
        )
        if result:
            return result

        environment = os.environ.copy()
        environment.pop(EnvVar.PYTHONPATH, None)
        environment.pop(EnvVar.PYTHONHOME, None)
        environment[EnvVar.PYTHONPATH] = str(install_dir)
        smoke = (
            "import gitignore_walk; "
            "path = gitignore_walk.__file__; "
            "assert any(part.casefold() == 'site-packages' "
            "for part in __import__('pathlib').Path(path).parts), path; "
            "print(path)"
        )
        return _run(
            [sys.executable, "-c", smoke],
            label="Import installed wheel",
            cwd=artifact_dir,
            environment=environment,
        )


def _python_version(python: str) -> str:
    result = subprocess.run(
        [python, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
        cwd=project_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"could not run {python}")
    return result.stdout.strip()


def _environment_with_source() -> dict[str, str]:
    environment = os.environ.copy()
    source = str(project_src())
    previous = environment.get(EnvVar.PYTHONPATH)
    environment[EnvVar.PYTHONPATH] = source + os.pathsep + previous if previous else source
    return environment


def _run(
    command: Sequence[str],
    *,
    label: str | None = None,
    cwd: Path | None = None,
    environment: dict[str, str] | None = None,
) -> int:
    printable_command = (
        subprocess.list2cmdline(list(command)) if is_windows() else shlex.join(command)
    )
    step = label or printable_command
    print(f"\n==> {step}", flush=True)
    print("+ " + printable_command, flush=True)
    try:
        result = subprocess.run(
            command,
            cwd=project_root() if cwd is None else cwd,
            env=environment,
            check=False,
        )
    except OSError as error:
        print(f"FAILED: {step} (could not start command: {error})", file=sys.stderr, flush=True)
        return 1
    if result.returncode:
        print(f"FAILED: {step} (exit {result.returncode})", file=sys.stderr, flush=True)
    else:
        print(f"PASSED: {step}", flush=True)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
