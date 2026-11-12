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

_BREEZY_API_READY = False


def _capture_profile_name(
    version_output: str,
    *,
    system: str | None = None,
    machine: str | None = None,
    python_version: tuple[int, int] | None = None,
) -> str | None:
    """Build the oracle filename used to scope profile-specific Breezy probes."""
    version_match = re.search(r"\b(\d+\.\d+(?:\.\d+)*)\b", version_output)
    if version_match is None:
        return None
    operating_system = (system or platform.system()).lower()
    operating_system = {"darwin": "macos"}.get(operating_system, operating_system)
    architecture = (machine or platform.machine()).lower()
    architecture = {"amd64": "x86_64", "x64": "x86_64"}.get(architecture, architecture)
    python_version = python_version or sys.version_info[:2]
    python_suffix = (
        "" if operating_system == "macos" else f"-py{python_version[0]}{python_version[1]}"
    )
    return f"brz-{version_match.group(1)}-{operating_system}-{architecture}{python_suffix}.json"


def _client_python_version(version_output: str) -> tuple[int, int] | None:
    """Extract the interpreter version embedded in Breezy's version report."""
    match = re.search(
        r"^\s*Python interpreter: .*\s(\d+)\.(\d+)\.\d+\s*$",
        version_output,
        re.MULTILINE,
    )
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _select_cases_for_profile(
    cases: Sequence[Mapping[str, Any]],
    capture_profile: str | None,
    python_version: tuple[int, int] | None = None,
) -> tuple[list[Mapping[str, Any]], list[dict[str, Any]]]:
    """Keep profile-scoped probes out of native profiles not named by the case."""
    selected: list[Mapping[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for case in cases:
        required_profiles = case.get("capture_profiles")
        required_python = case.get("capture_python_minimum")
        excluded_by_profile = required_profiles and capture_profile not in required_profiles
        excluded_by_python = (
            required_python
            and not excluded_by_profile
            and (python_version is None or python_version < tuple(required_python))
        )
        if excluded_by_profile or excluded_by_python:
            exclusion: dict[str, Any] = {"id": case["id"]}
            if excluded_by_profile:
                exclusion.update(
                    {
                        "required_profiles": required_profiles,
                        "current_profile": capture_profile,
                    }
                )
            if excluded_by_python:
                exclusion.update(
                    {
                        "required_python_minimum": required_python,
                        "current_python": list(python_version) if python_version else None,
                    }
                )
            excluded.append(exclusion)
        else:
            selected.append(case)
    return selected, excluded


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


def _ignored_patterns(output: str) -> dict[str, str]:
    """Extract Breezy's reported winning pattern for each ignored path."""
    patterns: dict[str, str] = {}
    for line in output.splitlines():
        match = re.match(r"^(.*?)\s{2,}(\S.*?)\s*$", line)
        if match:
            patterns.setdefault(match.group(1).strip(), match.group(2).strip())
    return patterns


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
        global _BREEZY_API_READY
        with patch.dict(os.environ, environment, clear=True):
            if not _BREEZY_API_READY:
                breezy.initialize()
                plugin.load_plugins()
                _BREEZY_API_READY = True
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
        brz_home = base / ("brz-home-explicit" if setup.get("brz_home") else "brz-home")
        if setup.get("brz_home") or os.name == "nt":
            global_ignore = brz_home / "breezy" / "ignore"
        else:
            global_ignore = config_home / "breezy" / "ignore"
        environment = {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "APPDATA": str(app_data),
            "BRZ_PLUGIN_PATH": "",
            "BRZ_LOG": os.devnull,
            "PATH": os.environ.get("PATH", ""),
            "LC_ALL": "C",
            "LANG": "C",
            "TZ": "UTC",
        }
        if os.name != "nt":
            environment["XDG_CONFIG_HOME"] = str(config_home)
        if setup.get("brz_home") or os.name == "nt":
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
        ignored_patterns = _ignored_patterns(ignored.stdout)
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
            "observed_pattern": ignored_patterns.get(query) if query is not None else None,
            "expected_winning_pattern": case.get("expected_winning_pattern"),
            "winning_pattern_matches": (
                ignored_patterns.get(query) == case["expected_winning_pattern"]
                if "expected_winning_pattern" in case
                else None
            ),
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
                "BRZ_PLUGIN_PATH": "",
                "BRZ_LOG": os.devnull,
                "PATH": os.environ.get("PATH", ""),
                "LC_ALL": "C",
                "LANG": "C",
                "TZ": "UTC",
            }
            if os.name != "nt":
                environment["XDG_CONFIG_HOME"] = str(home / ".config")
            defaults = _invoke(
                [executable, "ignore", "--no-plugins", "--default-rules"],
                cwd=home,
                environment=environment,
            )
        capture_profile = _capture_profile_name(version_text[0] if version_text else "")
        brz_python_version = _client_python_version("\n".join(version_text))
        selected_cases, excluded_cases = _select_cases_for_profile(
            cases_data["cases"], capture_profile, brz_python_version
        )
        captured = [_capture_case(case, executable) for case in selected_cases]
        expected_invalid_patterns = {
            "brz.regex-invalid-pattern",
            "brz.regex-global-inline-flag-rejected",
            "brz.regex-backreference-invalid-pattern",
        }
        failed = defaults.returncode != 0 or any(
            case["init_exit_code"] != 0
            or case["anchor_add_exit_code"] not in (None, 0)
            or case["ignored_exit_code"] != (3 if case["id"] in expected_invalid_patterns else 0)
            or case["status_exit_code"] != (3 if case["id"] in expected_invalid_patterns else 0)
            or case["candidate_matches"] is False
            or case["winning_pattern_matches"] is False
            for case in captured
        )
        result = {
            "schema_version": 1,
            "status": "failed" if failed else "captured",
            "client": {
                "brz": {
                    "executable": executable,
                    "version": version_text[0] if version_text else "unknown",
                    "python_version": list(brz_python_version) if brz_python_version else None,
                    "python_interpreter": next(
                        (line.strip() for line in version_text if "Python interpreter:" in line),
                        None,
                    ),
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
            "excluded_cases": excluded_cases,
            "cases": captured,
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    boolean_cases = [case for case in result["cases"] if case["candidate_matches"] is not None]
    matches = sum(case["candidate_matches"] is True for case in boolean_cases)
    pattern_cases = [
        case for case in result["cases"] if case["winning_pattern_matches"] is not None
    ]
    pattern_matches = sum(case["winning_pattern_matches"] is True for case in pattern_cases)
    print(f"Captured {len(result['cases'])} Breezy cases: {result['status']}")
    print(f"Boolean candidates matching: {matches}/{len(boolean_cases)}")
    print(f"Winning-pattern candidates matching: {pattern_matches}/{len(pattern_cases)}")
    print(f"Cases outside their declared capture profiles: {len(result.get('excluded_cases', []))}")
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
