"""Capture Sapling path-pattern behavior while preserving native client failures."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import tempfile
from pathlib import Path
from typing import Any

try:
    from .run import (
        _expand_ignored_paths,
        _prepare_sapling_oracle_home,
        _run,
        _sapling_status_paths,
        _version,
        _write_extended_pattern_probes,
        _write_files,
        _write_pattern_probes,
    )
except ImportError:  # pragma: no cover - direct script execution from the repository root
    from run import (
        _expand_ignored_paths,
        _prepare_sapling_oracle_home,
        _run,
        _sapling_status_paths,
        _version,
        _write_extended_pattern_probes,
        _write_files,
        _write_pattern_probes,
    )


def _capture_probe(
    executable: str,
    *,
    root: Path,
    environment: dict[str, str],
    probe_id: str,
    query_files: list[str],
    expected_ignored: list[str],
) -> dict[str, Any]:
    """Record one status probe, keeping nonzero native exits distinct from matches."""
    status = _run(
        [executable, "status", "-iu", "--print0"],
        cwd=root,
        environment=environment,
    )
    stderr = status.stderr.replace(str(root), "<workspace>")
    stderr = re.sub(r"(thread 'main' \()\d+(\))", r"\1<pid>\2", stderr)
    observation: dict[str, Any] = {
        "id": probe_id,
        "query_files": sorted(query_files),
        "expected_ignored": sorted(expected_ignored),
        "status_exit_code": status.returncode,
        "status_stdout": status.stdout.replace(str(root), "<workspace>"),
        "status_stderr": stderr,
    }
    if status.returncode != 0:
        observation.update(native_status="client-error", candidate_matches=None)
        return observation

    _, ignored_paths = _sapling_status_paths(status.stdout)
    ignored = sorted(_expand_ignored_paths(ignored_paths, set(query_files)))
    observation.update(
        native_status="captured",
        ignored=ignored,
        included=sorted(set(query_files) - set(ignored)),
        candidate_matches=ignored == sorted(expected_ignored),
    )
    return observation


def capture(executable: str) -> dict[str, Any]:
    """Run the legacy `.sl` pattern probes in isolated disposable workspaces."""
    fixture = json.loads(Path(__file__).with_name("cases.json").read_text(encoding="utf-8"))
    probes = []
    for probe_id, query_key, expected_key, extended in (
        (
            "sapling.sl-mode.pattern_discovery",
            "pattern_query_files",
            "expected_pattern_ignored",
            False,
        ),
        (
            "sapling.sl-mode.extended_pattern_discovery",
            "extended_pattern_query_files",
            "expected_extended_pattern_ignored",
            True,
        ),
    ):
        with tempfile.TemporaryDirectory(prefix="gitignore-walk-sapling-pattern-sl-") as temporary:
            base = Path(temporary)
            home = base / "home"
            _prepare_sapling_oracle_home(home)
            root = base / "workspace"
            root.mkdir()
            environment = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("GIT_CONFIG_")
                and key
                not in {
                    "GIT_DIR",
                    "GIT_WORK_TREE",
                    "GIT_INDEX_FILE",
                    "GIT_COMMON_DIR",
                    "HGRCPATH",
                    "HGRCSKIPREPO",
                    "SL_CONFIG",
                    "SL_CONFIG_PATH",
                }
            }
            environment.update(
                {
                    "HOME": str(home),
                    "USERPROFILE": str(home),
                    "XDG_CONFIG_HOME": str(home / ".config"),
                    "SL_USER": "Oracle <oracle@example.invalid>",
                    "PAGER": "cat",
                    "HGPLAIN": "1",
                    "GIT_CONFIG_NOSYSTEM": "1",
                }
            )
            initialized = _run([executable, "init", str(root)], cwd=root, environment=environment)
            if initialized.returncode != 0:
                raise RuntimeError(
                    "Sapling initialization failed: "
                    f"{initialized.stderr.strip() or initialized.stdout.strip()}"
                )
            _write_files(root, fixture["probe_files"])
            if extended:
                _write_pattern_probes(root, fixture)
                _write_extended_pattern_probes(root, fixture)
            else:
                _write_pattern_probes(root, fixture)
            probes.append(
                _capture_probe(
                    executable,
                    root=root,
                    environment=environment,
                    probe_id=probe_id,
                    query_files=fixture[query_key],
                    expected_ignored=fixture[expected_key],
                )
            )

    client_errors = sum(probe["native_status"] == "client-error" for probe in probes)
    mismatches = sum(probe["candidate_matches"] is False for probe in probes)
    return {
        "schema_version": 1,
        "status": "captured",
        "conformance": (
            "client-error-observed"
            if client_errors
            else "candidate-mismatch"
            if mismatches
            else "matched"
        ),
        "client": _version(executable),
        "platform": platform.platform(),
        "storage_mode": "sl",
        "isolated_temporary_workspaces": True,
        "probes": probes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sl", default="sl", help="Sapling executable")
    parser.add_argument("--output", type=Path, required=True, help="capture destination")
    arguments = parser.parse_args()
    result = capture(arguments.sl)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Sapling .sl pattern probe: {result['conformance']}")
    print(f"Capture: {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
