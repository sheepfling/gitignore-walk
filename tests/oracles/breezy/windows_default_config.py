"""Compare Breezy's default Windows global-ignore path with the native client.

This probe temporarily writes one marker rule into the current Windows user's roaming
application-data directory, runs native Breezy in a disposable working tree, and restores
the prior file bytes in ``finally``. Run it only on an ephemeral Windows account and pass
``--allow-user-config-mutation`` explicitly.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from gitignore_walk import BreezyIgnorePolicy

_CSIDL_APPDATA = 0x001A
_MARKER_PATTERN = "*.default-appdata-probe"
_CANDIDATE = "candidate.default-appdata-probe"


def _roaming_appdata() -> Path:
    """Resolve the current user's Windows roaming application-data folder via Shell32."""
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        raise RuntimeError("Windows Shell32 is unavailable")
    value = ctypes.create_unicode_buffer(32768)
    result = windll.shell32.SHGetFolderPathW(None, _CSIDL_APPDATA, None, 0, value)
    if result != 0 or not value.value:
        raise OSError(f"SHGetFolderPathW(CSIDL_APPDATA) failed with HRESULT {result:#x}")
    return Path(value.value)


def _run(command: Sequence[str], *, cwd: Path, environment: dict[str, str]) -> dict[str, Any]:
    result = subprocess.run(
        list(command),
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    return {
        "command": [Path(command[0]).name, *command[1:]],
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _ignored_paths(output: str) -> set[str]:
    paths: set[str] = set()
    for line in output.splitlines():
        match = re.match(r"^(.*?)\s{2,}\S", line)
        if match:
            paths.add(match.group(1).strip().replace("\\", "/"))
    return paths


def capture(output: Path) -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("the default Breezy Windows config probe only runs on Windows")
    appdata = _roaming_appdata()
    process_appdata = Path(os.environ["APPDATA"])
    global_ignore = appdata / "Breezy" / "3.0" / "ignore"
    breezy = shutil.which("brz")
    if breezy is None:
        raise FileNotFoundError("Breezy executable 'brz' was not found")

    path_existed = global_ignore.exists()
    original = global_ignore.read_bytes() if path_existed else None
    original_sha256 = hashlib.sha256(original).hexdigest() if original is not None else None
    created_directories: list[Path] = []
    cursor = global_ignore.parent
    while not cursor.exists() and cursor != appdata:
        created_directories.append(cursor)
        cursor = cursor.parent

    try:
        global_ignore.parent.mkdir(parents=True, exist_ok=True)
        fixture_bytes = (_MARKER_PATTERN + "\n").encode("utf-8")
        global_ignore.write_bytes(fixture_bytes)
        environment = os.environ.copy()
        environment.pop("BRZ_HOME", None)
        environment.update(
            {
                "BRZ_PLUGIN_PATH": "",
                "BRZ_LOG": os.devnull,
                "LC_ALL": "C",
                "LANG": "C",
                "TZ": "UTC",
            }
        )
        with tempfile.TemporaryDirectory(prefix="gitignore-walk-brz-appdata-") as temporary:
            working_tree = Path(temporary) / "tree"
            working_tree.mkdir()
            init = _run(
                [breezy, "init", "--no-plugins", str(working_tree)],
                cwd=working_tree,
                environment=environment,
            )
            (working_tree / _CANDIDATE).write_text("probe\n", encoding="utf-8")
            ignored = _run(
                [breezy, "ignored", "--no-plugins", "--verbose"],
                cwd=working_tree,
                environment=environment,
            )
            policy = BreezyIgnorePolicy(working_tree, environment=environment)
            decision = policy.explain(_CANDIDATE)
            for observation in (init, ignored):
                observation["stdout"] = (
                    observation["stdout"]
                    .replace(str(working_tree), "<working-tree>")
                    .replace(str(appdata), "<APPDATA>")
                )
                observation["stderr"] = (
                    observation["stderr"]
                    .replace(str(working_tree), "<working-tree>")
                    .replace(str(appdata), "<APPDATA>")
                )
            normalized_stdout = ignored["stdout"]
            ignored_paths = sorted(_ignored_paths(normalized_stdout))
            policy_source = (
                decision.source.replace(str(process_appdata), "<APPDATA>")
                .replace(str(appdata), "<APPDATA>")
                .replace("\\", "/")
                if decision.source is not None
                else None
            )
            expected_policy_source = "<APPDATA>/Breezy/3.0/ignore"
            result = {
                "schema_version": 1,
                "status": "captured",
                "client": {"version": _version(breezy), "platform": platform.platform()},
                "known_folder": "<APPDATA>",
                "process_appdata_matches_shell_folder": os.path.normcase(
                    os.path.abspath(process_appdata)
                )
                == os.path.normcase(os.path.abspath(appdata)),
                "global_ignore_path": "<APPDATA>/Breezy/3.0/ignore",
                "global_ignore_original_existed": path_existed,
                "global_ignore_original_sha256": original_sha256,
                "fixture_pattern": _MARKER_PATTERN,
                "global_ignore_fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
                "working_tree_init": init,
                "native_ignored_query": ignored,
                "native_ignored_stdout_normalized": normalized_stdout,
                "native_ignored_stdout_sha256": hashlib.sha256(
                    normalized_stdout.encode()
                ).hexdigest(),
                "native_ignored_paths": ignored_paths,
                "policy_ignored": decision.ignored,
                "policy_source": policy_source,
                "policy_pattern": decision.pattern,
                "expected_ignored_paths": [_CANDIDATE],
                "candidate_matches": (
                    init["exit_code"] == 0
                    and ignored["exit_code"] == 0
                    and ignored_paths == [_CANDIDATE]
                    and decision.ignored
                    and policy_source == expected_policy_source
                ),
            }
    finally:
        if path_existed:
            global_ignore.write_bytes(original or b"")
        else:
            global_ignore.unlink(missing_ok=True)
            for directory in created_directories:
                try:
                    directory.rmdir()
                except OSError:
                    break

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result


def _version(executable: str) -> str:
    result = subprocess.run(
        [executable, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=True,
    )
    return result.stdout.splitlines()[0] if result.stdout.splitlines() else "unknown"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--allow-user-config-mutation",
        action="store_true",
        help="allow temporary modification of the current user's APPDATA Breezy ignore file",
    )
    arguments = parser.parse_args(argv)
    if not arguments.allow_user_config_mutation:
        parser.error("pass --allow-user-config-mutation only on an ephemeral Windows account")
    result = capture(arguments.output)
    return 0 if result["candidate_matches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
