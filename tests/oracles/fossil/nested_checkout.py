"""Capture Fossil nested-checkout traversal boundaries."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from gitignore_walk import FossilIgnorePolicy, IgnoreWalker


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
        timeout=60,
        check=False,
    )


def _distribution() -> str:
    """Return the operating-system distribution name for this capture host."""
    release_file = Path("/etc/os-release")
    if release_file.is_file():
        for line in release_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.partition("=")[2].strip().strip('"')
    if platform.system() == "Darwin":
        version = platform.mac_ver()[0]
        return f"macOS {version}" if version else "macOS"
    return platform.platform()


def _capture(fossil: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="gitignore-walk-fossil-nested-") as temporary:
        root = Path(temporary).resolve()
        home = root / "home"
        home.mkdir()
        parent = root / "parent"
        nested = parent / "nested"
        parent_repository = root / "parent.fossil"
        nested_repository = root / "nested.fossil"
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
            ("init parent", ("init", "--admin-user", "oracle", str(parent_repository)), root),
            (
                "open parent",
                ("open", "--nosync", "--workdir", str(parent), str(parent_repository)),
                root,
            ),
            (
                "init nested",
                ("init", "--admin-user", "oracle", str(nested_repository)),
                root,
            ),
            (
                "open nested",
                (
                    "open",
                    "--nested",
                    "--nosync",
                    "--workdir",
                    str(nested),
                    str(nested_repository),
                ),
                root,
            ),
        )
        for label, arguments, cwd in commands:
            result = _run(fossil, arguments, cwd=cwd, environment=environment)
            if result.returncode != 0:
                detail = result.stderr.decode("utf-8", errors="replace")
                raise RuntimeError(f"Fossil {label} failed ({result.returncode}): {detail}")

        (parent / "outer.txt").write_text("parent file\n", encoding="utf-8")
        (nested / "inner.txt").write_text("nested file\n", encoding="utf-8")
        native = _run(
            fossil,
            ("extras", "--dotfiles"),
            cwd=parent,
            environment=environment,
        )
        if native.returncode != 0:
            detail = native.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"Fossil extras failed ({native.returncode}): {detail}")
        native_paths = sorted(
            line for line in native.stdout.decode("utf-8", errors="replace").splitlines() if line
        )

        policy = FossilIgnorePolicy(
            parent,
            fossil_executable=fossil,
            environment=environment,
        )
        policy_paths = sorted(
            path.relative_to(parent).as_posix()
            for path in IgnoreWalker(parent, policy=policy).iter_files()
        )
        version = _run(fossil, ("version",), cwd=root, environment=environment)
        if version.returncode != 0 or not version.stdout:
            raise RuntimeError("Fossil version query failed")

        expected_paths = ["outer.txt"]
        return {
            "schema_version": 1,
            "status": "captured"
            if native_paths == expected_paths and policy_paths == native_paths
            else "failed",
            "case": {
                "id": "fossil.walk-stops-at-nested-checkout",
                "command": ["fossil", "extras", "--dotfiles"],
                "expected_paths": expected_paths,
                "observed_native_paths": native_paths,
                "observed_policy_paths": policy_paths,
                "candidate_matches_native": policy_paths == native_paths,
                "native_matches_expected": native_paths == expected_paths,
                "exit_code": native.returncode,
                "stderr": native.stderr.decode("utf-8", errors="replace"),
            },
            "client": {
                "fossil": version.stdout.decode("utf-8", errors="replace").splitlines()[0],
                "executable": fossil,
                "distribution": _distribution(),
                "platform": platform.platform(),
                "runner_python": sys.version.split()[0],
            },
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fossil", default="fossil", help="Fossil executable")
    parser.add_argument("--output", type=Path, required=True, help="capture destination")
    args = parser.parse_args(argv)
    executable = shutil.which(args.fossil)
    if executable is None:
        parser.error(f"Fossil executable not found: {args.fossil}")
    result = _capture(executable)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Fossil nested-checkout capture: {result['status']}")
    print(f"Client: {result['client']['fossil']}")
    print(f"Native: {result['case']['observed_native_paths']}")
    print(f"Policy: {result['case']['observed_policy_paths']}")
    print(f"Capture: {args.output}")
    return 0 if result["status"] == "captured" else 1


if __name__ == "__main__":
    raise SystemExit(main())
