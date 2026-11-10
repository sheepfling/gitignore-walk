"""Probe Sapling and Jujutsu ignore behavior in disposable repositories."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _run(
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


def _capture_sapling(executable: str, mode: str, fixture: Mapping[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"gitignore-walk-sapling-{mode}-") as temporary:
        base = Path(temporary)
        home = base / "home"
        home.mkdir()
        root = base / "workspace"
        root.mkdir()
        environment = {
            **os.environ,
            "HOME": str(home),
            "USERPROFILE": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "SL_USER": "Oracle <oracle@example.invalid>",
            "PAGER": "cat",
            "HGPLAIN": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        if mode == "git":
            _require_success(
                _run(["git", "init", "-q", str(root)], cwd=root, environment=environment),
                "git init",
            )
        else:
            _require_success(
                _run([executable, "init", str(root)], cwd=root, environment=environment), "sl init"
            )
        _write_files(root, fixture["probe_files"])
        _write_source_probes(root, home, fixture)
        status = _run([executable, "status", "-iu", "--print0"], cwd=root, environment=environment)
        _require_success(status, "sl status")
        included, ignored = _sapling_status_paths(status.stdout)
        source_query_files = set(fixture["source_query_files"])
        source_ignored = sorted(ignored & source_query_files)
        pattern_query_files = set(fixture["pattern_query_files"])
        _write_pattern_probes(root, fixture)
        pattern_status = _run(
            [executable, "status", "-iu", "--print0"], cwd=root, environment=environment
        )
        _require_success(pattern_status, "sl status pattern probes")
        _, pattern_status_ignored = _sapling_status_paths(pattern_status.stdout)
        pattern_ignored = _expand_ignored_paths(pattern_status_ignored, pattern_query_files)
        return {
            "id": f"sapling.{mode}-mode",
            "vcs": "sapling",
            "mode": mode,
            "version": _version(executable),
            "included": sorted(included & set(fixture["query_files"])),
            "ignored": sorted(ignored & set(fixture["query_files"])),
            "status_exit_code": status.returncode,
            "status_stdout": status.stdout.replace(str(root), "<workspace>"),
            "status_stderr": status.stderr.replace(str(root), "<workspace>"),
            "metadata_markers": sorted(
                marker for marker in (".git", ".sl") if (root / marker).exists()
            ),
            "isolated_temporary_workspace": True,
            "source_discovery": {
                "query_files": sorted(source_query_files),
                "ignored": source_ignored,
                "included": sorted(source_query_files - set(source_ignored)),
            },
            "pattern_discovery": {
                "query_files": sorted(pattern_query_files),
                "ignored": sorted(pattern_ignored),
                "included": sorted(pattern_query_files - pattern_ignored),
                "status_stdout": pattern_status.stdout.replace(str(root), "<workspace>"),
                "status_stderr": pattern_status.stderr.replace(str(root), "<workspace>"),
            },
        }


def _capture_jj(executable: str, mode: str, fixture: Mapping[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"gitignore-walk-jj-{mode}-") as temporary:
        base = Path(temporary)
        home = base / "home"
        home.mkdir()
        config_dir = home / ".config" / "jj"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text(
            '[user]\nname = "Oracle"\nemail = "oracle@example.invalid"\n',
            encoding="utf-8",
        )
        root = base / "workspace"
        root.mkdir()
        environment = {
            **os.environ,
            "HOME": str(home),
            "USERPROFILE": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "PAGER": "cat",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        command = [executable, "git", "init"]
        if mode == "noncolocated":
            command.append("--no-colocate")
        command.append(str(root))
        _require_success(_run(command, cwd=root, environment=environment), "jj git init")
        _write_files(root, fixture["probe_files"])
        _write_source_probes(root, home, fixture)
        status = _run([executable, "status", "--no-pager"], cwd=root, environment=environment)
        _require_success(status, "jj status")
        listed = _run([executable, "file", "list"], cwd=root, environment=environment)
        _require_success(listed, "jj file list")
        files = {line.strip() for line in listed.stdout.splitlines() if line.strip()}
        query_files = set(fixture["query_files"])
        source_query_files = set(fixture["source_query_files"])
        source_ignored = sorted(source_query_files - files)
        pattern_query_files = set(fixture["pattern_query_files"])
        _write_pattern_probes(root, fixture)
        pattern_status = _run(
            [executable, "status", "--no-pager"], cwd=root, environment=environment
        )
        _require_success(pattern_status, "jj status pattern probes")
        pattern_listed = _run([executable, "file", "list"], cwd=root, environment=environment)
        _require_success(pattern_listed, "jj file list pattern probes")
        pattern_files = {
            line.strip() for line in pattern_listed.stdout.splitlines() if line.strip()
        }
        pattern_ignored = pattern_query_files - pattern_files
        return {
            "id": f"jj.{mode}",
            "vcs": "jujutsu",
            "mode": mode,
            "version": _version(executable),
            "included": sorted(files & query_files),
            "ignored": sorted(query_files - files),
            "status_exit_code": status.returncode,
            "status_stdout": status.stdout.replace(str(root), "<workspace>"),
            "status_stderr": status.stderr.replace(str(root), "<workspace>"),
            "metadata_markers": sorted(
                marker for marker in (".git", ".jj") if (root / marker).exists()
            ),
            "isolated_temporary_workspace": True,
            "status_snapshots_disposable_workspace": True,
            "source_discovery": {
                "query_files": sorted(source_query_files),
                "ignored": source_ignored,
                "included": sorted(source_query_files - set(source_ignored)),
            },
            "pattern_discovery": {
                "query_files": sorted(pattern_query_files),
                "ignored": sorted(pattern_ignored),
                "included": sorted(pattern_query_files - pattern_ignored),
                "status_stdout": pattern_status.stdout.replace(str(root), "<workspace>"),
                "status_stderr": pattern_status.stderr.replace(str(root), "<workspace>"),
                "file_list_stdout": pattern_listed.stdout.replace(str(root), "<workspace>"),
            },
        }


def _write_source_probes(root: Path, home: Path, fixture: Mapping[str, Any]) -> None:
    """Seed isolated Git-style global and per-clone ignore sources."""
    _write_files(root, fixture["source_probe_files"])
    xdg_ignore = home / ".config" / "git" / "ignore"
    xdg_ignore.parent.mkdir(parents=True, exist_ok=True)
    xdg_ignore.write_text(fixture["source_rules"]["xdg_git_ignore"], encoding="utf-8")
    git_dir = root / ".git"
    if git_dir.is_dir():
        info_dir = git_dir / "info"
        info_dir.mkdir(exist_ok=True)
        (info_dir / "exclude").write_text(
            fixture["source_rules"]["git_info_exclude"], encoding="utf-8"
        )


def _write_pattern_probes(root: Path, fixture: Mapping[str, Any]) -> None:
    """Add a path matrix for negation, directory barriers, anchoring, and ``**``."""
    _write_files(root, fixture["pattern_probe_files"])
    (root / ".gitignore").write_text(fixture["pattern_rules"], encoding="utf-8")


def _expand_ignored_paths(ignored: set[str], query_files: set[str]) -> set[str]:
    """Expand native ignored-directory summaries to the fixture's queried files."""
    normalized = {path.rstrip("/") for path in ignored}
    return {
        path
        for path in query_files
        if path in normalized or any(path.startswith(prefix + "/") for prefix in normalized)
    }


