"""Capture Mercurial ignored-file traversal in isolated disposable repositories."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from run import _config_text, _query_skip_reason, _symlink_is_directory, _write_files


def _capture_case(case: Mapping[str, Any], executable: str) -> dict[str, Any]:
    setup = case["setup"]
    skip_reason = _query_skip_reason("", native_os=os.name)
    if skip_reason is not None:
        return {
            "id": case["id"],
            "dimension": case["dimension"],
            "evidence_status": case["evidence_status"],
            "native_status": "skipped",
            "skip_reason": skip_reason,
            "expected_ignored_paths": sorted(case["expected_ignored_paths"]),
            "observed_ignored_paths": None,
            "expected_unknown_paths": sorted(case["expected_unknown_paths"]),
            "observed_unknown_paths": None,
            "candidate_matches": None,
            "tracked_paths": sorted(case.get("tracked_paths", [])),
            "init_exit_code": 0,
            "nested_init_exit_codes": [],
            "add_exit_codes": [],
            "exit_code": 0,
        }
    with tempfile.TemporaryDirectory(prefix="gitignore-walk-hg-walk-oracle-") as temporary:
        temp = Path(temporary)
        home = temp / "home"
        home.mkdir()
        root = temp / "repo"
        root.mkdir()
        config = {
            key: value.replace("<home>", str(home))
            for key, value in setup.get("config", {}).items()
        }
        hg_config = temp / "hgrc"
        hg_config.write_text(_config_text(config), encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "HGRCPATH": str(hg_config),
                "HGPLAIN": "1",
                "LC_ALL": "C",
            }
        )
        files = setup.get("files", {})
        _write_files(
            root,
            {relative: content for relative, content in files.items() if relative != ".hgignore"},
            home,
        )
        for relative, target in setup.get("symlinks", {}).items():
            link = root / relative
            link.parent.mkdir(parents=True, exist_ok=True)
            try:
                link.symlink_to(
                    target,
                    target_is_directory=_symlink_is_directory(relative, target, setup, link.parent),
                )
            except OSError as error:
                return {
                    "id": case["id"],
                    "dimension": case["dimension"],
                    "evidence_status": case["evidence_status"],
                    "native_status": "skipped",
                    "skip_reason": f"Unable to create fixture symlink: {error}",
                    "expected_ignored_paths": sorted(case["expected_ignored_paths"]),
                    "observed_ignored_paths": None,
                    "expected_unknown_paths": sorted(case["expected_unknown_paths"]),
                    "observed_unknown_paths": None,
                    "candidate_matches": None,
                    "tracked_paths": sorted(case.get("tracked_paths", [])),
                    "exit_code": None,
                }
        init = subprocess.run(
            [executable, "init", str(root)],
            cwd=temp,
            env=env,
            capture_output=True,
            timeout=30,
            check=False,
        )
        nested_init_results = [
            subprocess.run(
                [executable, "init", str(root / relative)],
                cwd=temp,
                env=env,
                capture_output=True,
                timeout=30,
                check=False,
            )
            for relative in setup.get("nested_repositories", [])
        ]
        add_results = []
        for relative in case.get("tracked_paths", []):
            add_results.append(
                subprocess.run(
                    [executable, "add", "--", relative],
                    cwd=root,
                    env=env,
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
            )
        if ".hgignore" in files:
            _write_files(root, {".hgignore": files[".hgignore"]}, home)
        observations: dict[str, dict[str, Any]] = {}
        for selection in ("ignored", "unknown"):
            command = [executable, "status", f"--{selection}", "--no-status", "-0"]
            status = subprocess.run(
                command,
                cwd=root,
                env=env,
                capture_output=True,
                timeout=30,
                check=False,
            )
            paths = sorted(
                path.decode("utf-8", errors="surrogateescape")
                for path in status.stdout.split(b"\0")
                if path
            )
            paths = sorted(path.replace("\\", "/") for path in paths)
            observations[selection] = {
                "command": command,
                "exit_code": status.returncode,
                "paths": paths,
                "stdout": status.stdout.decode("utf-8", errors="backslashreplace"),
                "stderr": status.stderr.decode("utf-8", errors="backslashreplace"),
                "stdout_sha256": hashlib.sha256(status.stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(status.stderr).hexdigest(),
            }
        ignored = observations["ignored"]["paths"]
        unknown = observations["unknown"]["paths"]
        expected_ignored = sorted(case["expected_ignored_paths"])
        expected_unknown = sorted(case["expected_unknown_paths"])
        return {
            "id": case["id"],
            "dimension": case["dimension"],
            "evidence_status": case["evidence_status"],
            "native_status": "captured",
            "expected_ignored_paths": expected_ignored,
            "observed_ignored_paths": ignored,
            "expected_unknown_paths": expected_unknown,
            "observed_unknown_paths": unknown,
            "candidate_matches": ignored == expected_ignored and unknown == expected_unknown,
            "tracked_paths": sorted(case.get("tracked_paths", [])),
            "observations": observations,
            "working_directory": "<repo>",
            "environment": {"HGRCPATH": "<temp>/hgrc", "HGPLAIN": "1", "LC_ALL": "C"},
            "init_exit_code": init.returncode,
            "nested_init_exit_codes": [item.returncode for item in nested_init_results],
            "add_exit_codes": [item.returncode for item in add_results],
            "exit_code": max(item["exit_code"] for item in observations.values()),
        }


def capture(cases_path: Path, output_path: Path, hg_executable: str) -> int:
    cases_data = json.loads(cases_path.read_text(encoding="utf-8"))
    executable = shutil.which(hg_executable)
    if executable is None:
        result = {
            "schema_version": 1,
            "status": "skipped",
            "reason": f"Mercurial executable not found: {hg_executable}",
            "client": None,
            "cases": [],
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return 0

    version = subprocess.run(
        [executable, "--version"], capture_output=True, text=True, check=False, timeout=30
    )
    captured = [_capture_case(case, executable) for case in cases_data["cases"]]
    failed = any(
        case["native_status"] != "skipped"
        and (
            case["init_exit_code"] != 0
            or any(code != 0 for code in case["nested_init_exit_codes"])
            or any(code != 0 for code in case["add_exit_codes"])
            or case["exit_code"] != 0
        )
        for case in captured
    )
    version_lines = version.stdout.splitlines()
    result = {
        "schema_version": 1,
        "status": "failed" if failed else "captured",
        "client": {
            "executable": executable,
            "version": version_lines[0] if version_lines else "unknown",
            "platform": platform.platform(),
            "runner_python": sys.version.split()[0],
        },
        "cases": captured,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    matched = sum(case["candidate_matches"] is True for case in captured)
    comparable = sum(case["candidate_matches"] is not None for case in captured)
    print(f"Captured {len(captured)} Mercurial walking cases: {result['status']}")
    print(f"Candidate walking observations matching: {matched}/{comparable}")
    print(f"Capture: {output_path}")
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("walk_cases.json"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("walk.capture.local.json"),
    )
    parser.add_argument("--hg", default="hg", help="Mercurial executable")
    args = parser.parse_args(argv)
    return capture(args.cases, args.output, args.hg)


if __name__ == "__main__":
    raise SystemExit(main())
