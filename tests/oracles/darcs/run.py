"""Capture native Darcs boring-file decisions in disposable repositories."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _run(
    executable: str,
    arguments: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [executable, *arguments],
        cwd=cwd,
        env=dict(environment),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )


def _write_files(root: Path, files: Mapping[str, str]) -> None:
    for relative, contents in files.items():
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as error:
            raise ValueError(f"fixture path escapes temporary repository: {relative}") from error
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as stream:
            stream.write(contents)


def _paths_from_annotated_lines(output: str, marker: str) -> set[str]:
    paths: set[str] = set()
    for line in output.splitlines():
        match = re.match(rf"^{re.escape(marker)}\s+(.+)$", line)
        if match:
            paths.add(match.group(1).strip().removeprefix("./"))
    return paths


def _global_boring_path(environment: Mapping[str, str], *, windows: bool | None = None) -> Path:
    """Return Darcs' per-user boring-file path for the selected platform."""
    if windows is None:
        windows = os.name == "nt"
    if windows:
        app_data = environment.get("APPDATA")
        if app_data is None:
            raise ValueError("APPDATA must be set to capture Windows Darcs configuration")
        return Path(app_data) / "darcs" / "boring"
    home = environment.get("HOME")
    if home is None:
        raise ValueError("HOME must be set to capture POSIX Darcs configuration")
    return Path(home) / ".darcs" / "boring"


def _capture_case(case: Mapping[str, Any], executable: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="gitignore-walk-darcs-oracle-") as temporary:
        base = Path(temporary)
        home = base / "home"
        home.mkdir()
        repository = base / "repository"
        repository.mkdir()
        setup = case["setup"]
        environment = {
            "APPDATA": str(home),
            "PATH": os.environ.get("PATH", ""),
            "DARCS_PAGER": "cat",
            "PAGER": "cat",
            "LC_ALL": setup.get("locale", "C"),
            "LANG": setup.get("locale", "C"),
            "TZ": "UTC",
        }
        if os.name != "nt":
            environment["HOME"] = str(home)
        init = _run(
            executable,
            ["init", "--repodir", str(repository)],
            cwd=repository,
            environment=environment,
        )
        if init.returncode != 0:
            raise RuntimeError(f"darcs init failed: {init.stderr.strip() or init.stdout.strip()}")

        local_boring = repository / "_darcs" / "prefs" / "boring"
        with local_boring.open("w", encoding="utf-8", newline="") as stream:
            stream.write(setup.get("local_boring", ""))
        global_boring = _global_boring_path(environment)
        if "global_boring" in setup:
            global_boring.parent.mkdir(parents=True, exist_ok=True)
            with global_boring.open("w", encoding="utf-8", newline="") as stream:
                stream.write(setup["global_boring"])

        for relative in setup.get("nested_repositories", []):
            nested_root = (repository / relative).resolve()
            try:
                nested_root.relative_to(repository.resolve())
            except ValueError as error:
                raise ValueError(f"nested repository escapes fixture root: {relative}") from error
            if nested_root == repository.resolve():
                raise ValueError("nested repository must be below the fixture root")
            nested_root.mkdir(parents=True, exist_ok=True)
            nested_init = _run(
                executable,
                ["init", "--repodir", str(nested_root)],
                cwd=nested_root,
                environment=environment,
            )
            if nested_init.returncode != 0:
                detail = nested_init.stderr.strip() or nested_init.stdout.strip()
                raise RuntimeError(f"nested darcs init failed: {detail}")

        _write_files(repository, setup.get("files", {}))
        boringfile = setup.get("boringfile")
        if boringfile is not None:
            added_boringfile = _run(
                executable,
                ["add", "--boring", boringfile],
                cwd=repository,
                environment=environment,
            )
            if added_boringfile.returncode != 0:
                raise RuntimeError(
                    "darcs add for boringfile failed: "
                    f"{added_boringfile.stderr.strip() or added_boringfile.stdout.strip()}"
                )
            setpref = _run(
                executable,
                ["setpref", "boringfile", boringfile],
                cwd=repository,
                environment=environment,
            )
            if setpref.returncode != 0:
                raise RuntimeError(f"darcs setpref failed: {setpref.stderr.strip()}")

        for relative in setup.get("tracked", []):
            path = repository / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
            added = _run(
                executable,
                ["add", "--boring", relative],
                cwd=repository,
                environment=environment,
            )
            if added.returncode != 0:
                raise RuntimeError(
                    f"darcs add failed: {added.stderr.strip() or added.stdout.strip()}"
                )

        query = case.get("query")
        if query is not None:
            target = (repository / query).resolve()
            try:
                target.relative_to(repository.resolve())
            except ValueError as error:
                raise ValueError(f"fixture query escapes temporary repository: {query}") from error
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch(exist_ok=True)

        candidates = _run(
            executable,
            ["whatsnew", "--look-for-adds", "--summary"],
            cwd=repository,
            environment=environment,
        )
        tracked = _run(
            executable,
            ["show", "files"],
            cwd=repository,
            environment=environment,
        )
        candidate_paths = _paths_from_annotated_lines(candidates.stdout, "a")
        tracked_paths = {line.strip().removeprefix("./") for line in tracked.stdout.splitlines()}
        observed_boring: bool | None = None
        if query is not None and candidates.returncode in (0, 1) and tracked.returncode == 0:
            observed_boring = query not in candidate_paths and query not in tracked_paths
        return {
            "id": case["id"],
            "dimension": case["dimension"],
            "query": query,
            "expected_boring": case["expected_boring"],
            "observed_boring": observed_boring,
            "candidate_paths": sorted(candidate_paths),
            "tracked_paths": sorted(tracked_paths),
            "whatsnew_exit_code": candidates.returncode,
            "whatsnew_stdout": candidates.stdout,
            "whatsnew_stderr": candidates.stderr,
            "show_files_exit_code": tracked.returncode,
            "setup_isolated": True,
            "repository_root": "<temp>/repository",
            "home": "<temp>/home",
        }


def capture(executable: str) -> dict[str, Any]:
    case_path = Path(__file__).with_name("cases.json")
    cases = json.loads(case_path.read_text(encoding="utf-8"))["cases"]
    version = subprocess.run(
        [executable, "--version"], capture_output=True, text=True, timeout=30, check=True
    ).stdout.strip()
    return {
        "schema_version": 1,
        "status": "captured",
        "client": {"version": version, "platform": platform.platform()},
        "cases": [_capture_case(case, executable) for case in cases],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--darcs", default="darcs", help="Darcs executable")
    parser.add_argument("--output", type=Path, required=True, help="capture JSON destination")
    arguments = parser.parse_args()
    result = capture(arguments.darcs)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    total = sum(case["expected_boring"] is not None for case in result["cases"])
    matched = sum(
        case["expected_boring"] is not None and case["expected_boring"] == case["observed_boring"]
        for case in result["cases"]
    )
    print(f"Captured {len(result['cases'])} Darcs cases: {result['status']}")
    print(f"Boolean candidates matching: {matched}/{total}")
    print(f"Capture: {arguments.output}")
    return 0 if matched == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
