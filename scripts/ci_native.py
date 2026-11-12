"""Run native oracle captures with explicit prerequisites and a durable result summary."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

BACKENDS = ("hg", "svn", "fossil", "brz", "darcs", "p4")
OPTIONAL_BACKENDS = ("compat", "svn-config")
KNOWN_BACKENDS = (*BACKENDS, *OPTIONAL_BACKENDS)
REQUIRED_TOOLS = {
    "hg": ("hg",),
    # svnserve only enables protocol-based external fixtures; the runner records those as explicit
    # case-level skips when the server is unavailable.
    "svn": ("svn", "svnadmin"),
    "fossil": ("fossil",),
    "brz": ("brz",),
    "darcs": ("darcs",),
    "p4": ("p4", "p4d"),
    # Sapling's Git-storage mode uses Git to initialize disposable workspaces.
    "compat": ("git", "sl", "jj"),
    "svn-config": ("docker",),
}


def require_tools(
    backends: Sequence[str],
    *,
    include_git: bool = False,
    sl: str = "sl",
    jj: str = "jj",
) -> None:
    """Reject missing selected clients instead of turning a skipped oracle into success."""
    if not backends:
        raise ValueError("select at least one native backend")
    unknown = set(backends) - set(KNOWN_BACKENDS)
    if unknown:
        raise ValueError(f"unknown native backends: {', '.join(sorted(unknown))}")
    required = {tool for backend in backends for tool in REQUIRED_TOOLS[backend]}
    if include_git:
        required.add("git")
    executable_overrides = {"sl": sl, "jj": jj}
    missing = sorted(
        tool for tool in required if shutil.which(executable_overrides.get(tool, tool)) is None
    )
    if missing:
        raise RuntimeError("native CI requires these executables on PATH: " + ", ".join(missing))


def capture_arguments(
    backend: str,
    directory: Path,
    *,
    include_trust: bool = False,
    sl: str = "sl",
    jj: str = "jj",
) -> tuple[list[str], list[Path]]:
    output = directory / f"{backend}-oracle.json"
    arguments = [f"oracle-{backend}", "--output", str(output)]
    outputs = [output]
    if backend == "hg":
        walk = directory / "hg-walk-oracle.json"
        trust = directory / "hg-trust-oracle.json"
        sparse_refresh = directory / "hg-sparse-refresh-oracle.json"
        arguments.extend(
            [
                "--walk-output",
                str(walk),
                "--trust-output",
                str(trust),
                "--sparse-refresh-output",
                str(sparse_refresh),
            ]
        )
        outputs.extend([walk, trust, sparse_refresh])
        if not include_trust:
            arguments.append("--skip-trust")
    elif backend == "svn":
        outputs.append(directory / "svn-oracle.transitions.json")
    elif backend == "fossil":
        membership = directory / "fossil-membership-oracle.json"
        arguments.extend(["--membership-output", str(membership)])
        outputs.append(membership)
    elif backend == "compat":
        if sl != "sl":
            arguments.extend(["--sl", sl])
        if jj != "jj":
            arguments.extend(["--jj", jj])
    return arguments, outputs


def _case_failed(case: dict[str, Any]) -> bool:
    if case.get("native_status") == "skipped":
        return False
    expected = case.get("expected_candidate")
    if isinstance(expected, dict):
        expected = expected.get("ignored")
    closed = isinstance(expected, bool) or any(
        case.get(key) is not None for key in ("expected_ignored_paths", "expected_unknown_paths")
    )
    if (
        case.get("candidate_matches") is False
        or case.get("ignore_check_matches") is False
        or (closed and case.get("candidate_matches") is not True)
    ):
        return True
    # Breezy can otherwise mistake empty output from failed queries for "not ignored".
    # Open malformed-pattern probes intentionally have nonzero query exits.
    if closed and any(case.get(key, 0) != 0 for key in ("ignored_exit_code", "status_exit_code")):
        return True
    expected_boring = case.get("expected_boring")
    return expected_boring is not None and expected_boring != case.get("observed_boring")


def inspect_capture(path: Path, *, allow_skip: bool = False) -> dict[str, Any]:
    """Check fresh capture status and comparisons, preserving explicit case-level skips."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("capture must be an object")
        cases = data.get("cases")
        if cases is None and "candidate_matches" in data:
            cases = [
                {
                    "id": data.get("id", path.stem),
                    "candidate_matches": data["candidate_matches"],
                    "expected_ignored_paths": data.get("expected_ignored_paths"),
                }
            ]
        if cases is None:
            cases = []
        if not isinstance(cases, list) or any(not isinstance(case, dict) for case in cases):
            raise ValueError("capture cases must be objects")
        if not allow_skip and not cases:
            raise ValueError("primary capture contains no cases")
        mismatches = [case.get("id") for case in cases if _case_failed(case)]
        status = data.get("status")
        passed = (status == "captured" or (allow_skip and status == "skipped")) and not mismatches
        client = data.get("client") or data.get("clients")
        client_platform = client.get("platform") if isinstance(client, dict) else None
        return {
            "file": str(path),
            "status": status,
            "passed": passed,
            "reason": data.get("reason"),
            "case_count": len(cases),
            "skipped_cases": [
                case.get("id") for case in cases if case.get("native_status") == "skipped"
            ],
            "mismatches": mismatches,
            "client": client,
            "platform": data.get("platform") or client_platform,
        }
    except (OSError, ValueError) as error:
        return {"file": str(path), "status": "invalid", "passed": False, "reason": str(error)}


