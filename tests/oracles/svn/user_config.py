"""Capture ambient per-user Subversion ignore configuration in an isolated working copy."""

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


def capture(
    output: Path, *, svn_name: str = "svn", svnadmin_name: str = "svnadmin"
) -> dict[str, Any]:
    """Capture native and policy behavior for one ambient user config file."""
    if os.name == "nt":
        raise RuntimeError("this profile uses the POSIX HOME/.subversion/config location")
    svn = shutil.which(svn_name)
    svnadmin = shutil.which(svnadmin_name)
    if svn is None or svnadmin is None:
        raise FileNotFoundError("svn and svnadmin are required")

    with tempfile.TemporaryDirectory(prefix="gitignore-walk-svn-user-config-") as temporary:
        root = Path(temporary)
        home = root / "home"
        user_config = home / ".subversion" / "config"
        user_config.parent.mkdir(parents=True)
        user_config.write_text(
            "[miscellany]\nglobal-ignores = *.user-config-hide\n", encoding="utf-8"
        )
        environment = {
            **os.environ,
            "HOME": str(home),
            "LC_ALL": "C",
            "LANG": "C",
        }
        repository = root / "repository"
        working_copy = root / "working-copy"
        _run([svnadmin, "create", str(repository)], cwd=root, environment=environment)
        url = repository.as_uri() + "/trunk"
        _run([svn, "mkdir", url, "-m", "initialize"], cwd=root, environment=environment)
        _run([svn, "checkout", url, str(working_copy)], cwd=root, environment=environment)
        for name in ("candidate.user-config-hide", "visible.user-config-show"):
            (working_copy / name).write_text(name, encoding="utf-8")

        command = [svn, "status", "--xml", "--no-ignore", "."]
        native = subprocess.run(
            command,
            cwd=working_copy,
            env=environment,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if native.returncode != 0:
            raise RuntimeError(
                "svn status failed: " + native.stderr.decode("utf-8", errors="replace")
            )
        document = ET.fromstring(native.stdout)
        native_ignored = sorted(
            entry.attrib["path"].replace("\\", "/")
            for entry in document.findall("./target/entry")
            if (status := entry.find("wc-status")) is not None
            and status.attrib.get("item") == "ignored"
        )
        policy = SubversionIgnorePolicy(working_copy, environment=environment)
        candidates = ("candidate.user-config-hide", "visible.user-config-show")
        policy_ignored = sorted(name for name in candidates if policy.is_ignored(name))
        decision = policy.trace("candidate.user-config-hide").decision
        policy_source = (decision.source or "").replace(str(home), "<isolated-home>")
        expected = ["candidate.user-config-hide"]
        normalized_xml = ET.canonicalize(
            xml_data=native.stdout.decode("utf-8", errors="replace").replace(
                str(working_copy), "<working-copy>"
            )
        )
        version = _run([svn, "--version", "--quiet"], cwd=root, environment=environment)
        result = {
            "schema_version": 1,
            "status": "captured",
            "client": {
                "svn_version": version.decode("utf-8", errors="replace").strip(),
                "platform": platform.platform(),
            },
            "user_config": "<isolated-home>/.subversion/config",
            "user_config_sha256": hashlib.sha256(user_config.read_bytes()).hexdigest(),
            "pattern": "*.user-config-hide",
            "native_status_command": ["svn", "status", "--xml", "--no-ignore", "."],
            "native_status_exit_code": native.returncode,
            "native_status_xml": normalized_xml,
            "native_status_stdout_sha256": hashlib.sha256(
                normalized_xml.encode("utf-8")
            ).hexdigest(),
            "expected_ignored_paths": expected,
            "native_ignored_paths": native_ignored,
            "policy_ignored_paths": policy_ignored,
            "policy_source": policy_source,
            "candidate_matches": (
                native_ignored == expected
                and policy_ignored == expected
                and policy_source
                == "Subversion runtime configuration: <isolated-home>/.subversion/config"
                and decision.discovery_complete
            ),
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--svn", default="svn")
    parser.add_argument("--svnadmin", default="svnadmin")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    result = capture(arguments.output, svn_name=arguments.svn, svnadmin_name=arguments.svnadmin)
    return 0 if result["candidate_matches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
