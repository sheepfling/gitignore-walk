"""Capture Fossil ignore-glob and extras behavior in isolated disposable repositories."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _invoke(
    command: Sequence[str], *, cwd: Path, environment: Mapping[str, str]
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        list(command), cwd=cwd, env=dict(environment), capture_output=True, timeout=60, check=False
    )


def _write_target(root: Path, relative: str) -> None:
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"fixture path escapes its temporary checkout: {relative}") from error
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("oracle fixture\n", encoding="utf-8")


def _capture_case(case: Mapping[str, Any], fossil: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="gitignore-walk-fossil-oracle-") as temporary:
        temporary_root = Path(temporary)
        home = temporary_root / "home"
        home.mkdir()
        checkout = temporary_root / "checkout"
        repository = temporary_root / "repository.fossil"
        environment = {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "USER": "oracle",
            "PATH": os.environ.get("PATH", ""),
            "LC_ALL": "C",
            "LANG": "C",
            "TZ": "UTC",
        }
        setup_results = [
            _invoke(
                [fossil, "init", "--admin-user", "oracle", str(repository)],
                cwd=temporary_root,
                environment=environment,
            ),
            _invoke(
                [fossil, "open", "--nosync", "--workdir", str(checkout), str(repository)],
                cwd=temporary_root,
                environment=environment,
            ),
        ]
        setup = case["setup"]
        for relative, contents in setup.get("files", {}).items():
            path = checkout / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8")
        if setup.get("global_ignore_glob") is not None:
            setup_results.append(
                _invoke(
                    [
                        fossil,
                        "settings",
                        "ignore-glob",
                        setup["global_ignore_glob"],
                        "--global",
                    ],
                    cwd=checkout,
                    environment=environment,
                )
            )
        local_ignore_glob = setup.get("local_ignore_glob", setup.get("ignore_glob"))
        if local_ignore_glob is not None:
            setup_results.append(
                _invoke(
                    [fossil, "settings", "ignore-glob", local_ignore_glob],
                    cwd=checkout,
                    environment=environment,
                )
            )
        if setup.get("versioned_ignore_glob") is not None:
            settings_path = checkout / ".fossil-settings" / "ignore-glob"
            settings_path.parent.mkdir(parents=True)
            settings_path.write_text(setup["versioned_ignore_glob"], encoding="utf-8")
            setup_results.append(
                _invoke(
                    [fossil, "add", "--dotfiles", ".fossil-settings/ignore-glob"],
                    cwd=checkout,
                    environment=environment,
                )
            )
            setup_results.append(
                _invoke(
                    [fossil, "commit", "--no-warnings", "-m", "version ignore fixture"],
                    cwd=checkout,
                    environment=environment,
                )
            )
            (checkout / ".fossil-settings" / "ignore-glob.no-warn").touch()
        setup_failed = any(result.returncode != 0 for result in setup_results)
        probe_results: list[dict[str, Any]] = []
        for probe in setup.get("probes", []):
            value = probe["value"]
            result = _invoke(
                [fossil, "settings", "ignore-glob", value], cwd=checkout, environment=environment
            )
            query = probe["query"]
            _write_target(checkout, query)
            extras_result = _invoke(
                [fossil, "extras", "--dotfiles", "--rel-paths"],
                cwd=checkout,
                environment=environment,
            )
            listed = sorted(
                line.removeprefix("./")
                for line in extras_result.stdout.decode("utf-8", errors="replace").splitlines()
                if line
            )
            probe_results.append(
                {
                    "value": value,
                    "query": query,
                    "exit_code": result.returncode,
                    "stderr": result.stderr.decode("utf-8", errors="replace"),
                    "extras_exit_code": extras_result.returncode,
                    "observed_ignored": query not in listed,
                    "listed_paths": listed,
                }
            )

        query = case.get("query")
        observed_ignored: bool | None = None
        extras: dict[str, Any] | None = None
        if query is not None:
            _write_target(checkout, query)
            command = [fossil, "extras", "--dotfiles", "--rel-paths"]
            result = _invoke(command, cwd=checkout, environment=environment)
            listed = sorted(
                line.removeprefix("./")
                for line in result.stdout.decode("utf-8", errors="replace").splitlines()
                if line
            )
            observed_ignored = query not in listed
            extras = {
                "command": ["fossil", "extras", "--dotfiles", "--rel-paths"],
                "exit_code": result.returncode,
                "listed_paths": listed,
                "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
                "stderr": result.stderr.decode("utf-8", errors="replace"),
            }
        expected = case.get("expected_candidate")
        candidate_matches = observed_ignored == expected if isinstance(expected, bool) else None
        return {
            "id": case["id"],
            "dimension": case["dimension"],
            "evidence_status": case["evidence_status"],
            "native_status": "captured",
            "expected_candidate": expected,
            "observed_ignored": observed_ignored,
            "candidate_matches": candidate_matches,
            "query": query,
            "extras": extras,
            "setting_probes": probe_results,
            "setup_exit_codes": [result.returncode for result in setup_results],
            "setup_failed": setup_failed,
        }


def capture(cases_path: Path, output_path: Path, fossil_name: str) -> int:
    cases_data = json.loads(cases_path.read_text(encoding="utf-8"))
    fossil = shutil.which(fossil_name)
    if fossil is None:
        result: dict[str, Any] = {
            "schema_version": 1,
            "status": "skipped",
            "reason": f"Fossil executable not found: {fossil_name}",
            "client": None,
            "cases": [],
        }
    else:
        version_result = _invoke([fossil, "version"], cwd=Path.cwd(), environment=os.environ)
        version = version_result.stdout.decode("utf-8", errors="replace").splitlines()[0]
        captured = [_capture_case(case, fossil) for case in cases_data["cases"]]
        failed = any(case["setup_failed"] for case in captured) or any(
            (case["extras"] is not None and case["extras"]["exit_code"] != 0)
            or any(probe["extras_exit_code"] != 0 for probe in case["setting_probes"])
            for case in captured
        )
        result = {
            "schema_version": 1,
            "status": "failed" if failed else "captured",
            "client": {
                "fossil": {"executable": fossil, "version": version},
                "platform": platform.platform(),
                "runner_python": sys.version.split()[0],
            },
            "cases": captured,
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    cases = result["cases"]
    candidates = [case for case in cases if case["candidate_matches"] is not None]
    matches = sum(bool(case["candidate_matches"]) for case in candidates)
    print(f"Captured {len(cases)} Fossil cases: {result['status']}")
    print(f"Boolean candidates matching: {matches}/{len(candidates)}")
    print(f"Capture: {output_path}")
    return 1 if result["status"] == "failed" else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("cases.json"))
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).with_name("capture.local.json")
    )
    parser.add_argument("--fossil", default="fossil", help="Fossil executable")
    args = parser.parse_args(argv)
    return capture(args.cases, args.output, args.fossil)


if __name__ == "__main__":
    raise SystemExit(main())