def run_native(
    root: Path,
    backends: Sequence[str],
    output_dir: Path,
    *,
    include_trust: bool = False,
    sl: str = "sl",
    jj: str = "jj",
) -> int:
    """Run every selected backend even after a failure, then return the combined outcome."""
    require_tools(backends, sl=sl, jj=jj)
    output_dir.mkdir(parents=True, exist_ok=True)
    # A fresh directory prevents a crashed command from reusing a previous successful capture.
    directory = Path(tempfile.mkdtemp(prefix="native-", dir=output_dir)).resolve()
    outcomes: list[dict[str, Any]] = []
    for backend in dict.fromkeys(backends):
        arguments, paths = capture_arguments(
            backend, directory, include_trust=include_trust, sl=sl, jj=jj
        )
        command = [sys.executable, "-m", "scripts.ci", *arguments]
        print(f"\n==> Native {backend}: {' '.join(command)}", flush=True)
        try:
            result = subprocess.run(command, cwd=root, check=False)
            exit_code = result.returncode
        except OSError as error:
            print(f"Could not start {backend}: {error}", file=sys.stderr)
            exit_code = 1
        captures = [
            inspect_capture(path, allow_skip=path.name == "hg-trust-oracle.json") for path in paths
        ]
        passed = exit_code == 0 and all(capture["passed"] for capture in captures)
        outcomes.append(
            {"backend": backend, "exit_code": exit_code, "passed": passed, "captures": captures}
        )
        print(f"{'PASSED' if passed else 'FAILED'}: Native {backend}", flush=True)
    skipped = any(
        capture.get("status") == "skipped" or capture.get("skipped_cases")
        for outcome in outcomes
        for capture in outcome["captures"]
    )
    passed = all(outcome["passed"] for outcome in outcomes)
    status = "passed_with_skips" if passed and skipped else "passed" if passed else "failed"
    summary = {
        "schema_version": 1,
        "status": status,
        "platform": platform.platform(),
        "python": sys.version,
        "backends": outcomes,
    }
    summary_path = directory / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"\nNative CI: {status}. Full results: {summary_path}", flush=True)
    for outcome in outcomes:
        for capture in outcome["captures"]:
            if capture.get("status") == "skipped" or capture.get("skipped_cases"):
                print(
                    f"Explicit skips in {capture['file']}: "
                    f"{capture.get('reason') or capture.get('skipped_cases')}",
                    flush=True,
                )
    return 0 if passed else 1
