"""Capture Subversion ignore status in isolated local repositories."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _command(
    command: Sequence[str], *, cwd: Path | None, environment: Mapping[str, str]
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        env=dict(environment),
        capture_output=True,
        timeout=60,
        check=False,
    )


def _status_paths(stdout: bytes) -> tuple[list[str], list[str]]:
    document = ET.fromstring(stdout)
    entries = document.findall(".//entry")
    paths: list[str] = []
    ignored: list[str] = []
    for entry in entries:
        path = entry.attrib["path"].replace("\\", "/")
        status = entry.find("wc-status")
        if status is None:
            continue
        paths.append(path)
        if status.attrib.get("item") == "ignored":
            ignored.append(path)
    return sorted(paths), sorted(ignored)


def _write_files(root: Path, files: Mapping[str, str]) -> None:
    for relative, content in files.items():
        target = (root / relative).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError as error:
            raise ValueError(f"fixture path escapes its temporary root: {relative}") from error
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _start_svnserve(
    repository: Path, temporary: Path, environment: Mapping[str, str]
) -> tuple[subprocess.Popen[bytes], str]:
    """Serve one disposable repository on loopback for authority-relative URL probes."""
    svnserve = shutil.which("svnserve")
    if svnserve is None:
        raise FileNotFoundError("svnserve is required for scheme-relative external probes")
    config = temporary / "svnserve.conf"
    config.write_text("[general]\nanon-access = write\nauth-access = write\n", encoding="utf-8")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    process = subprocess.Popen(
        [
            svnserve,
            "--foreground",
            "--daemon",
            "--listen-host",
            "127.0.0.1",
            "--listen-port",
            str(port),
            "--root",
            str(repository),
            "--config-file",
            str(config),
        ],
        cwd=temporary,
        env=dict(environment),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    repository_url = f"svn://127.0.0.1:{port}"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"svnserve exited during startup with status {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return process, repository_url
        except OSError:
            time.sleep(0.05)
    process.terminate()
    process.wait(timeout=5)
    raise TimeoutError("svnserve did not start listening on loopback")


def _capture_case(
    case: Mapping[str, Any], svn: str, svnadmin: str, svnserve_name: str
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="gitignore-walk-svn-oracle-") as temporary:
        setup = case["setup"]
        temp = Path(temporary)
        repository = temp / "repository"
        working_copy = temp / "working-copy"
        config_dir = temp / "config"
        config_dir.mkdir()
        (config_dir / "config").write_text(
            "[miscellany]\nglobal-ignores = *.oracle-default\n", encoding="utf-8"
        )
        environment = {
            "HOME": str(temp / "home"),
            "LC_ALL": "C",
            "LANG": "C",
            "PATH": os.environ.get("PATH", ""),
        }
        Path(environment["HOME"]).mkdir()
        create_command = [svnadmin, "create", str(repository)]
        create = _command(create_command, cwd=temp, environment=environment)
        server_process = None
        try:
            if setup.get("repository_protocol") == "svnserve":
                svnserve = shutil.which(svnserve_name)
                if svnserve is None:
                    raise FileNotFoundError(f"{svnserve_name} is required for this SVN fixture")
                server_process, repository_url = _start_svnserve(repository, temp, environment)
            else:
                repository_url = repository.as_uri()
            url = f"{repository_url}/trunk"
            repository_directories = setup.get("repository_directories", [])
            mkdir_command = [
                svn,
                "--config-dir",
                str(config_dir),
                "mkdir",
                url,
                *(f"{repository_url}/{relative}" for relative in repository_directories),
                "-m",
                "init",
            ]
            mkdir = _command(mkdir_command, cwd=temp, environment=environment)
            setup_results = [create, mkdir]
            for relative in setup.get("repository_subdirectories", []):
                setup_results.append(
                    _command(
                        [
                            svn,
                            "--config-dir",
                            str(config_dir),
                            "mkdir",
                            f"{url}/{relative}",
                            "-m",
                            "nested repository directory",
                        ],
                        cwd=temp,
                        environment=environment,
                    )
                )
            checkout_subpath = setup.get("checkout_subpath")
            if checkout_subpath:
                parent_working_copy = temp / "parent-working-copy"
                setup_results.append(
                    _command(
                        [
                            svn,
                            "--config-dir",
                            str(config_dir),
                            "checkout",
                            url,
                            str(parent_working_copy),
                        ],
                        cwd=temp,
                        environment=environment,
                    )
                )
                parent_property_results = []
                for relative, properties in setup.get("repository_properties", {}).items():
                    target = "." if relative == "." else relative
                    for name, value in properties.items():
                        parent_property_results.append(
                            _command(
                                [
                                    svn,
                                    "--config-dir",
                                    str(config_dir),
                                    "propset",
                                    name,
                                    value,
                                    target,
                                ],
                                cwd=parent_working_copy,
                                environment=environment,
                            )
                        )
                setup_results.extend(parent_property_results)
                setup_results.append(
                    _command(
                        [
                            svn,
                            "--config-dir",
                            str(config_dir),
                            "commit",
                            "-m",
                            "repository parent properties",
                            ".",
                        ],
                        cwd=parent_working_copy,
                        environment=environment,
                    )
                )
                checkout_url = f"{url}/{checkout_subpath}"
            else:
                checkout_url = url
            checkout = _command(
                [svn, "--config-dir", str(config_dir), "checkout", checkout_url, str(working_copy)],
                cwd=temp,
                environment=environment,
            )
            setup_results.append(checkout)
            for relative in setup.get("directories", []):
                (working_copy / relative).mkdir(parents=True, exist_ok=True)
            _write_files(working_copy, setup.get("versioned_files", {}))
            add_command = [svn, "--config-dir", str(config_dir), "add", "--force", "."]
            add = _command(add_command, cwd=working_copy, environment=environment)
            property_results = []
            for relative, properties in setup.get("properties", {}).items():
                target = "." if relative == "." else relative
                for name, value in properties.items():
                    value = value.replace("<repository_url>", repository_url).replace(
                        "<repository_path>", repository.as_uri().removeprefix("file://")
                    )
                    if repository_url.startswith("svn://"):
                        authority = repository_url.removeprefix("svn://").split("/", 1)[0]
                        value = value.replace("<repository_authority>", authority)
                    property_results.append(
                        _command(
                            [svn, "--config-dir", str(config_dir), "propset", name, value, target],
                            cwd=working_copy,
                            environment=environment,
                        )
                    )
            commit_command = [svn, "--config-dir", str(config_dir), "commit", "-m", "fixture"]
            commit = _command(commit_command, cwd=working_copy, environment=environment)
            external_update = None
            if setup.get("external_files"):
                external_update = _command(
                    [svn, "--config-dir", str(config_dir), "update"],
                    cwd=working_copy,
                    environment=environment,
                )
            sparse_updates = [
                _command(
                    [
                        svn,
                        "--config-dir",
                        str(config_dir),
                        "update",
                        "--set-depth",
                        depth,
                        relative,
                    ],
                    cwd=working_copy,
                    environment=environment,
                )
                for relative, depth in setup.get("sparse_depths", {}).items()
            ]
            _write_files(working_copy, setup.get("unversioned_files", {}))
            _write_files(working_copy, setup.get("external_files", {}))
            nested_results = []
            for index, (relative, nested_setup) in enumerate(
                setup.get("nested_working_copies", {}).items()
            ):
                nested_repository = temp / f"nested-repository-{index}"
                nested_create = _command(
                    [svnadmin, "create", str(nested_repository)], cwd=temp, environment=environment
                )
                nested_url = (nested_repository / "trunk").as_uri()
                nested_mkdir = _command(
                    [svn, "--config-dir", str(config_dir), "mkdir", nested_url, "-m", "nested"],
                    cwd=temp,
                    environment=environment,
                )
                nested_path = working_copy / relative
                nested_checkout = _command(
                    [
                        svn,
                        "--config-dir",
                        str(config_dir),
                        "checkout",
                        nested_url,
                        str(nested_path),
                    ],
                    cwd=temp,
                    environment=environment,
                )
                _write_files(nested_path, nested_setup.get("unversioned_files", {}))
                nested_results.extend((nested_create, nested_mkdir, nested_checkout))

            observations: dict[str, dict[str, Any]] = {}
            for label, options in (("default", []), ("no_ignore", ["--no-ignore"])):
                command = [svn, "--config-dir", str(config_dir), "status", "--xml", *options]
                result = _command(command, cwd=working_copy, environment=environment)
                paths, ignored = (
                    _status_paths(result.stdout) if result.returncode == 0 else ([], [])
                )
                observations[label] = {
                    "command": command,
                    "exit_code": result.returncode,
                    "paths": paths,
                    "ignored_paths": ignored,
                    "stdout": result.stdout.decode("utf-8", errors="backslashreplace"),
                    "stderr": result.stderr.decode("utf-8", errors="backslashreplace"),
                    "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
                    "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
                }

            observed_ignored = observations["no_ignore"]["ignored_paths"]
            expected_ignored = sorted(case["expected_ignored_paths"])
            expected_status_paths = case.get("expected_status_paths")
            observed_status_paths = observations["no_ignore"]["paths"]
            command_results = [
                *setup_results,
                add,
                *property_results,
                commit,
                *([external_update] if external_update is not None else []),
                *sparse_updates,
                *nested_results,
            ]
            result = {
                "id": case["id"],
                "dimension": case["dimension"],
                "evidence_status": case["evidence_status"],
                "native_status": "captured",
                "expected_ignored_paths": expected_ignored,
                "observed_ignored_paths": observed_ignored,
                "expected_status_paths": expected_status_paths,
                "observed_status_paths": observed_status_paths,
                "candidate_matches": observed_ignored == expected_ignored
                and (
                    expected_status_paths is None
                    or observed_status_paths == sorted(expected_status_paths)
                ),
                "versioned_files": sorted(setup.get("versioned_files", {})),
                "observations": observations,
                "setup_exit_codes": [result.returncode for result in command_results],
            }
            return result
        finally:
            if server_process is not None and server_process.poll() is None:
                server_process.terminate()
                server_process.wait(timeout=5)


def _skip_case(case: Mapping[str, Any], reason: str) -> dict[str, Any]:
    """Record an oracle case that this client profile cannot execute."""
    return {
        "id": case["id"],
        "dimension": case["dimension"],
        "evidence_status": case["evidence_status"],
        "native_status": "skipped",
        "skip_reason": reason,
        "candidate_matches": None,
    }


def capture(
    cases_path: Path,
    output_path: Path,
    svn_name: str,
    svnadmin_name: str,
    svnserve_name: str = "svnserve",
) -> int:
    cases_data = json.loads(cases_path.read_text(encoding="utf-8"))
    svn = shutil.which(svn_name)
    svnadmin = shutil.which(svnadmin_name)
    if svn is None or svnadmin is None:
        missing = [
            name for name, path in ((svn_name, svn), (svnadmin_name, svnadmin)) if path is None
        ]
        result = {
            "schema_version": 1,
            "status": "skipped",
            "reason": "Subversion executable(s) not found: " + ", ".join(missing),
            "client": None,
            "cases": [],
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return 0

    version_result = _command([svn, "--version", "--quiet"], cwd=None, environment=os.environ)
    admin_version_result = _command(
        [svnadmin, "--version", "--quiet"], cwd=None, environment=os.environ
    )
    svn_version = version_result.stdout.decode("utf-8", errors="replace").strip()
    admin_version = admin_version_result.stdout.decode("utf-8", errors="replace").strip()
    svnserve_available = shutil.which(svnserve_name) is not None
    captured = [
        (
            _skip_case(case, case["windows_skip_reason"])
            if os.name == "nt" and case.get("windows_skip_reason")
            else (
                _skip_case(case, f"Subversion server executable not found: {svnserve_name}")
                if case["setup"].get("repository_protocol") == "svnserve" and not svnserve_available
                else _capture_case(case, svn, svnadmin, svnserve_name)
            )
        )
        for case in cases_data["cases"]
    ]
    failed = any(
        case["native_status"] == "captured"
        and (
            any(code != 0 for code in case["setup_exit_codes"])
            or case["observations"]["default"]["exit_code"] != 0
            or case["observations"]["no_ignore"]["exit_code"] != 0
        )
        for case in captured
    )
    result = {
        "schema_version": 1,
        "status": "failed" if failed else "captured",
        "client": {
            "svn": {"executable": svn, "version": svn_version},
            "svnadmin": {"executable": svnadmin, "version": admin_version},
            "platform": platform.platform(),
            "runner_python": sys.version.split()[0],
        },
        "cases": captured,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    matched = sum(case.get("candidate_matches") is True for case in captured)
    compared = sum(case.get("candidate_matches") is not None for case in captured)
    skipped = sum(case["native_status"] == "skipped" for case in captured)
    print(f"Processed {len(captured)} Subversion cases: {result['status']}")
    print(f"Candidate ignored-path lists matching: {matched}/{compared}")
    print(f"Cases skipped for this client profile: {skipped}")
    print(f"Capture: {output_path}")
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("cases.json"))
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).with_name("capture.local.json")
    )
    parser.add_argument("--svn", default="svn", help="Subversion executable")
    parser.add_argument("--svnadmin", default="svnadmin", help="svnadmin executable")
    parser.add_argument("--svnserve", default="svnserve", help="svnserve executable")
    args = parser.parse_args(argv)
    return capture(args.cases, args.output, args.svn, args.svnadmin, args.svnserve)


if __name__ == "__main__":
    raise SystemExit(main())
