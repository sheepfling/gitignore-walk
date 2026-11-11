"""Capture Sapling's versioned ignore behavior across pinned client releases."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import tempfile
from pathlib import Path
from typing import Any

_PROBES = {
    "empty/target/under-empty-ignore.tmp": "target/ rule below an empty .gitignore",
    "missing/target/under-missing-ignore.tmp": "target/ rule below a missing .gitignore",
    "nested/target/under-nested-ignore.tmp": "target/ rule below a nested empty .gitignore",
    "nested/child/local.childignore": "nested .gitignore below an empty parent ignore",
}
_EXPECTED = {
    "0.2.20261028": {"sl": [], "git": sorted(_PROBES)},
    "0.2.20261102": {"sl": sorted(_PROBES), "git": sorted(_PROBES)},
    "0.2.20261103": {"sl": sorted(_PROBES), "git": sorted(_PROBES)},
}


def _run(
    command: list[str], *, cwd: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        timeout=60,
        check=False,
    )


def _capture_mode(executable: str, version: str, mode: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"sapling-{version}-{mode}-") as temporary:
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
            "GIT_CONFIG_NOSYSTEM": "1",
            "HGPLAIN": "1",
            "SL_USER": "Oracle <oracle@example.invalid>",
            "PAGER": "cat",
        }
        for key in tuple(environment):
            if key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
                environment.pop(key)
        for key in ("GIT_CONFIG_COUNT", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
            environment.pop(key, None)

        if mode == "git":
            result = _run(["git", "init", "-q", str(root)], cwd=root, environment=environment)
            if result.returncode:
                raise RuntimeError(f"git init failed: {result.stderr.decode(errors='replace')}")
        else:
            result = _run([executable, "init", str(root)], cwd=root, environment=environment)
            if result.returncode:
                raise RuntimeError(f"sl init failed: {result.stderr.decode(errors='replace')}")

        (root / ".gitignore").write_text("target/\n", encoding="utf-8")
        (root / "nested" / "child").mkdir(parents=True)
        (root / "nested" / ".gitignore").write_text("", encoding="utf-8")
        (root / "nested" / "child" / ".gitignore").write_text("*.childignore\n", encoding="utf-8")
        (root / "empty" / "target").mkdir(parents=True)
        (root / "empty" / ".gitignore").write_text("", encoding="utf-8")
        (root / "missing" / "target").mkdir(parents=True)
        (root / "nested" / "target").mkdir()
        for relative in _PROBES:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

        status = _run(
            [executable, "status", "-iu", "--print0", "--root-relative"],
            cwd=root,
            environment=environment,
        )
        if status.returncode:
            raise RuntimeError(f"sl status failed: {status.stderr.decode(errors='replace')}")
        records = [record for record in status.stdout.split(b"\0") if record]
        ignored = sorted(
            os.fsdecode(record[2:])
            for record in records
            if len(record) >= 3 and record[:2] == b"I " and os.fsdecode(record[2:]) in _PROBES
        )
        return {
            "mode": mode,
            "query_files": sorted(_PROBES),
            "probe_purpose": _PROBES,
            "ignored": ignored,
            "expected_ignored": _EXPECTED[version][mode],
            "candidate_matches": ignored == _EXPECTED[version][mode],
            "status_stdout": status.stdout.decode(errors="replace")
            .replace(str(root), "<workspace>")
            .replace("\0", "\\0"),
            "status_stderr": status.stderr.decode(errors="replace").replace(
                str(root), "<workspace>"
            ),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sl", default="sl", help="Sapling executable")
    parser.add_argument(
        "--profile-version", choices=tuple(_EXPECTED), required=True, help="pinned behavior profile"
    )
    parser.add_argument("--output", type=Path, required=True, help="JSON capture destination")
    arguments = parser.parse_args()
    version = subprocess.run(
        [arguments.sl, "--version"], capture_output=True, text=True, check=False, timeout=30
    )
    capture = {
        "schema_version": 1,
        "status": "captured" if version.returncode == 0 else "client-error",
        "profile_version": arguments.profile_version,
        "client": version.stdout.strip() if version.returncode == 0 else None,
        "version_probe": {
            "exit_code": version.returncode,
            "stdout": version.stdout,
            "stderr": version.stderr,
        },
        "platform": platform.platform(),
        "machine": platform.machine(),
        "isolated_temporary_workspace": True,
        "cases": [],
    }
    if version.returncode == 0:
        capture["cases"] = [
            _capture_mode(arguments.sl, arguments.profile_version, mode) for mode in ("sl", "git")
        ]
    else:
        capture["conformance"] = "client-error-observed"
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(capture, indent=2) + "\n", encoding="utf-8")
    passed = sum(case["candidate_matches"] for case in capture["cases"])
    print(
        f"Sapling {arguments.profile_version} release profile: "
        f"{passed}/{len(capture['cases'])} ({capture['status']})"
    )
    print(f"Capture: {arguments.output}")
    if capture["status"] == "client-error":
        return 0
    return 0 if passed == len(capture["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
