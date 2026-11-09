"""Capture Mercurial ignore behavior in isolated disposable repositories."""

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


def _write_files(root: Path, files: Mapping[str, str], home: Path) -> None:
    for relative, content in files.items():
        if relative.startswith("<home>/"):
            base = home
            target = home / relative.removeprefix("<home>/")
        else:
            base = root
            target = root / relative
        target = target.resolve()
        try:
            target.relative_to(base.resolve())
        except ValueError as error:
            message = f"oracle fixture path escapes its temporary root: {relative}"
            raise ValueError(message) from error
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="") as stream:
            stream.write(content.replace("<home>", str(home)))


def _write_byte_files(root: Path, files: Mapping[str, str]) -> None:
    """Write hexadecimal fixture content without requiring UTF-8 decoding."""
    for relative, contents_hex in files.items():
        target = (root / relative).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError as error:
            message = f"oracle fixture path escapes its temporary root: {relative}"
            raise ValueError(message) from error
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bytes.fromhex(contents_hex))


def _write_outside_files(temporary_root: Path, files: Mapping[str, str]) -> None:
    """Write fixture files outside the repository but inside its disposable parent."""
    for relative, content in files.items():
        target = (temporary_root / relative).resolve()
        try:
            target.relative_to(temporary_root.resolve())
        except ValueError as error:
            message = f"outside fixture path escapes its temporary root: {relative}"
            raise ValueError(message) from error
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")


def _set_file_modes(root: Path, modes: Mapping[str, int]) -> None:
    """Apply POSIX-style mode bits to files in a fixture after writing them."""
    for relative, mode in modes.items():
        target = (root / relative).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError as error:
            message = f"oracle mode path escapes its temporary root: {relative}"
            raise ValueError(message) from error
        target.chmod(mode)


def _config_text(config: Mapping[str, str]) -> str:
    if not config:
        return ""
    lines = ["[ui]"]
    lines.extend(f"{key.partition('.')[-1]} = {value}" for key, value in config.items())
    return "\n".join(lines) + "\n"


def _ignored(stdout: str) -> bool | None:
    matches = re.findall(r"(?:^|\n)[^\n]+ is (not )?ignored(?:\b|$)", stdout)
    if len(matches) != 1:
        return None
    return matches[0] == ""


def _has_surrogateescaped_bytes(value: str) -> bool:
    """Return whether text contains a POSIX surrogateescape byte placeholder."""
    return any(0xDC80 <= ord(character) <= 0xDCFF for character in value)


def _query_skip_reason(
    query: str, *, native_os: str, requires_posix_permissions: bool = False
) -> str | None:
    """Explain when this host cannot reproduce a native-oracle fixture."""
    if native_os == "nt" and _has_surrogateescaped_bytes(query):
        return "Windows process arguments cannot represent POSIX undecodable path bytes"
    if native_os == "nt" and "\\" in query:
        return "Windows paths cannot represent a POSIX filename containing backslash"
    if native_os == "nt" and requires_posix_permissions:
        return "Windows file permissions cannot reproduce the POSIX unreadable-source fixture"
    return None


