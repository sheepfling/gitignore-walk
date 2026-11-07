"""Run the same verification steps locally and in CI."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
SRC: Final = ROOT / "src"
sys.path.insert(0, str(SRC))

from gitignore_walk._environment import EnvVar  # noqa: E402


def _writable_temp_root() -> Path:
    candidates: list[Path] = []
    if os.name == "nt":
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


TEMP_ROOT: Final = _writable_temp_root()
os.environ[EnvVar.TEMP] = str(TEMP_ROOT)
os.environ[EnvVar.TMP] = str(TEMP_ROOT)
if os.name != "nt":
    os.environ[EnvVar.TMPDIR] = str(TEMP_ROOT)
TEST_TEMP: Final = TEMP_ROOT / "gitignore-walk-ci"
DEFAULT_PYTHON_VERSIONS: Final = ("3.10", "3.11", "3.12", "3.13", "3.14", "3.15")
DEFAULT_LINUX_DOCKER_VERSIONS: Final = ("3.10", "3.12", "3.15")


def main(argv: Sequence[str] | None = None) -> int:
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
    basetemp = TEST_TEMP / f"pytest-{version}"
    basetemp.parent.mkdir(parents=True, exist_ok=True)
    environment = _environment_with_source()
    print(f"Testing Python {version}", flush=True)
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

    environment = TEST_TEMP / "local-venvs" / version
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
        "apt-get install -y -qq git libatomic1 >/dev/null",
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
    mount = f"type=bind,source={ROOT},target=/work"
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
    for command in (
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "ruff", "format", "--check", "."],
        [sys.executable, "-m", "pyright"],
    ):
        result = _run(command)
        if result:
            return result
    return 0


def _package() -> int:
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
            ]
        )
        if result:
            return result

        artifacts = sorted(artifact_dir.glob("*.whl")) + sorted(artifact_dir.glob("*.tar.gz"))
        if len(artifacts) != 2:
            raise RuntimeError(f"expected one wheel and one source archive, found {artifacts}")

        result = _run([sys.executable, "-m", "twine", "check", *(str(p) for p in artifacts)])
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
            ]
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
        return _run([sys.executable, "-c", smoke], cwd=artifact_dir, environment=environment)


def _python_version(python: str) -> str:
    result = subprocess.run(
        [python, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"could not run {python}")
    return result.stdout.strip()


def _environment_with_source() -> dict[str, str]:
    environment = os.environ.copy()
    source = str(SRC)
    previous = environment.get(EnvVar.PYTHONPATH)
    environment[EnvVar.PYTHONPATH] = source + os.pathsep + previous if previous else source
    return environment


def _run(
    command: Sequence[str],
    *,
    cwd: Path = ROOT,
    environment: dict[str, str] | None = None,
) -> int:
    printable_command = (
        subprocess.list2cmdline(list(command)) if os.name == "nt" else shlex.join(command)
    )
    print("+ " + printable_command, flush=True)
    result = subprocess.run(command, cwd=cwd, env=environment, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
