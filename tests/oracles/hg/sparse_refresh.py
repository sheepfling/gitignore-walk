"""Capture Mercurial sparse-refresh failures and the resulting membership state."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from gitignore_walk import MercurialIgnorePolicy


def _run(
    executable: str,
    arguments: Sequence[str],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[bytes]:
    """Run one isolated Mercurial command with a bounded timeout."""
    return subprocess.run(
        [executable, *arguments],
        cwd=cwd,
        env=environment,
        capture_output=True,
        check=False,
        timeout=30,
    )


def _status_records(output: bytes) -> dict[str, str]:
    """Decode Mercurial's NUL-delimited status records."""
    records: dict[str, str] = {}
    for record in output.split(b"\0"):
        if not record:
            continue
        if len(record) < 3 or record[1:2] != b" ":
            raise ValueError(f"Mercurial returned an invalid status record: {record!r}")
        path = os.fsdecode(record[2:]).replace("\\", "/")
        records[path] = record[:1].decode("ascii")
    return records


def _membership_from_status(code: str | None) -> str | None:
    """Translate one captured status code into the policy's public membership value."""
    if code in {"C", "M", "A", "R", "!"}:
        return "versioned"
    if code in {"?", "I"}:
        return "unversioned"
    return None


def capture(hg: str, output: Path) -> int:
    """Record native status before and after manually editing an active sparse rule."""
    executable = shutil.which(hg)
    if executable is None:
        print(f"Mercurial executable not found: {hg}")
        return 2

    with tempfile.TemporaryDirectory(prefix="hg-sparse-refresh-") as temporary:
        base = Path(temporary)
        root = base / "repo"
        root.mkdir()
        home = base / "home"
        home.mkdir()
        hgrc = base / "hgrc"
        hgrc.write_text("[extensions]\nsparse =\n", encoding="utf-8")
        environment = os.environ.copy()
        environment.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "HGRCPATH": str(hgrc),
                "HGPLAIN": "1",
                "LC_ALL": "C",
            }
        )

        def run(*arguments: str) -> subprocess.CompletedProcess[bytes]:
            return _run(executable, arguments, cwd=root, environment=environment)

        initial = run("init")
        if initial.returncode != 0:
            raise RuntimeError(initial.stderr.decode(errors="replace"))
        tracked_path = root / "two" / "b.txt"
        tracked_path.parent.mkdir()
        tracked_path.write_text("tracked before sparse exclusion\n", encoding="utf-8")
        for command_result in (
            run("add", "two/b.txt"),
            run("commit", "-m", "sparse refresh probe", "-u", "gitignore-walk oracle"),
            run("debugsparse", "--exclude", "glob:two/**"),
        ):
            if command_result.returncode != 0:
                raise RuntimeError(command_result.stderr.decode(errors="replace"))

        before_status = run("status", "--all", "--unknown", "--ignored", "-0")
        if before_status.returncode != 0:
            raise RuntimeError(before_status.stderr.decode(errors="replace"))
        before_records = _status_records(before_status.stdout)
        policy = MercurialIgnorePolicy(
            root,
            hg_executable=executable,
            membership_aware=True,
            environment=environment,
        )
        before_decision = policy.explain("two/b.txt")
        sparse_file = root / ".hg" / "sparse"
        sparse_content = sparse_file.read_text(encoding="utf-8")
        rule = "glob:two/**\n"
        if rule not in sparse_content or tracked_path.exists():
            raise RuntimeError("native sparse exclusion did not remove the probe file")
        sparse_file.write_text(sparse_content.replace(rule, "", 1), encoding="utf-8")

        refresh = run("debugsparse", "--refresh")
        status = run("status", "--all", "--unknown", "--ignored", "-0")
        if status.returncode != 0:
            raise RuntimeError(status.stderr.decode(errors="replace"))
        records = _status_records(status.stdout)
        decision = policy.explain("two/b.txt")
        before_status_code = before_records.get("two/b.txt")
        status_code = records.get("two/b.txt")
        policy_membership = decision.membership
        status_membership = _membership_from_status(status_code)
        refresh_stderr = refresh.stderr.decode(errors="replace").replace(str(root), "<repo>")
        file_exists = tracked_path.exists()
        known_failure = (
            refresh.returncode == 1
            and "ProgrammingError" in refresh_stderr
            and file_exists
            and status_code == "?"
            and policy_membership == "unversioned"
        )
        fixed_behavior = (
            refresh.returncode == 0
            and file_exists
            and status_membership == "versioned"
            and policy_membership == "versioned"
        )
        candidate_matches = known_failure or fixed_behavior
        version = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            check=False,
            timeout=30,
        )
        version_lines = version.stdout.decode(errors="replace").splitlines()
        result: dict[str, Any] = {
            "id": "hg.sparse-refresh-membership",
            "schema_version": 1,
            "status": "captured",
            "candidate_matches": candidate_matches,
            "client": {
                "executable": executable,
                "version": version_lines[0] if version_lines else "unknown",
                "platform": platform.platform(),
            },
            "scenario": "remove an exclusion from .hg/sparse and refresh the working copy",
            "path": "two/b.txt",
            "refresh": {
                "command": [executable, "debugsparse", "--refresh"],
                "exit_code": refresh.returncode,
                "programming_error": "ProgrammingError" in refresh_stderr,
                "stderr": refresh_stderr,
            },
            "before_refresh": {
                "file_exists": False,
                "status_code": before_status_code,
                "policy_membership": before_decision.membership,
            },
            "after_refresh": {
                "file_exists": file_exists,
                "status_code": status_code,
                "policy_membership": policy_membership,
                "status_membership": status_membership,
                "policy_matches_native_status": policy_membership == status_membership,
            },
        }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"Mercurial sparse refresh: exit={result['refresh']['exit_code']}, "
        f"status={status_code!r}, "
        f"policy_match={result['after_refresh']['policy_matches_native_status']}, "
        f"known_or_fixed_profile={candidate_matches}"
    )
    return 0 if candidate_matches else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Capture the current Mercurial sparse-refresh result to a JSON file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hg", default="hg", help="Mercurial executable")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("sparse-refresh.capture.local.json"),
    )
    arguments = parser.parse_args(argv)
    return capture(arguments.hg, arguments.output)


if __name__ == "__main__":
    raise SystemExit(main())
