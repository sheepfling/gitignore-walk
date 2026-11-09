"""Compare ambient Windows Registry settings with native Subversion status."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import tempfile
import winreg
import xml.etree.ElementTree as ET
from contextlib import suppress
from pathlib import Path
from typing import Any

from gitignore_walk import SubversionIgnorePolicy

_REGISTRY_ROOT = r"Software\Tigris.org\Subversion\Config\Miscellany"
_VALUE_NAME = "global-ignores"
_PROBE_PATTERN = "*.codex-registry-probe"


def _run(command: list[str], *, cwd: Path, environment: dict[str, str]) -> bytes:
    result = subprocess.run(
        command, cwd=cwd, env=environment, capture_output=True, timeout=60, check=False
    )
    if result.returncode:
        raise RuntimeError(
            f"native SVN command failed ({result.returncode}): {command!r}\n"
            f"stdout={result.stdout.decode(errors='replace')}\n"
            f"stderr={result.stderr.decode(errors='replace')}"
        )
    return result.stdout


def _status_item(status_xml: bytes, path: str) -> str | None:
    document = ET.fromstring(status_xml)
    for entry in document.findall(".//entry"):
        if Path(entry.attrib["path"]).name == path:
            status = entry.find("wc-status")
            if status is not None:
                return status.attrib.get("item")
    return None


class _RegistryOverride:
    """Temporarily set one HKCU value and restore the key tree afterwards."""

    def __init__(self, value: str) -> None:
        self.value = value
        self.previous: tuple[Any, int] | None = None
        self.created_keys: list[str] = []

    def __enter__(self) -> _RegistryOverride:
        parent = ""
        for component in _REGISTRY_ROOT.split("\\"):
            parent = f"{parent}\\{component}" if parent else component
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, parent):
                    continue
            except FileNotFoundError:
                self.created_keys.append(parent)
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, _REGISTRY_ROOT, access=winreg.KEY_READ | winreg.KEY_WRITE
        ) as key:
            try:
                self.previous = winreg.QueryValueEx(key, _VALUE_NAME)
            except FileNotFoundError:
                self.previous = None
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, self.value)
        return self

    def __exit__(self, *_exc: object) -> None:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _REGISTRY_ROOT, access=winreg.KEY_READ | winreg.KEY_WRITE
        ) as key:
            if self.previous is None:
                with suppress(FileNotFoundError):
                    winreg.DeleteValue(key, _VALUE_NAME)
            else:
                value, value_type = self.previous
                winreg.SetValueEx(key, _VALUE_NAME, 0, value_type, value)
        for path in reversed(self.created_keys):
            with suppress(OSError):
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)


def capture(output: Path, *, allow_registry_mutation: bool) -> dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("the Windows Registry oracle can only run on Windows")
    if not allow_registry_mutation:
        raise RuntimeError("pass --allow-registry-mutation to opt into the temporary HKCU probe")
    svn = shutil.which("svn")
    svnadmin = shutil.which("svnadmin")
    if svn is None or svnadmin is None:
        raise FileNotFoundError("svn and svnadmin must be available on PATH")

    with tempfile.TemporaryDirectory(prefix="gitignore-walk-svn-registry-") as temporary:
        root = Path(temporary)
        appdata = root / "appdata"
        programdata = root / "programdata"
        appdata.mkdir()
        programdata.mkdir()
        environment = os.environ.copy()
        environment.update(
            {
                "APPDATA": str(appdata),
                "PROGRAMDATA": str(programdata),
                "HOME": str(root / "home"),
                "LC_ALL": "C",
                "LANG": "C",
            }
        )
        repository = root / "repository"
        working_copy = root / "working-copy"
        _run([svnadmin, "create", str(repository)], cwd=root, environment=environment)
        repository_url = repository.as_uri()
        _run(
            [svn, "mkdir", f"{repository_url}/trunk", "-m", "init"],
            cwd=root,
            environment=environment,
        )
        _run(
            [svn, "checkout", f"{repository_url}/trunk", str(working_copy)],
            cwd=root,
            environment=environment,
        )
        registry_candidate_name = "registry.codex-registry-probe"
        registry_candidate = working_copy / registry_candidate_name
        registry_candidate.write_text("registry probe\n", encoding="utf-8")

        with _RegistryOverride(_PROBE_PATTERN):
            policy = SubversionIgnorePolicy(working_copy, environment=environment)
            registry_decision = policy.explain(registry_candidate)
            registry_native_xml = _run(
                [svn, "status", "--xml", "--no-ignore"],
                cwd=working_copy,
                environment=environment,
            )
            registry_native_item = _status_item(registry_native_xml, registry_candidate_name)

            user_config = appdata / "Subversion" / "config"
            user_config.parent.mkdir(parents=True)
            user_config.write_text("[miscellany]\nglobal-ignores = *.file-only\n", encoding="utf-8")
            overridden_candidate_name = "overridden.codex-registry-probe"
            file_candidate_name = "selected.file-only"
            (working_copy / overridden_candidate_name).write_text(
                "registry override probe\n", encoding="utf-8"
            )
            (working_copy / file_candidate_name).write_text("user file probe\n", encoding="utf-8")
            file_policy = SubversionIgnorePolicy(working_copy, environment=environment)
            overridden_decision = file_policy.explain(overridden_candidate_name)
            file_decision = file_policy.explain(file_candidate_name)
            file_native_xml = _run(
                [svn, "status", "--xml", "--no-ignore"],
                cwd=working_copy,
                environment=environment,
            )
            overridden_native_item = _status_item(file_native_xml, overridden_candidate_name)
            file_native_item = _status_item(file_native_xml, file_candidate_name)
            result = {
                "schema_version": 1,
                "status": "captured",
                "client": {
                    "svn": {
                        "executable": svn,
                        "version": subprocess.run(
                            [svn, "--version", "--quiet"],
                            capture_output=True,
                            text=True,
                            check=True,
                        ).stdout.strip(),
                    },
                    "platform": platform.platform(),
                },
                "registry": {
                    "hive": "HKEY_CURRENT_USER",
                    "key": _REGISTRY_ROOT,
                    "value": _VALUE_NAME,
                    "probe_pattern": _PROBE_PATTERN,
                    "registry_only": {
                        "native_status_item": registry_native_item,
                        "policy_ignored": registry_decision.ignored,
                        "policy_source": registry_decision.source,
                    },
                    "user_ini_override": {
                        "native_registry_pattern_status_item": overridden_native_item,
                        "policy_registry_pattern_ignored": overridden_decision.ignored,
                        "native_file_pattern_status_item": file_native_item,
                        "policy_file_pattern_ignored": file_decision.ignored,
                        "policy_source": file_decision.source,
                    },
                    "policy_discovery_complete": file_decision.discovery_complete,
                },
                "candidate_matches": (
                    registry_native_item == "ignored"
                    and registry_decision.ignored
                    and "HKEY_CURRENT_USER" in (registry_decision.source or "")
                    and registry_decision.discovery_complete
                    and overridden_native_item == "unversioned"
                    and not overridden_decision.ignored
                    and file_native_item == "ignored"
                    and file_decision.ignored
                    and file_decision.discovery_complete
                ),
                "native_status_xml": file_native_xml.decode("utf-8", errors="backslashreplace"),
            }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not result["candidate_matches"]:
        raise AssertionError(f"policy/native Registry behavior did not match: {result}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--allow-registry-mutation",
        action="store_true",
        help="temporarily set and restore the current user's Subversion ignore Registry value",
    )
    args = parser.parse_args()
    capture(args.output, allow_registry_mutation=args.allow_registry_mutation)
    print(f"Captured Windows Registry/Subversion match: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
