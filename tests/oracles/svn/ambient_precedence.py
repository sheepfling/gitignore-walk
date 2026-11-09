"""Capture native Subversion system-versus-user global-ignore precedence.

Run only in an isolated Linux container with the fixture system config at
``/etc/subversion/config``. The runner refuses to run unless that file contains the expected marker,
so it cannot silently test the host's ambient configuration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from gitignore_walk import SubversionIgnorePolicy

SYSTEM_CONFIG = Path("/etc/subversion/config")
SYSTEM_MARKER = "global-ignores = *.system-only-hide"


def _run(command: Sequence[str], *, cwd: Path, environment: dict[str, str]) -> bytes:
    result = subprocess.run(
        list(command), cwd=cwd, env=environment, capture_output=True, check=False, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {command!r}\n"
            f"stdout={result.stdout.decode(errors='replace')}\n"
            f"stderr={result.stderr.decode(errors='replace')}"
        )
    return result.stdout


def capture(output: Path) -> dict[str, Any]:
    if os.name == "nt":
        raise RuntimeError("this ambient system-config fixture is Linux-only")
    system_config = SYSTEM_CONFIG.read_text(encoding="utf-8")
    if SYSTEM_MARKER not in system_config:
        raise RuntimeError(
            f"{SYSTEM_CONFIG} must be the isolated fixture containing {SYSTEM_MARKER!r}"
        )
    svn = shutil.which("svn")
    svnadmin = shutil.which("svnadmin")
    if svn is None or svnadmin is None:
        raise FileNotFoundError("svn and svnadmin are required")

    with tempfile.TemporaryDirectory(prefix="gitignore-walk-svn-ambient-") as temporary:
        root = Path(temporary)
        home = root / "home"
        user_config = home / ".subversion" / "config"
        user_config.parent.mkdir(parents=True)
        user_config.write_text(
            "[miscellany]\nglobal-ignores = *.user-only-hide\n", encoding="utf-8"
        )
        environment = {"HOME": str(home), "LC_ALL": "C", "LANG": "C", "PATH": os.environ["PATH"]}
        repository = root / "repository"
        working_copy = root / "working-copy"
        _run([svnadmin, "create", str(repository)], cwd=root, environment=environment)
        url = repository.as_uri() + "/trunk"
        _run([svn, "mkdir", url, "-m", "initialize"], cwd=root, environment=environment)
        _run([svn, "checkout", url, str(working_copy)], cwd=root, environment=environment)
        for name in ("candidate.system-only-hide", "candidate.user-only-hide", "visible"):
            (working_copy / name).write_text(name, encoding="utf-8")

        status_command = [svn, "status", "--xml", "--no-ignore", "."]
        status = subprocess.run(
            status_command,
            cwd=working_copy,
            env=environment,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if status.returncode != 0:
            raise RuntimeError(
                "svn status failed: " + status.stderr.decode("utf-8", errors="replace")
            )
        document = ET.fromstring(status.stdout)
        ignored = sorted(
            entry.attrib["path"].replace("\\", "/")
            for entry in document.findall(".//entry")
            if (item := entry.find("wc-status")) is not None
            and item.attrib.get("item") == "ignored"
        )
        policy = SubversionIgnorePolicy(working_copy, environment=environment)
        policy_ignored = sorted(
            name
            for name in ("candidate.system-only-hide", "candidate.user-only-hide")
            if policy.is_ignored(name)
        )
        expected = ["candidate.user-only-hide"]
        policy_source = policy.trace("candidate.user-only-hide").decision.source
        if policy_source == f"Subversion runtime configuration: {user_config}":
            policy_source = "Subversion runtime configuration: <isolated-home>/.subversion/config"
        version = (
            subprocess.run(
                [svn, "--version", "--quiet"], capture_output=True, check=True, timeout=10
            )
            .stdout.decode()
            .strip()
        )
        result = {
            "schema_version": 1,
            "status": "captured",
            "client": {"svn_version": version, "platform": platform.platform()},
            "system_config": str(SYSTEM_CONFIG),
            "system_config_sha256": hashlib.sha256(system_config.encode()).hexdigest(),
            "system_pattern": "*.system-only-hide",
            "user_config": "<isolated-home>/.subversion/config",
            "user_config_sha256": hashlib.sha256(user_config.read_bytes()).hexdigest(),
            "user_pattern": "*.user-only-hide",
            "native_status_command": ["svn", *status_command[1:]],
            "native_status_exit_code": status.returncode,
            "native_status_stdout": status.stdout.decode("utf-8", errors="replace").replace(
                str(working_copy), "<working-copy>"
            ),
            "native_status_stderr": status.stderr.decode("utf-8", errors="replace"),
            "native_status_stdout_sha256": hashlib.sha256(
                status.stdout.decode("utf-8", errors="replace")
                .replace(str(working_copy), "<working-copy>")
                .encode()
            ).hexdigest(),
            "expected_ignored_paths": expected,
            "native_ignored_paths": ignored,
            "policy_ignored_paths": policy_ignored,
            "policy_source": policy_source,
            "candidate_matches": ignored == expected and policy_ignored == expected,
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    result = capture(arguments.output)
    return 0 if result["candidate_matches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