def _sapling_status_paths(output: str) -> tuple[set[str], set[str]]:
    included: set[str] = set()
    ignored: set[str] = set()
    for line in output.split("\0"):
        if len(line) < 3 or line[1] != " ":
            continue
        path = line[2:].removeprefix("./")
        if line[0] == "I":
            ignored.add(path)
        elif line[0] in ("?", "A", "M", "R"):
            included.add(path)
    return included, ignored


def _write_files(root: Path, files: Mapping[str, str]) -> None:
    for relative, contents in files.items():
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as error:
            raise ValueError(f"fixture path escapes temporary workspace: {relative}") from error
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as stream:
            stream.write(contents)


def _version(executable: str) -> str:
    result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"unable to get version for {executable}: {result.stderr.strip()}")
    return result.stdout.strip()


def _require_success(result: subprocess.CompletedProcess[str], operation: str) -> None:
    if result.returncode != 0:
        raise RuntimeError(f"{operation} failed: {result.stderr.strip() or result.stdout.strip()}")


def capture(sapling: str, jj: str) -> dict[str, Any]:
    fixture = json.loads(Path(__file__).with_name("cases.json").read_text(encoding="utf-8"))
    client_versions = {"sapling": _version(sapling), "jujutsu": _version(jj)}
    captures = [_capture_sapling(sapling, mode, fixture) for mode in ("git", "sl")] + [
        _capture_jj(jj, mode, fixture) for mode in ("colocated", "noncolocated")
    ]
    expected_included = sorted(fixture["expected_included"])
    expected_ignored = sorted(fixture["expected_ignored"])
    for result in captures:
        result["candidate_matches"] = (
            result["included"] == expected_included and result["ignored"] == expected_ignored
        )
        result["source_discovery"]["candidate_matches"] = (
            result["source_discovery"]["ignored"]
            == fixture["expected_source_ignored"][result["id"]]
        )
        result["pattern_discovery"]["candidate_matches"] = (
            result["pattern_discovery"]["ignored"] == fixture["expected_pattern_ignored"]
        )
    return {
        "schema_version": 1,
        "status": "captured",
        "platform": platform.platform(),
        "clients": client_versions,
        "cases": captures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sl", default="sl", help="Sapling executable")
    parser.add_argument("--jj", default="jj", help="Jujutsu executable")
    parser.add_argument("--output", type=Path, required=True, help="capture JSON destination")
    arguments = parser.parse_args()
    result = capture(arguments.sl, arguments.jj)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    matched = sum(
        case["candidate_matches"]
        and case["source_discovery"]["candidate_matches"]
        and case["pattern_discovery"]["candidate_matches"]
        for case in result["cases"]
    )
    print(f"Captured {len(result['cases'])} Sapling/Jujutsu cases")
    print(f"Ignore, source, and path-pattern candidates matching: {matched}/{len(result['cases'])}")
    print(f"Capture: {arguments.output}")
    return 0 if matched == len(result["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
