"""Capture Mercurial repository-config trust behavior in an isolated workspace."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

try:
    import pwd
except ImportError:  # pragma: no cover - unavailable on Windows
    pwd = None  # type: ignore[assignment]


def _ignored(stdout: str) -> bool | None:
    matches = re.findall(r"(?:^|\n)[^\n]+ is (not )?ignored(?:\b|$)", stdout)
    if len(matches) != 1:
        return None
    return matches[0] == ""


def _environment(home: Path, hgrc: Path) -> dict[str, str]:
    return {
        **os.environ,
        "HOME": str(home),
        "HGRCPATH": str(hgrc),
        "HGPLAIN": "1",
        "LC_ALL": "C",
    }


def _run_as(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    identity_prefix: list[str],
) -> subprocess.CompletedProcess[str]:
    if identity_prefix:
        actual = [
            *identity_prefix,
            "env",
            *(f"{key}={value}" for key, value in environment.items()),
            *command,
        ]
        process_environment = {"PATH": environment["PATH"]}
    else:
        actual = command
        process_environment = environment
    return subprocess.run(
        actual,
        cwd=cwd,
        env=process_environment,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
        timeout=30,
    )


def _policy_probe(
    repository: Path,
    *,
    environment: dict[str, str],
    identity_prefix: list[str],
) -> dict[str, Any]:
    code = (
        "import json, os; "
        "from gitignore_walk import MercurialIgnorePolicy; "
        "env = {key: os.environ[key] for key in "
        "('HOME', 'HGRCPATH', 'HGPLAIN', 'LC_ALL', 'PATH')}; "
        "policy = MercurialIgnorePolicy(os.environ['HG_TRUST_REPO'], "
        "read_client_config=True, environment=env); "
        "decision = policy.explain('a.tmp'); "
        "print(json.dumps({'ignored': decision.ignored, "
        "'discovery_complete': decision.discovery_complete, "
        "'source': decision.source, "
        "'diagnostics': [item.code for item in decision.diagnostics]}))"
    )
    child_environment = {**environment, "HG_TRUST_REPO": str(repository)}
    result = _run_as(
        [sys.executable, "-c", code],
        cwd=repository,
        environment=child_environment,
        identity_prefix=identity_prefix,
    )
    if result.returncode != 0:
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "ignored": None,
            "discovery_complete": None,
            "source": None,
            "diagnostics": [],
        }
    return {"exit_code": 0, **json.loads(result.stdout)}


def _capture_state(
    label: str,
    *,
    hg: str,
    repository: Path,
    home: Path,
    hgrc: Path,
    identity_prefix: list[str],
) -> dict[str, Any]:
    env = _environment(home, hgrc)
    config = _run_as(
        [hg, "config", "--debug", "ui"],
        cwd=repository,
        environment=env,
        identity_prefix=identity_prefix,
    )
    debugignore = _run_as(
        [hg, "debugignore", "-v", "--", "a.tmp"],
        cwd=repository,
        environment=env,
        identity_prefix=identity_prefix,
    )
    policy = _policy_probe(
        repository,
        environment=env,
        identity_prefix=identity_prefix,
    )
    expected_ignored = label == "trusted"
    return {
        "label": label,
        "expected_ignored": expected_ignored,
        "config": {
            "command": [hg, "config", "--debug", "ui"],
            "exit_code": config.returncode,
            "stdout": config.stdout.replace(str(repository), "<repo>")
            .replace(str(home), "<home>")
            .replace(str(hgrc), "<hgrc>"),
            "stderr": config.stderr.replace(str(repository), "<repo>")
            .replace(str(home), "<home>")
            .replace(str(hgrc), "<hgrc>"),
        },
        "debugignore": {
            "command": [hg, "debugignore", "-v", "--", "a.tmp"],
            "exit_code": debugignore.returncode,
            "observed_ignored": _ignored(debugignore.stdout),
            "stdout": debugignore.stdout.replace(str(repository), "<repo>").replace(
                str(home), "<home>"
            ),
            "stderr": debugignore.stderr.replace(str(repository), "<repo>").replace(
                str(home), "<home>"
            ),
        },
        "policy": policy,
        "matches": (
            config.returncode == 0
            and debugignore.returncode == 0
            and _ignored(debugignore.stdout) is expected_ignored
            and policy["exit_code"] == 0
            and policy["ignored"] is expected_ignored
            and policy["discovery_complete"] is True
        ),
    }


def _identity() -> tuple[list[str] | None, int | None, int | None, str | None]:
    if os.name != "posix":
        return None, None, None, "Mercurial config ownership trust is POSIX-specific"
    if os.geteuid() == 0:
        runuser = shutil.which("runuser")
        try:
            account = pwd.getpwnam("nobody") if pwd is not None else None
        except KeyError:
            account = None
        if runuser is None or account is None:
            return None, None, None, "root capture requires runuser and the nobody account"
        return [runuser, "-u", account.pw_name, "--"], account.pw_uid, account.pw_gid, None
    sudo = shutil.which("sudo")
    if sudo is None:
        return None, None, None, "non-root capture requires passwordless sudo to set file ownership"
    check = subprocess.run([sudo, "-n", "true"], capture_output=True, check=False, timeout=30)
    if check.returncode != 0:
        return None, None, None, "non-root capture requires passwordless sudo to set file ownership"
    return [], os.geteuid(), os.getegid(), None


def capture(output: Path, hg: str) -> int:
    executable = shutil.which(hg)
    identity_prefix, trusted_uid, trusted_gid, skip_reason = _identity()
    if executable is None:
        skip_reason = f"Mercurial executable not found: {hg}"
    if skip_reason is not None:
        result: dict[str, Any] = {
            "schema_version": 1,
            "status": "skipped",
            "reason": skip_reason,
            "client": None,
            "states": [],
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"Mercurial trust probe skipped: {skip_reason}")
        return 0

    with tempfile.TemporaryDirectory(prefix="gitignore-walk-hg-trust-") as temporary:
        temp = Path(temporary)
        temp.chmod(0o755)
        home = temp / "home"
        home.mkdir()
        hgrc = temp / "hgrc"
        hgrc.write_text("", encoding="utf-8")
        repository = temp / "repo"
        repository.mkdir()
        init = subprocess.run(
            [executable, "init", str(repository)],
            cwd=temp,
            env=_environment(home, hgrc),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        repository_hgrc = repository / ".hg" / "hgrc"
        repository_hgrc.write_text(
            "[ui]\nignore.trust_probe = ignore.rules\n",
            encoding="utf-8",
        )
        (repository / "ignore.rules").write_text(
            "syntax: glob\n*.tmp\n",
            encoding="utf-8",
        )
        if os.geteuid() == 0:
            os.chown(home, trusted_uid, trusted_gid)
            os.chown(hgrc, trusted_uid, trusted_gid)
            os.chown(repository_hgrc, trusted_uid, trusted_gid)
        states = [
            _capture_state(
                "trusted",
                hg=executable,
                repository=repository,
                home=home,
                hgrc=hgrc,
                identity_prefix=identity_prefix or [],
            )
        ]
        if os.geteuid() == 0:
            os.chown(repository_hgrc, 0, 0)
        else:
            subprocess.run(
                ["sudo", "-n", "chown", "root:root", str(repository_hgrc)],
                check=True,
                capture_output=True,
                timeout=30,
            )
        states.append(
            _capture_state(
                "untrusted",
                hg=executable,
                repository=repository,
                home=home,
                hgrc=hgrc,
                identity_prefix=identity_prefix or [],
            )
        )
        version = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, check=False, timeout=30
        )
        version_lines = version.stdout.splitlines()
        client = {
            "executable": executable,
            "version": version_lines[0] if version_lines else "unknown",
            "platform": platform.platform(),
            "runner_python": sys.version.split()[0],
        }
        result = {
            "schema_version": 1,
            "status": (
                "captured"
                if init.returncode == 0 and all(s["matches"] for s in states)
                else "failed"
            ),
            "client": client,
            "working_directory": "<repo>",
            "environment": {"HGRCPATH": "<temp>/hgrc", "HGPLAIN": "1", "LC_ALL": "C"},
            "init_exit_code": init.returncode,
            "states": states,
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Mercurial trust probe: {result['status']}")
    matches = sum(s["matches"] for s in states)
    print(f"Trusted and untrusted config states match: {matches}/{len(states)}")
    print(f"Capture: {output}")
    return 1 if result["status"] != "captured" else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("trust.capture.local.json"),
    )
    parser.add_argument("--hg", default="hg", help="Mercurial executable")
    args = parser.parse_args(argv)
    return capture(args.output, args.hg)


if __name__ == "__main__":
    raise SystemExit(main())
