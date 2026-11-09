"""Capture Breezy ignore behavior in disposable, isolated working trees."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from unittest.mock import patch


def _invoke(
    command: Sequence[str], *, cwd: Path, environment: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
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
    for relative, content in files.items():
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as error:
            raise ValueError(f"fixture path escapes its temporary tree: {relative}") from error
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as stream:
            stream.write(content)


def _ignored_paths(output: str) -> set[str]:
    paths: set[str] = set()
    for line in output.splitlines():
        match = re.match(r"^(.*?)\s{2,}\S", line)
        if match:
            paths.add(match.group(1).strip())
    return paths


def _unknown_paths(output: str) -> set[str]:
    """Extract unversioned paths from Breezy's short status output."""
    paths: set[str] = set()
    for line in output.splitlines():
        match = re.match(r"^\?\s+(.+)$", line)
        if match:
            paths.add(match.group(1).strip())
    return paths


def _add_anchor(
    checkout: Path,
    anchor: Path,
    *,
    executable: str,
    environment: Mapping[str, str],
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Version a nested fixture anchor using Breezy's native working-tree API on Windows."""
    if os.name != "nt":
        relative_anchor = anchor.relative_to(checkout).as_posix()
        return (
            _invoke(
                [executable, "add", "--no-plugins", relative_anchor],
                cwd=checkout,
                environment=environment,
            ),
            "cli",
        )

    try:
        import breezy
        from breezy import plugin
        from breezy.workingtree import WorkingTree
    except ImportError:
        relative_anchor = anchor.relative_to(checkout).as_posix()
        return (
            _invoke(
                [executable, "add", "--no-plugins", relative_anchor],
                cwd=checkout,
                environment=environment,
            ),
            "cli-fallback",
        )

    command = [executable, "add", "--no-plugins", str(anchor)]
    try:
        with patch.dict(os.environ, environment, clear=True):
            breezy.initialize()
            plugin.load_plugins()
            tree = WorkingTree.open(str(checkout))
            relative_parent = anchor.parent.relative_to(checkout)
            with tree.lock_write():
                for depth in range(1, len(relative_parent.parts) + 1):
                    directory = Path(*relative_parent.parts[:depth]).as_posix()
                    tree.add([directory])
                tree.add([anchor.relative_to(checkout).as_posix()])
    except Exception as error:
        stderr = f"{type(error).__name__}: {error}"
        return subprocess.CompletedProcess(command, 1, "", stderr), "api"
    return subprocess.CompletedProcess(command, 0, "", ""), "api"


def _capture_case(case: Mapping[str, Any], executable: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="gitignore-walk-brz-oracle-") as temporary:
        base = Path(temporary)
        home = base / "home"
        home.mkdir()
        config_home = home / ".config"
        app_data = base / "appdata"
        checkout = (base / "checkout").resolve()
        checkout.mkdir()
        setup = case["setup"]
        brz_home = base / "brz-home"
        if setup.get("brz_home"):
            global_ignore = brz_home / "breezy" / "ignore"
        elif os.name == "nt":
            global_ignore = app_data / "Breezy" / "3.0" / "ignore"
        else:
            global_ignore = config_home / "breezy" / "ignore"
        environment = {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "APPDATA": str(app_data),
            "XDG_CONFIG_HOME": str(config_home),
            "BRZ_PLUGIN_PATH": "",
            "BRZ_LOG": os.devnull,
            "PATH": os.environ.get("PATH", ""),
            "LC_ALL": "C",
            "LANG": "C",
            "TZ": "UTC",
        }
        if setup.get("brz_home"):
            environment["BRZ_HOME"] = str(brz_home)
        _write_files(checkout, setup.get("files", {}))
        if setup.get("patterns") is not None:
            with (checkout / ".bzrignore").open("w", encoding="utf-8", newline="") as stream:
                stream.write("\n".join(setup["patterns"]) + "\n")
        if setup.get("global_ignore_file_exists") or "global_ignore_file_content" in setup:
            global_ignore.parent.mkdir(parents=True, exist_ok=True)
            global_ignore.write_text(setup.get("global_ignore_file_content", ""), encoding="utf-8")
        if "brz_home_ignore_file_content" in setup:
            global_ignore.parent.mkdir(parents=True, exist_ok=True)
            global_ignore.write_text(setup["brz_home_ignore_file_content"], encoding="utf-8")
        global_ignore_existed_before = global_ignore.exists()
        init = _invoke(
            [executable, "init", "--no-plugins", str(checkout)],
            cwd=checkout,
            environment=environment,
        )
        query = case.get("query")
        anchor_add = None
        anchor_add_method = None
        if query is not None:
            target = (checkout / query).resolve()
            try:
                target.relative_to(checkout.resolve())
            except ValueError as error:
                raise ValueError(f"fixture query escapes temporary tree: {query}") from error
            if target.parent != checkout:
                anchor = target.parent / ".oracle-walk-anchor"
                anchor.parent.mkdir(parents=True, exist_ok=True)
                anchor.write_text("native walker anchor\n", encoding="utf-8")
                anchor_add, anchor_add_method = _add_anchor(
                    checkout,
                    anchor,
                    executable=executable,
                    environment=environment,
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch(exist_ok=True)
        ignored_command = [executable, "ignored", "--no-plugins", "--verbose"]
        ignored = _invoke(ignored_command, cwd=checkout, environment=environment)
        status_command = [executable, "status", "--no-plugins", "--short", "--no-classify"]
        status = _invoke(status_command, cwd=checkout, environment=environment)
        paths = _ignored_paths(ignored.stdout)
        unknown_paths = _unknown_paths(status.stdout)
        observed = query in paths if query is not None else None
        observed_unknown = query in unknown_paths if query is not None else None
        expected = case.get("expected_candidate")
        candidate = expected.get("ignored") if isinstance(expected, dict) else expected
        candidate_matches = observed == candidate if isinstance(candidate, bool) else None
        return {
            "id": case["id"],
            "dimension": case["dimension"],
            "evidence_status": case["evidence_status"],
            "native_status": "captured",
            "expected_candidate": expected,
            "query": query,
            "observed_ignored": observed,
            "observed_unknown": observed_unknown,
            "candidate_matches": candidate_matches,
            "init_exit_code": init.returncode,
            "init_stderr": init.stderr,
            "anchor_add_exit_code": anchor_add.returncode if anchor_add else None,
            "anchor_add_stderr": anchor_add.stderr if anchor_add else "",
            "anchor_add_method": anchor_add_method,
            "ignored_command": ["brz", "ignored", "--no-plugins", "--verbose"],
            "ignored_exit_code": ignored.returncode,
            "status_command": ["brz", "status", "--no-plugins", "--short", "--no-classify"],
            "status_exit_code": status.returncode,
            "ignored_paths": sorted(paths),
            "unknown_paths": sorted(unknown_paths),
            "stdout": ignored.stdout,
            "stderr": ignored.stderr,
            "status_stdout": status.stdout,
            "status_stderr": status.stderr,
            "stdout_sha256": hashlib.sha256(ignored.stdout.encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256(ignored.stderr.encode("utf-8")).hexdigest(),
            "isolated_configuration": True,
            "global_ignore_existed_before": global_ignore_existed_before,
            "global_ignore_exists_after": global_ignore.exists(),
        }


def capture(cases_path: Path, output_path: Path, brz_name: str) -> int:
    cases_data = json.loads(cases_path.read_text(encoding="utf-8"))
    executable = shutil.which(brz_name)
    if executable is None:
        result: dict[str, Any] = {
            "schema_version": 1,
            "status": "skipped",
            "reason": f"Breezy executable not found: {brz_name}",
            "client": None,
            "cases": [],
        }
    else:
        version = _invoke([executable, "--version"], cwd=Path.cwd(), environment=os.environ)
        version_text = version.stdout.splitlines()
        with tempfile.TemporaryDirectory(prefix="gitignore-walk-brz-defaults-") as temporary:
            home = Path(temporary)
            environment = {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "APPDATA": str(home / "appdata"),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "BRZ_PLUGIN_PATH": "",
                "BRZ_LOG": os.devnull,
                "PATH": os.environ.get("PATH", ""),
                "LC_ALL": "C",
                "LANG": "C",
                "TZ": "UTC",
            }
            defaults = _invoke(
                [executable, "ignore", "--no-plugins", "--default-rules"],
                cwd=home,
                environment=environment,
            )
        captured = [_capture_case(case, executable) for case in cases_data["cases"]]
        failed = defaults.returncode != 0 or any(
            case["init_exit_code"] != 0 or case["anchor_add_exit_code"] not in (None, 0)
            for case in captured
        )
        result = {
            "schema_version": 1,
            "status": "failed" if failed else "captured",
            "client": {
                "brz": {
                    "executable": executable,
                    "version": version_text[0] if version_text else "unknown",
                },
                "platform": platform.platform(),
                "runner_python": sys.version.split()[0],
            },
            "default_rules": {
                "command": ["brz", "ignore", "--no-plugins", "--default-rules"],
                "exit_code": defaults.returncode,
                "patterns": defaults.stdout.splitlines(),
                "stderr": defaults.stderr,
                "isolated_configuration": True,
            },
            "cases": captured,
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    boolean_cases = [case for case in result["cases"] if case["candidate_matches"] is not None]
    matches = sum(case["candidate_matches"] is True for case in boolean_cases)
    print(f"Captured {len(result['cases'])} Breezy cases: {result['status']}")
    print(f"Boolean candidates matching: {matches}/{len(boolean_cases)}")
    print(f"Capture: {output_path}")
    return 1 if result["status"] == "failed" else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("cases.json"))
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).with_name("capture.local.json")
    )
    parser.add_argument("--brz", default="brz", help="Breezy executable")
    args = parser.parse_args(argv)
    return capture(args.cases, args.output, args.brz)


if __name__ == "__main__":
    raise SystemExit(main())
