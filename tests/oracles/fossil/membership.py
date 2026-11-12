"""Capture Fossil file-membership states in an isolated disposable checkout."""

from __future__ import annotations

import argparse
import base64
import json
import platform
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def _run(
    fossil: str,
    arguments: Sequence[str],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [fossil, *arguments],
        cwd=cwd,
        env=environment,
        capture_output=True,
        timeout=30,
        check=False,
    )


def _json_payload(result: subprocess.CompletedProcess[bytes], operation: str) -> dict[str, Any]:
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"Fossil {operation} failed ({result.returncode}): {detail}")
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict) or not isinstance(payload.get("payload"), dict):
        raise RuntimeError(f"Fossil {operation} returned an invalid JSON envelope")
    return payload["payload"]


def _entry_list(payload: dict[str, Any], key: str, *, operation: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("name"), str) for item in value
    ):
        raise RuntimeError(f"Fossil {operation} did not contain valid {key} entries")
    return value


def _raw_result(result: subprocess.CompletedProcess[bytes]) -> dict[str, Any]:
    return {
        "exit_code": result.returncode,
        "stdout_base64": base64.b64encode(result.stdout).decode("ascii"),
        "stderr_base64": base64.b64encode(result.stderr).decode("ascii"),
    }


def _capture(fossil: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="gitignore-walk-fossil-membership-") as temporary:
        temp_root = Path(temporary)
        home = temp_root / "home"
        home.mkdir()
        checkout = temp_root / "checkout"
        repository = temp_root / "repository.fossil"
        environment = {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "USER": "oracle",
            "PATH": str(Path(fossil).resolve().parent),
            "LC_ALL": "C",
            "LANG": "C",
            "TZ": "UTC",
        }

        commands = (
            ("init", "--admin-user", "oracle", str(repository)),
            ("open", "--nosync", "--workdir", str(checkout), str(repository)),
        )
        for command in commands:
            result = _run(fossil, command, cwd=temp_root, environment=environment)
            if result.returncode != 0:
                detail = result.stderr.decode("utf-8", errors="replace")
                raise RuntimeError(f"Fossil {' '.join(command[:1])} failed: {detail}")

        setting = _run(
            fossil, ("settings", "ignore-glob", "*.tmp"), cwd=checkout, environment=environment
        )
        if setting.returncode != 0:
            raise RuntimeError(f"Fossil settings failed: {setting.stderr.decode(errors='replace')}")
        seed = {
            "tracked.tmp": "tracked despite ignore\n",
            "nested/versioned.txt": "nested tracked file\n",
            "deleted.tmp": "will be removed\n",
            "modified.tmp": "before edit\n",
            "moved.tmp": "will be renamed\n",
        }
        for relative, contents in seed.items():
            path = checkout / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8")

        add = _run(
            fossil,
            ("add", "--force", *seed),
            cwd=checkout,
            environment=environment,
        )
        if add.returncode != 0:
            raise RuntimeError(f"Fossil add failed: {add.stderr.decode(errors='replace')}")
        commit = _run(
            fossil,
            ("commit", "--no-warnings", "-m", "membership oracle baseline"),
            cwd=checkout,
            environment=environment,
        )
        if commit.returncode != 0:
            raise RuntimeError(f"Fossil commit failed: {commit.stderr.decode(errors='replace')}")

        root_result = _run(
            fossil,
            ("json", "dir", "--checkin", "current", "--name", "/"),
            cwd=checkout,
            environment=environment,
        )
        root = _json_payload(root_result, "json dir root")
        nested_result = _run(
            fossil,
            ("json", "dir", "--checkin", "current", "--name", "nested"),
            cwd=checkout,
            environment=environment,
        )
        nested = _json_payload(nested_result, "json dir nested")
        status_before_result = _run(
            fossil, ("json", "status"), cwd=checkout, environment=environment
        )
        status_before = _json_payload(status_before_result, "json status before transitions")

        (checkout / "added.tmp").write_text("scheduled despite ignore\n", encoding="utf-8")
        add_pending = _run(
            fossil,
            ("add", "--force", "added.tmp"),
            cwd=checkout,
            environment=environment,
        )
        if add_pending.returncode != 0:
            detail = add_pending.stderr.decode(errors="replace")
            raise RuntimeError(f"Fossil add pending failed: {detail}")
        (checkout / "deleted.tmp").unlink()
        (checkout / "modified.tmp").write_text("after edit\n", encoding="utf-8")
        rename = _run(
            fossil,
            ("mv", "moved.tmp", "renamed.tmp"),
            cwd=checkout,
            environment=environment,
        )
        if rename.returncode != 0:
            raise RuntimeError(f"Fossil mv failed: {rename.stderr.decode(errors='replace')}")
        status_after_result = _run(
            fossil, ("json", "status"), cwd=checkout, environment=environment
        )
        status_after = _json_payload(status_after_result, "json status after transitions")

        root_entries = _entry_list(root, "entries", operation="json dir root")
        nested_entries = _entry_list(nested, "entries", operation="json dir nested")
        before_files = _entry_list(status_before, "files", operation="json status before")
        after_files = _entry_list(status_after, "files", operation="json status after")
        status_by_name = {item["name"]: item.get("status") for item in after_files}
        root_names = sorted(item["name"] for item in root_entries)
        nested_names = sorted(item["name"] for item in nested_entries)
        expected_status = {
            "added.tmp": "new",
            "deleted.tmp": "missing",
            "modified.tmp": "edited",
            "renamed.tmp": ["missing", "renamed"],
        }
        cases = [
            {
                "id": f"fossil.membership.{name}",
                "expected_status": expected,
                "observed_status": status_by_name.get(name),
                "candidate_matches": status_by_name.get(name) == expected,
            }
            for name, expected in expected_status.items()
        ]
        cases.extend(
            (
                {
                    "id": "fossil.membership.root-inventory",
                    "expected_entries": [
                        "deleted.tmp",
                        "modified.tmp",
                        "moved.tmp",
                        "nested",
                        "tracked.tmp",
                    ],
                    "observed_entries": root_names,
                    "candidate_matches": root_names
                    == ["deleted.tmp", "modified.tmp", "moved.tmp", "nested", "tracked.tmp"],
                },
                {
                    "id": "fossil.membership.nested-inventory",
                    "expected_entries": ["versioned.txt"],
                    "observed_entries": nested_names,
                    "candidate_matches": nested_names == ["versioned.txt"],
                },
                {
                    "id": "fossil.membership.clean-status",
                    "expected_status_files": [],
                    "observed_status_files": before_files,
                    "candidate_matches": before_files == [],
                },
            )
        )
        version = _run(fossil, ("version",), cwd=temp_root, environment=environment)
        if version.returncode != 0 or not version.stdout:
            raise RuntimeError("Fossil version query failed")

        return {
            "cases": cases,
            "client": {
                "fossil": version.stdout.decode("utf-8", errors="replace").splitlines()[0],
                "executable": fossil,
                "platform": platform.platform(),
                "runner_python": sys.version.split()[0],
            },
            "commands": {
                "inventory": [
                    "fossil json dir --checkin current --name /",
                    "fossil json dir --checkin current --name nested",
                ],
                "status": "fossil json status",
            },
            "native_results": {
                "root_inventory": _raw_result(root_result),
                "nested_inventory": _raw_result(nested_result),
                "clean_status": _raw_result(status_before_result),
                "transition_status": _raw_result(status_after_result),
            },
            "inventory": {
                "root_entries": root_names,
                "nested_entries": nested_names,
            },
            "before_transitions": {
                "status_files": before_files,
            },
            "after_transitions": {
                "status_files": after_files,
                "status_by_name": {item["name"]: item["status"] for item in after_files},
            },
        }


def capture(output: Path, fossil_name: str) -> int:
    executable = shutil.which(fossil_name)
    if executable is None:
        result: dict[str, Any] = {
            "schema_version": 1,
            "status": "skipped",
            "reason": f"Fossil executable not found: {fossil_name}",
            "client": None,
        }
    else:
        try:
            result = {"schema_version": 1, "status": "captured", **_capture(executable)}
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
            result = {"schema_version": 1, "status": "failed", "reason": str(error)}

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Fossil membership capture: {result['status']} ({output})")
    if result["status"] != "captured":
        if "reason" in result:
            print(result["reason"], file=sys.stderr)
        return 1 if result["status"] == "failed" else 0

    cases = result["cases"]
    matched = all(case["candidate_matches"] for case in cases)
    print(f"Membership transitions match: {matched} ({len(cases)} records)")
    return 0 if matched else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fossil", default="fossil", help="Fossil executable")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent / "results" / "fossil-membership-local.json",
    )
    arguments = parser.parse_args(argv)
    return capture(arguments.output, arguments.fossil)


if __name__ == "__main__":
    raise SystemExit(main())
