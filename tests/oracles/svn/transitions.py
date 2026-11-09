"""Capture Subversion working-copy membership across native status transitions."""

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
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

EXPECTED_STATUS_ITEMS = {
    "normal.tmp": "normal",
    "modified.tmp": "modified",
    "added.tmp": "added",
    "deleted.tmp": "deleted",
    "missing.tmp": "missing",
    "replaced.tmp": "replaced",
    "obstructed.tmp": "obstructed",
    "conflicted.tmp": "conflicted",
    "loose.tmp": "ignored",
}


def _run(
    command: list[str], *, cwd: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess[bytes]:
    """Run one bounded native command and surface fixture setup failures."""
    result = subprocess.run(
        command, cwd=cwd, env=environment, capture_output=True, timeout=60, check=False
    )
    if result.returncode:
        raise RuntimeError(
            f"Subversion fixture command failed ({result.returncode}): {command!r}\n"
            f"stdout={result.stdout.decode(errors='replace')}\n"
            f"stderr={result.stderr.decode(errors='replace')}"
        )
    return result


def _capture_status(svn: str, svnadmin: str) -> dict[str, Any]:
    """Create a disposable repository, produce status states, and capture native XML."""
    with tempfile.TemporaryDirectory(prefix="gitignore-walk-svn-transitions-") as directory:
        temporary = Path(directory)
        repository = temporary / "repository"
        root = temporary / "working-copy"
        other = temporary / "other-working-copy"
        config_dir = temporary / "config"
        home = temporary / "home"
        config_dir.mkdir()
        home.mkdir()
        environment = {
            name: os.environ[name]
            for name in ("PATH", "SystemRoot", "WINDIR")
            if name in os.environ
        }
        environment.update(
            {
                "HOME": str(home),
                "LC_ALL": "C",
                "LANG": "C",
                "TEMP": str(temporary),
                "TMP": str(temporary),
                "USERPROFILE": str(home),
            }
        )
        if os.name == "nt":
            roaming = home / "AppData" / "Roaming"
            local = home / "AppData" / "Local"
            roaming.mkdir(parents=True)
            local.mkdir(parents=True)
            environment.update({"APPDATA": str(roaming), "LOCALAPPDATA": str(local)})
        (config_dir / "config").write_text("[miscellany]\nglobal-ignores =\n", encoding="utf-8")
        svn_prefix = [svn, "--config-dir", str(config_dir)]
        _run([svnadmin, "create", str(repository)], cwd=temporary, environment=environment)
        repository_url = repository.as_uri()
        trunk_url = f"{repository_url}/trunk"
        _run(
            [*svn_prefix, "mkdir", trunk_url, "-m", "initialize transition fixture"],
            cwd=temporary,
            environment=environment,
        )
        _run(
            [*svn_prefix, "checkout", trunk_url, str(root)],
            cwd=temporary,
            environment=environment,
        )
        initial_files = {
            "normal.tmp": "normal\n",
            "modified.tmp": "before\n",
            "deleted.tmp": "deleted\n",
            "missing.tmp": "missing\n",
            "replaced.tmp": "replaced\n",
            "obstructed.tmp": "obstructed\n",
            "conflicted.tmp": "base\n",
        }
        for name, content in initial_files.items():
            (root / name).write_text(content, encoding="utf-8")
        _run([*svn_prefix, "add", "--force", "."], cwd=root, environment=environment)
        ignore_file = temporary / "svn-ignore.txt"
        ignore_file.write_text("*.tmp\n", encoding="utf-8")
        _run(
            [*svn_prefix, "propset", "svn:ignore", "--file", str(ignore_file), "."],
            cwd=root,
            environment=environment,
        )
        _run(
            [*svn_prefix, "commit", "-m", "commit transition fixture", "."],
            cwd=root,
            environment=environment,
        )

        (root / "modified.tmp").write_text("after\n", encoding="utf-8")
        (root / "added.tmp").write_text("added after checkout\n", encoding="utf-8")
        _run([*svn_prefix, "add", "added.tmp"], cwd=root, environment=environment)
        for name in ("deleted.tmp", "replaced.tmp"):
            _run([*svn_prefix, "delete", "--keep-local", name], cwd=root, environment=environment)
        _run([*svn_prefix, "add", "replaced.tmp"], cwd=root, environment=environment)

        repository_url = (
            _run([svn, "info", "--show-item", "url", "."], cwd=root, environment=environment)
            .stdout.decode("utf-8")
            .strip()
        )
        _run(
            [*svn_prefix, "checkout", repository_url, str(other)],
            cwd=temporary,
            environment=environment,
        )
        (other / "conflicted.tmp").write_text("theirs\n", encoding="utf-8")
        _run(
            [*svn_prefix, "commit", "-m", "create conflict", "conflicted.tmp"],
            cwd=other,
            environment=environment,
        )
        (root / "conflicted.tmp").write_text("ours\n", encoding="utf-8")
        _run(
            [*svn_prefix, "update", "--accept", "postpone", "."],
            cwd=root,
            environment=environment,
        )
        (root / "missing.tmp").unlink()
        (root / "obstructed.tmp").unlink()
        (root / "obstructed.tmp").mkdir()
        (root / "obstructed.tmp" / "child.txt").write_text("obstructed child\n", encoding="utf-8")
        (root / "loose.tmp").write_text("ignored unversioned file\n", encoding="utf-8")

        command = [
            *svn_prefix,
            "status",
            "--xml",
            "--verbose",
            "--no-ignore",
            "--depth",
            "infinity",
            ".",
        ]
        status = _run(command, cwd=root, environment=environment)
        document = ET.fromstring(status.stdout)
        observed: dict[str, str] = {}
        for entry in document.findall("./target/entry"):
            wc_status = entry.find("wc-status")
            if wc_status is not None:
                observed[entry.attrib["path"].replace("\\", "/")] = wc_status.attrib["item"]
        actual = {name: observed.get(name) for name in EXPECTED_STATUS_ITEMS}
        normalized_stdout = status.stdout.decode("utf-8", errors="replace").replace(
            str(root), "<working-copy>"
        )
        return {
            "id": "svn.status-membership-transitions",
            "dimension": "working-copy-status-membership",
            "native_status": "captured",
            "expected_status_items": EXPECTED_STATUS_ITEMS,
            "observed_status_items": actual,
            "candidate_matches": actual == EXPECTED_STATUS_ITEMS,
            "command": [
                svn,
                "--config-dir",
                "<config>",
                "status",
                "--xml",
                "--verbose",
                "--no-ignore",
                "--depth",
                "infinity",
                ".",
            ],
            "environment": {
                "HOME": "<isolated-home>",
                "LC_ALL": "C",
                "LANG": "C",
                "config_dir": "<isolated-config>",
            },
            "exit_code": status.returncode,
            "normalized_stdout_sha256": hashlib.sha256(normalized_stdout.encode()).hexdigest(),
            "raw_stdout": status.stdout.decode("utf-8", errors="replace"),
            "normalized_stdout": normalized_stdout,
            "stderr": status.stderr.decode("utf-8", errors="replace"),
        }


def main(argv: list[str] | None = None) -> int:
    """Write a native status-transition capture for one installed Subversion profile."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--svn", default="svn", help="Subversion executable")
    parser.add_argument("--svnadmin", default="svnadmin", help="svnadmin executable")
    parser.add_argument("--output", type=Path, required=True, help="transition capture path")
    arguments = parser.parse_args(argv)
    svn = shutil.which(arguments.svn)
    svnadmin = shutil.which(arguments.svnadmin)
    if svn is None or svnadmin is None:
        print("svn and svnadmin must both be available on PATH", file=sys.stderr)
        return 2
    try:
        version = _run(
            [svn, "--version", "--quiet"],
            cwd=Path.cwd(),
            environment={"PATH": os.environ.get("PATH", "")},
        ).stdout
        admin_version = _run(
            [svnadmin, "--version", "--quiet"],
            cwd=Path.cwd(),
            environment={"PATH": os.environ.get("PATH", "")},
        ).stdout
        case = _capture_status(svn, svnadmin)
    except (ET.ParseError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"Subversion status-transition capture failed: {error}", file=sys.stderr)
        return 1
    result = {
        "schema_version": 1,
        "status": "captured" if case["candidate_matches"] else "failed",
        "client": {
            "svn": {"executable": svn, "version": version.decode().strip()},
            "svnadmin": {"executable": svnadmin, "version": admin_version.decode().strip()},
            "platform": platform.platform(),
            "runner_python": sys.version.split()[0],
        },
        "cases": [case],
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        "Subversion status transitions: "
        f"{'matched' if case['candidate_matches'] else 'differed'} "
        f"({result['client']['svn']['version']})"
    )
    print(f"Capture: {arguments.output}")
    return 0 if case["candidate_matches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
