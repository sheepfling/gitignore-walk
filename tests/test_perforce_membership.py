"""Live Perforce membership checks against an isolated disposable server."""

from __future__ import annotations

import os
import shutil
import socket
import stat
import subprocess
import time
from pathlib import Path

import pytest

from gitignore_walk import IgnoreWalker, PerforceIgnorePolicy


def _native_path_matches(output: str, expected: Path) -> bool:
    """Compare tagged native local paths with the host filesystem's path conventions."""
    expected_key = os.path.normcase(os.path.abspath(expected))
    for line in output.splitlines():
        if line.startswith("... path "):
            observed = line[9:]
            if os.path.normcase(os.path.abspath(observed)) == expected_key:
                return True
    return False


def test_perforce_membership_matches_native_have_and_opened(
    tmp_path: Path,
) -> None:
    p4 = shutil.which("p4")
    p4d = shutil.which("p4d")
    if p4 is None or p4d is None:
        pytest.skip("Perforce p4 and p4d are required for native membership checks")

    temporary = tmp_path.resolve()
    server_root = temporary / "server"
    workspace = temporary / "workspace"
    home = temporary / "home"
    for directory in (server_root, workspace, home):
        directory.mkdir()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    address = f"127.0.0.1:{port}"
    client_name = "membership-test"
    password = "temporary-membership-password"
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.upper().startswith("P4"):
            del environment[name]
    environment.pop("PWD", None)
    environment.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "P4PORT": address,
            "P4USER": "super",
            "P4CLIENT": client_name,
            "P4CONFIG": "",
            "P4TICKETS": str(temporary / "tickets"),
            "P4TRUST": str(temporary / "trust"),
            "LC_ALL": "C",
            "TZ": "UTC",
        }
    )

    def run(
        *arguments: str,
        input_text: str | None = None,
        cwd: Path = workspace,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [p4, *arguments],
            cwd=cwd,
            env=environment,
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, (arguments, result.stdout, result.stderr)
        return result

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
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if server.poll() is not None:
                log_path = server_root / "log"
                log = (
                    log_path.read_text(encoding="utf-8", errors="replace")
                    if log_path.exists()
                    else "<p4d exited before creating its log>"
                )
                pytest.fail(
                    f"disposable p4d exited during startup ({server.returncode}): {log[-2000:]}"
                )
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            log_path = server_root / "log"
            log = (
                log_path.read_text(encoding="utf-8", errors="replace")
                if log_path.exists()
                else "<p4d has not created its log>"
            )
            pytest.fail(f"disposable p4d did not accept connections: {log[-2000:]}")
        run("info")

        run(
            "passwd",
            input_text=f"{password}\n{password}\n",
        )
        run("login", input_text=f"{password}\n")
        run(
            "depot",
            "-i",
            input_text=(
                "Depot: depot\nOwner: super\nDescription:\n\tdisposable test\n"
                "Type: local\nMap: depot/...\n"
            ),
        )
        run(
            "client",
            "-i",
            input_text=(
                f"Client: {client_name}\nOwner: super\nRoot: {workspace}\n"
                "Options: noallwrite noclobber nocompress unlocked nomodtime normdir\n"
                "LineEnd: local\nView:\n\t//depot/... //membership-test/...\n"
            ),
        )

        (workspace / "cache").mkdir()
        submitted = (
            "tracked.tmp",
            "CaseProbe.tmp",
            "modified.txt",
            "missing.txt",
            "deleted.txt",
            "cache/tracked.tmp",
        )
        for name in submitted:
            (workspace / name).write_text(f"initial {name}\n", encoding="utf-8")
        run("add", *submitted)
        run("submit", "-d", "initial membership fixture")

        run("edit", "modified.txt")
        (workspace / "modified.txt").write_text("modified\n", encoding="utf-8")
        missing = workspace / "missing.txt"
        missing.chmod(missing.stat().st_mode | stat.S_IWRITE)
        missing.unlink()
        run("delete", "-k", "deleted.txt")
        (workspace / "pending-add.tmp").write_text("pending add\n", encoding="utf-8")
        run("add", "pending-add.tmp")
        (workspace / "untracked.tmp").write_text("untracked\n", encoding="utf-8")
        (workspace / "cache" / "untracked.tmp").write_text("untracked\n", encoding="utf-8")
        (workspace / ".p4ignore").write_text("cache/\n*.tmp\n", encoding="utf-8")

        have = run("-ztag", "have").stdout
        opened = run("-ztag", "opened").stdout
        where = run("-ztag", "where", "//membership-test/pending-add.tmp").stdout
        assert _native_path_matches(have, workspace / "tracked.tmp")
        assert _native_path_matches(have, workspace / "CaseProbe.tmp")
        assert _native_path_matches(have, workspace / "missing.txt")
        assert _native_path_matches(have, workspace / "cache" / "tracked.tmp")
        assert "... action delete" in opened
        assert "... action edit" in opened
        assert "... action add" in opened
        assert _native_path_matches(where, workspace / "pending-add.tmp")

        policy = PerforceIgnorePolicy(
            workspace,
            environment=environment,
            membership_aware=True,
        )
        names = (
            "tracked.tmp",
            "modified.txt",
            "missing.txt",
            "deleted.txt",
            "pending-add.tmp",
            "untracked.tmp",
            "directory",
            "missing-unlisted.txt",
            "caseprobe.tmp",
            "cache",
            "cache/tracked.tmp",
            "cache/untracked.tmp",
        )
        (workspace / "directory").mkdir()
        decisions = policy.explain_many(names)
        try:
            case_alias_exists = os.path.samefile(
                workspace / "CaseProbe.tmp", workspace / "caseprobe.tmp"
            )
        except OSError:
            case_alias_exists = False

        assert {
            name: decision.membership for name, decision in zip(names, decisions, strict=True)
        } == {
            "tracked.tmp": "versioned",
            "modified.txt": "versioned",
            "missing.txt": "versioned",
            "deleted.txt": "versioned",
            "pending-add.tmp": "versioned",
            "untracked.tmp": "unversioned",
            "directory": None,
            "missing-unlisted.txt": None,
            "caseprobe.tmp": "versioned" if case_alias_exists else None,
            "cache": None,
            "cache/tracked.tmp": "versioned",
            "cache/untracked.tmp": "unversioned",
        }
        assert decisions[0].ignored is True
        assert decisions[4].ignored is True
        assert decisions[5].ignored is True
        assert decisions[-3].ignored is True
        assert decisions[-2].ignored is True
        assert decisions[-1].ignored is True

        for topdown in (True, False):
            walker = IgnoreWalker(workspace, policy=policy)
            included = set(walker.iter_files(selection="included", topdown=topdown))
            ignored = set(walker.iter_files(selection="ignored", topdown=topdown))
            assert workspace / "cache" / "tracked.tmp" in included
            assert workspace / "cache" / "tracked.tmp" not in ignored
            assert workspace / "cache" / "untracked.tmp" not in included
            assert workspace / "cache" / "untracked.tmp" in ignored
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
