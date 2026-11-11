"""Run Breezy source-precedence probes on an additional native client profile."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

try:
    from .run import _capture_profile_name, _invoke, capture
except ImportError:  # pragma: no cover - direct script execution from the repository root
    from run import _capture_profile_name, _invoke, capture

SOURCE_PRECEDENCE_CASES = {
    "brz.global-ignore-over-local-ignore": "*.tmp",
    "brz.local-ignore-over-default-ignore": "*.py[co]",
    "brz.global-ignore-over-default-ignore": "module.*",
}


def _cases_for_profile(cases_data: Mapping[str, Any], profile: str) -> dict[str, Any]:
    """Copy the oracle corpus and enable its three source-order probes for one profile."""
    copied = json.loads(json.dumps(cases_data))
    selected = {case["id"] for case in copied["cases"]}
    if not set(SOURCE_PRECEDENCE_CASES) <= selected:
        raise ValueError("Breezy corpus is missing a source-precedence case")
    for case in copied["cases"]:
        if case["id"] in SOURCE_PRECEDENCE_CASES:
            profiles = case.setdefault("capture_profiles", [])
            if profile not in profiles:
                profiles.append(profile)
    return copied


def run_source_precedence(brz: str, output: Path) -> int:
    """Capture source-precedence decisions on the installed Breezy profile."""
    version = _invoke([brz, "--version"], cwd=Path.cwd(), environment=os.environ)
    lines = version.stdout.splitlines()
    profile = _capture_profile_name(lines[0] if lines else "")
    if version.returncode != 0 or profile is None:
        raise RuntimeError("could not identify the installed Breezy capture profile")

    cases_path = Path(__file__).with_name("cases.json")
    cases_data = json.loads(cases_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="gitignore-walk-brz-source-order-") as temporary:
        scoped_cases_path = Path(temporary) / "cases.json"
        scoped_cases_path.write_text(
            json.dumps(_cases_for_profile(cases_data, profile), indent=2) + "\n",
            encoding="utf-8",
        )
        result = capture(scoped_cases_path, output, brz)
    if result != 0:
        return result

    captured = json.loads(output.read_text(encoding="utf-8"))
    observations = {case["id"]: case for case in captured["cases"]}
    for case_id, pattern in SOURCE_PRECEDENCE_CASES.items():
        observation = observations.get(case_id)
        if observation is None or observation["observed_pattern"] != pattern:
            raise AssertionError(
                f"{profile}: {case_id} expected winning pattern {pattern!r}, "
                f"observed {None if observation is None else observation['observed_pattern']!r}"
            )
        if observation["winning_pattern_matches"] is not True:
            raise AssertionError(f"{profile}: {case_id} did not match its expected winner")
    print(f"Breezy source-precedence profile: {profile}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brz", default="brz", help="Breezy executable")
    parser.add_argument("--output", type=Path, required=True, help="capture destination")
    arguments = parser.parse_args()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    return run_source_precedence(arguments.brz, arguments.output)


if __name__ == "__main__":
    raise SystemExit(main())
