"""Capture P4IGNORE behavior with disposable local P4 clients and servers."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _run(
    executable: str,
    arguments: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(environment)
    env["PWD"] = str(cwd)
    return subprocess.run(
        [executable, *arguments],
        cwd=cwd,
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )


def _write_files(root: Path, files: Mapping[str, str]) -> None:
    for relative, contents in files.items():
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as error:
            raise ValueError(f"fixture path escapes its temporary workspace: {relative}") from error
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as stream:
            stream.write(contents)


def _ignored_by_rules(stdout: str, stderr: str) -> bool | None:
    """Parse the explicit ``p4 ignores -i -v`` rule-match result."""
    output = stdout + stderr
    if re.search(r"\bnot ignored\b", output, flags=re.IGNORECASE):
        return False
    if re.search(r"\bignored by\b", output, flags=re.IGNORECASE):
        return True
    return None


def _capture_case(case: Mapping[str, Any], p4: str, p4d: str) -> dict[str, Any]:
    setup = case["setup"]
    with tempfile.TemporaryDirectory(prefix="gitignore-walk-p4-oracle-") as temporary:
        temp = Path(temporary).resolve()
        server_root = temp / "server"
        home = temp / "home"
        workspace = temp / "workspace"
        server_root.mkdir()
        home.mkdir()
        workspace.mkdir()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        address = f"127.0.0.1:{port}"
        password = "temporary-oracle-password"
        client_name = "ignore-oracle"
        environment = {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "PATH": os.environ.get("PATH", ""),
            "P4PORT": address,
            "P4USER": "super",
            "P4CLIENT": client_name,
            "P4CONFIG": setup.get("P4CONFIG", ""),
            "P4TICKETS": str(temp / "tickets"),
            "P4TRUST": str(temp / "trust"),
            "LC_ALL": "C",
            "TZ": "UTC",
        }
        if "P4IGNORE" in setup:
            environment["P4IGNORE"] = setup["P4IGNORE"]
        _write_files(workspace, setup.get("files", {}))
        target = (workspace / case["query"]).resolve()
        try:
            target.relative_to(workspace.resolve())
        except ValueError as error:
            raise ValueError(
                f"fixture query escapes its temporary workspace: {case['query']}"
            ) from error
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch(exist_ok=True)

        server = subprocess.Popen(
            [
                p4d,
                "-r",
                str(server_root),
                "-p",
                address,
                "-L",
                str(server_root / "log"),
                "-J",
                str(server_root / "journal"),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(100):
                info = _run(p4, ["info"], cwd=workspace, environment=environment)
                if info.returncode == 0:
                    break
                if server.poll() is not None:
                    raise RuntimeError(f"p4d exited during startup: {server.returncode}")
                time.sleep(0.05)
            else:
                raise TimeoutError("local p4d did not accept connections")

            password_result = _run(
                p4,
                ["passwd"],
                cwd=workspace,
                environment=environment,
                input_text=f"{password}\n{password}\n",
            )
            login = _run(
                p4,
                ["login"],
                cwd=workspace,
                environment=environment,
                input_text=f"{password}\n",
            )
            depot_spec = "\n".join(
                [
                    "Depot: depot",
                    "Owner: super",
                    "Description:",
                    "\toracle",
                    "Type: local",
                    "Map: depot/...",
                    "",
                ]
            )
            depot = _run(
                p4,
                ["depot", "-i"],
                cwd=workspace,
                environment=environment,
                input_text=depot_spec,
            )
            client_spec = (
                f"Client: {client_name}\n"
                "Owner: super\n"
                f"Root: {workspace}\n"
                "Options: noallwrite noclobber nocompress unlocked nomodtime normdir\n"
                "LineEnd: local\n"
                "View:\n"
                f"\t//depot/... //{client_name}/...\n"
            )
            client = _run(
                p4,
                ["client", "-i"],
                cwd=workspace,
                environment=environment,
                input_text=client_spec,
            )
            if any(result.returncode != 0 for result in (password_result, login, depot, client)):
                raise RuntimeError(
                    "failed to prepare disposable P4 server: "
                    + repr([result.stderr for result in (password_result, login, depot, client)])
                )

            query_cwd = workspace
            query_argument = case["query"]
            if case.get("query_cwd") == "parent":
                query_cwd = (workspace / Path(case["query"]).parent).resolve()
                query_argument = Path(case["query"]).name
            command = _run(
                p4,
                ["add", "-n", query_argument],
                cwd=query_cwd,
                environment=environment,
            )
            ignore_check = _run(
                p4,
                ["ignores", "-i", "-v", query_argument],
                cwd=query_cwd,
                environment=environment,
            )
            walk_preview = (
                _run(p4, ["add", "-n", "..."], cwd=workspace, environment=environment)
                if case.get("capture_walk")
                else None
            )
            command_output = command.stdout + command.stderr
            ignored = "ignored file can't be added" in command_output
            expected_native_error = case.get("expected_native_error")
            if expected_native_error is not None:
                if expected_native_error not in command_output:
                    raise RuntimeError(
                        f"native Perforce error changed for {case['id']}: "
                        f"expected {expected_native_error!r}, got "
                        f"{command.returncode}, {command_output!r}"
                    )
                ignored_result: bool | None = None
            elif not ignored and (
                command.returncode != 0 or "opened for add" not in command_output
            ):
                raise RuntimeError(
                    f"p4 add preview did not produce a recognized result for {case['id']}: "
                    f"{command.returncode}, {command.stdout!r}, {command.stderr!r}"
                )
            else:
                ignored_result = ignored
            expected = case["expected_candidate"]
            client_version = _run(
                p4, ["-V"], cwd=workspace, environment=environment
            ).stdout.splitlines()
            config_result = (
                _run(p4, ["set"], cwd=query_cwd, environment=environment)
                if setup.get("P4CONFIG")
                else None
            )
            server_version = next(
                (
                    line.partition(": ")[2]
                    for line in info.stdout.splitlines()
                    if line.startswith("Server version: ")
                ),
                "unknown",
            )
            return {
                "id": case["id"],
                "dimension": case["dimension"],
                "evidence_status": case["evidence_status"],
                "native_status": "captured",
                "query": case["query"],
                "expected_candidate": expected,
                "observed_ignored": ignored_result,
                "candidate_matches": (
                    ignored_result is expected
                    if isinstance(expected, bool) and ignored_result is not None
                    else None
                ),
                **(
                    {"native_error": expected_native_error}
                    if expected_native_error is not None
                    else {}
                ),
                "server_version": server_version,
                "client_version": next(
                    (line[5:] for line in client_version if line.startswith("Rev. ")), "unknown"
                ),
                "command": ["p4", "add", "-n", case["query"]],
                "command_cwd": query_cwd.relative_to(workspace).as_posix() or ".",
                "exit_code": command.returncode,
                "stdout": command.stdout.replace(str(workspace), "<workspace>"),
                "stderr": command.stderr.replace(str(workspace), "<workspace>"),
                "ignore_check": {
                    "command": ["p4", "ignores", "-i", "-v", query_argument],
                    "exit_code": ignore_check.returncode,
                    "observed_ignored": _ignored_by_rules(ignore_check.stdout, ignore_check.stderr),
                    "stdout": ignore_check.stdout.replace(str(workspace), "<workspace>"),
                    "stderr": ignore_check.stderr.replace(str(workspace), "<workspace>"),
                },
                "isolated_configuration": True,
                "p4_set_exit_code": config_result.returncode if config_result else None,
                "p4_set_output": (
                    (config_result.stdout + config_result.stderr).replace(
                        str(workspace), "<workspace>"
                    )
                    if config_result
                    else None
                ),
                "server_root": "<temp>/server",
                "workspace_root": "<temp>/workspace",
                "walk_preview": (
                    {
                        "command": ["p4", "add", "-n", "..."],
                        "exit_code": walk_preview.returncode,
                        "stdout": walk_preview.stdout.replace(str(workspace), "<workspace>"),
                        "stderr": walk_preview.stderr.replace(str(workspace), "<workspace>"),
                    }
                    if walk_preview
                    else None
                ),
            }
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


def capture(cases_path: Path, output_path: Path, p4_name: str, p4d_name: str) -> int:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    p4 = shutil.which(p4_name)
    p4d = shutil.which(p4d_name)
    if p4 is None or p4d is None:
        missing = [name for name, path in ((p4_name, p4), (p4d_name, p4d)) if path is None]
        result: dict[str, Any] = {
            "schema_version": 1,
            "status": "skipped",
            "reason": f"Perforce oracle executable(s) not found: {', '.join(missing)}",
            "client": None,
            "cases": [],
        }
    else:
        captured = [_capture_case(case, p4, p4d) for case in cases]
        walk_failed = any(
            case["walk_preview"] is not None and case["walk_preview"]["exit_code"] != 0
            for case in captured
        )
        result = {
            "schema_version": 1,
            "status": "captured"
            if not walk_failed and all(case["candidate_matches"] is not False for case in captured)
            else "failed",
            "client": {
                "p4": p4,
                "p4d": p4d,
                "version": subprocess.run(
                    [p4, "-V"], capture_output=True, text=True, check=False, timeout=30
                )
                .stdout.split("Rev. ", maxsplit=1)[-1]
                .splitlines()[0],
                "platform": platform.platform(),
                "runner_python": sys.version.split()[0],
            },
            "cases": captured,
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Captured {len(result['cases'])} Perforce cases: {result['status']}")
    if result["status"] == "captured":
        compared = [case for case in result["cases"] if case["candidate_matches"] is not None]
        matched = sum(case["candidate_matches"] is True for case in compared)
        print(f"Boolean candidates matching: {matched}/{len(compared)}")
    print(f"Capture: {output_path}")
    return 0 if result["status"] in {"captured", "skipped"} else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("cases.json"))
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).with_name("capture.local.json")
    )
    parser.add_argument("--p4", default="p4")
    parser.add_argument("--p4d", default="p4d")
    args = parser.parse_args(argv)
    return capture(args.cases, args.output, args.p4, args.p4d)


if __name__ == "__main__":
    raise SystemExit(main())