def _capture_case(case: Mapping[str, Any], executable: str) -> dict[str, Any]:
    query = case["query"]
    if not isinstance(query, str):
        raise TypeError(f"{case['id']}: the hg profile requires one path query")
    setup = case["setup"]
    skip_reason = _query_skip_reason(
        query, native_os=os.name, requires_posix_permissions=bool(setup.get("file_modes"))
    )
    if skip_reason is not None:
        return {
            "id": case["id"],
            "profile": case["profile"],
            "dimension": case["dimension"],
            "evidence_status": case["evidence_status"],
            "native_status": "skipped",
            "skip_reason": skip_reason,
            "expected_candidate": case.get("expected_candidate"),
            "observed_ignored": None,
            "candidate_matches": None,
            "command": [executable, "debugignore", "-v", "--", query],
            "exit_code": None,
            "result": "skipped",
        }
    with tempfile.TemporaryDirectory(prefix="gitignore-walk-hg-oracle-") as temporary:
        temp = Path(temporary)
        home = temp / "home"
        home.mkdir()
        root = (temp / "repo").resolve()
        root.mkdir()
        hg_config = temp / "hgrc"
        config = {
            key: value.replace("<home>", str(home))
            for key, value in setup.get("config", {}).items()
        }
        hg_config.write_text(_config_text(config), encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "HGRCPATH": str(hg_config),
                "HGPLAIN": "1",
                "LC_ALL": "C",
            }
        )
        init = subprocess.run(
            [executable, "init", str(root)],
            cwd=temp,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        _write_files(root, setup.get("files", {}), home)
        _write_byte_files(root, setup.get("files_bytes_hex", {}))
        _write_outside_files(temp, setup.get("outside_files", {}))
        _set_file_modes(root, setup.get("file_modes", {}))
        for relative, target in setup.get("symlinks", {}).items():
            link = root / relative
            if Path(relative).is_absolute() or ".." in Path(relative).parts:
                raise ValueError(f"oracle symlink path escapes its temporary root: {relative}")
            link.parent.mkdir(parents=True, exist_ok=True)
            try:
                link.symlink_to(target)
            except OSError as error:
                return {
                    "id": case["id"],
                    "profile": case["profile"],
                    "dimension": case["dimension"],
                    "evidence_status": case["evidence_status"],
                    "native_status": "skipped",
                    "skip_reason": f"Unable to create fixture symlink: {error}",
                    "expected_candidate": case.get("expected_candidate"),
                    "observed_ignored": None,
                    "candidate_matches": None,
                    "command": [executable, "debugignore", "-v", "--", query],
                    "exit_code": None,
                    "result": "skipped",
                }
        config_capture = None
        if case.get("policy_mode") == "client-config":
            config_result = subprocess.run(
                [executable, "config", "--debug", "ui"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            config_stdout = (
                config_result.stdout.replace(str(root), "<repo>")
                .replace(str(home), "<home>")
                .replace(str(hg_config), "<hgrc>")
            )
            config_stderr = (
                config_result.stderr.replace(str(root), "<repo>")
                .replace(str(home), "<home>")
                .replace(str(hg_config), "<hgrc>")
            )
            config_capture = {
                "command": [executable, "config", "--debug", "ui"],
                "exit_code": config_result.returncode,
                "stdout": config_stdout,
                "stderr": config_stderr,
                "normalized_stdout_sha256": hashlib.sha256(
                    config_stdout.encode("utf-8", errors="surrogatepass")
                ).hexdigest(),
            }
        command = [executable, "debugignore", "-v", "--", query]
        result = subprocess.run(
            command,
            cwd=root,
            env=env,
            text=True,
            errors="surrogateescape",
            capture_output=True,
            check=False,
            timeout=30,
        )
        raw_stdout, raw_stderr = result.stdout, result.stderr
        normalized_stdout = raw_stdout.replace(str(root), "<repo>").replace(str(home), "<home>")
        normalized_stderr = raw_stderr.replace(str(root), "<repo>").replace(str(home), "<home>")
        observed = _ignored(normalized_stdout)
        expected = case.get("expected_candidate")
        candidate = expected.get("ignored") if isinstance(expected, dict) else expected
        matches_candidate = observed == candidate if isinstance(candidate, bool) else None
        return {
            "id": case["id"],
            "profile": case["profile"],
            "dimension": case["dimension"],
            "evidence_status": case["evidence_status"],
            "native_status": "captured",
            "expected_candidate": expected,
            "observed_ignored": observed,
            "candidate_matches": matches_candidate,
            "command": command,
            "working_directory": "<repo>",
            "environment": {
                "HGRCPATH": "<temp>/hgrc",
                "HGPLAIN": "1",
                "LC_ALL": "C",
            },
            "init_exit_code": init.returncode,
            "init_stdout": init.stdout.replace(str(root), "<repo>"),
            "init_stderr": init.stderr.replace(str(root), "<repo>"),
            "exit_code": result.returncode,
            "result": (
                "ignored"
                if observed is True
                else "not-ignored"
                if observed is False
                else "command-error-or-unparsed"
            ),
            "stdout": normalized_stdout,
            "stderr": normalized_stderr,
            "configuration": config_capture,
            "normalized_stdout_sha256": hashlib.sha256(
                normalized_stdout.encode("utf-8", errors="surrogateescape")
            ).hexdigest(),
            "normalized_stderr_sha256": hashlib.sha256(
                normalized_stderr.encode("utf-8", errors="surrogateescape")
            ).hexdigest(),
            "raw_stdout": raw_stdout,
            "raw_stderr": raw_stderr,
        }


def capture(cases_path: Path, output_path: Path, hg_executable: str) -> int:
    cases_data = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = [case for case in cases_data["cases"] if case["profile"] == "hg"]
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
    captured = [_capture_case(case, executable) for case in cases]
    any_init_failures = _has_init_failures(captured)
    version_lines = version.stdout.splitlines()
    with tempfile.TemporaryDirectory(prefix="gitignore-walk-hg-profile-") as profile_temp:
        profile_root = Path(profile_temp)
        profile_home = profile_root / "home"
        profile_home.mkdir()
        profile_config = profile_root / "hgrc"
        profile_config.write_text("", encoding="utf-8")
        profile = subprocess.run(
            [executable, "debuginstall"],
            env={
                **os.environ,
                "HOME": str(profile_home),
                "HGRCPATH": str(profile_config),
                "HGPLAIN": "1",
                "LC_ALL": "C",
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    runtime_match = re.search(r"checking Python version \(([^)]+)\)", profile.stdout)
    result = {
        "schema_version": 1,
        "status": "failed" if any_init_failures else "captured",
        "client": {
            "executable": executable,
            "version": version_lines[0] if version_lines else "unknown",
            "runtime": runtime_match.group(1) if runtime_match else None,
            "platform": platform.platform(),
            "runner_python": sys.version.split()[0],
        },
        "cases": captured,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Captured {len(captured)} Mercurial cases: {result['status']}")
    print(
        "Boolean candidates matching observations: "
        f"{sum(case['candidate_matches'] is True for case in captured)}"
    )
    print(
        "Boolean candidates differing from observations: "
        f"{sum(case['candidate_matches'] is False for case in captured)}"
    )
    print(f"Open candidates: {sum(case['candidate_matches'] is None for case in captured)}")
    print(f"Nonzero query exits: {sum(case['exit_code'] not in (None, 0) for case in captured)}")
    print(f"Skipped cases: {sum(case['native_status'] == 'skipped' for case in captured)}")
    print(f"Capture: {output_path}")
    return 1 if any_init_failures else 0


def _has_init_failures(captured: Sequence[Mapping[str, Any]]) -> bool:
    """Return whether a non-skipped fixture failed to initialize its repository."""
    return any(
        case.get("init_exit_code", 0) != 0
        for case in captured
        if case.get("native_status") != "skipped"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("cases.json"))
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).with_name("capture.local.json")
    )
    parser.add_argument("--hg", default="hg", help="Mercurial executable")
    args = parser.parse_args(argv)
    return capture(args.cases, args.output, args.hg)


if __name__ == "__main__":
    raise SystemExit(main())
