"""Subversion runtime global-ignore configuration discovery."""

from __future__ import annotations

import configparser
import importlib
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..._policy import IgnoreDiagnostic
from .errors import SubversionIgnoreError

_SYSTEM_CONFIG_FILE = Path("/etc/subversion/config")


@dataclass(frozen=True, slots=True)
class _RuntimeGlobalIgnores:
    """Effective supported global-ignore setting and its discovery state."""

    patterns: tuple[str, ...]
    source: str
    discovery_complete: bool
    diagnostics: tuple[IgnoreDiagnostic, ...]


def load_runtime_global_ignores(
    *,
    config_dir: Path | None,
    environment: Mapping[str, str],
    default_patterns: Sequence[str],
    windows: bool | None = None,
) -> _RuntimeGlobalIgnores:
    """Load explicit or ambient config in Subversion's source precedence order.

    On Windows the merge order is machine Registry, machine INI, user Registry, user INI.
    An explicit config directory replaces all ambient config discovery.
    """
    patterns = tuple(default_patterns)
    source = "Subversion built-in global-ignores defaults"
    complete = True
    diagnostics: list[IgnoreDiagnostic] = []

    if config_dir is not None:
        config_files = (config_dir / "config",)
        windows = False
    else:
        windows = os.name == "nt" if windows is None else windows
        config_files, complete, diagnostics = _ambient_config_files(environment, windows=windows)

    registry_settings: dict[str, tuple[str, str]] = {}
    if windows:
        registry_settings, registry_complete, registry_diagnostics = (
            _windows_registry_global_ignores()
        )
        complete = complete and registry_complete
        diagnostics.extend(registry_diagnostics)

    if windows:
        config_sources = (
            ("machine", config_files[0] if config_files else None),
            ("user", config_files[1] if len(config_files) > 1 else None),
        )
    else:
        config_sources = (("file", path) for path in config_files)

    for scope, config_file in config_sources:
        registry_setting = registry_settings.get(scope)
        if registry_setting is not None:
            registry_source, registry_value = registry_setting
            patterns = tuple(registry_value.split())
            source = registry_source
        if config_file is None:
            continue
        if not config_file.exists():
            continue
        try:
            parser = configparser.ConfigParser(interpolation=None)
            with config_file.open(encoding="utf-8") as stream:
                parser.read_file(stream)
            if parser.has_option("miscellany", "global-ignores"):
                patterns = tuple(parser.get("miscellany", "global-ignores").split())
                source = f"Subversion runtime configuration: {config_file}"
        except (configparser.Error, OSError, UnicodeError) as error:
            raise SubversionIgnoreError(
                f"Unable to read Subversion runtime configuration: {error}",
                operation="config",
                path=str(config_file),
            ) from error

    return _RuntimeGlobalIgnores(patterns, source, complete, tuple(diagnostics))


def _ambient_config_files(
    environment: Mapping[str, str],
    *,
    windows: bool | None = None,
) -> tuple[tuple[Path, ...], bool, list[IgnoreDiagnostic]]:
    """Return ambient system-to-user INI paths from the supplied environment."""
    values = {name.casefold(): value for name, value in environment.items()}
    diagnostics: list[IgnoreDiagnostic] = []
    complete = True
    config_files: list[Path] = []

    if windows is None:
        windows = os.name == "nt"
    if windows:
        common_data = values.get("programdata") or values.get("allusersprofile")
        if common_data:
            config_files.append(Path(common_data) / "Subversion" / "config")
        else:
            complete = False
            diagnostics.append(
                IgnoreDiagnostic(
                    code="system-config-location-unknown",
                    message=(
                        "PROGRAMDATA is not set, so the system Subversion config was not located."
                    ),
                    source="Subversion system configuration",
                )
            )
        app_data = values.get("appdata")
        if app_data:
            config_files.append(Path(app_data) / "Subversion" / "config")
        else:
            complete = False
            diagnostics.append(
                IgnoreDiagnostic(
                    code="user-config-location-unknown",
                    message="APPDATA is not set, so the user Subversion config was not located.",
                    source="Subversion per-user configuration",
                )
            )
        return tuple(config_files), complete, diagnostics

    config_files.append(_SYSTEM_CONFIG_FILE)
    home = values.get("home")
    if home:
        config_files.append(Path(home) / ".subversion" / "config")
    else:
        complete = False
        diagnostics.append(
            IgnoreDiagnostic(
                code="user-config-location-unknown",
                message=(
                    "HOME is not set, so the per-user Subversion config file could not be "
                    "located; pass config_dir or set HOME in the supplied environment."
                ),
                source="Subversion per-user configuration",
            )
        )
    return tuple(config_files), complete, diagnostics


def _windows_registry_global_ignores() -> tuple[
    dict[str, tuple[str, str]], bool, list[IgnoreDiagnostic]
]:
    """Read machine and user ``global-ignores`` registry values, when available."""
    try:
        winreg = importlib.import_module("winreg")
    except ImportError as error:
        return (
            {},
            False,
            [
                IgnoreDiagnostic(
                    code="registry-config-unavailable",
                    message=f"Unable to access Windows Subversion registry settings: {error}",
                    source="Windows Subversion configuration registry",
                )
            ],
        )

    registry_values: dict[str, tuple[str, str]] = {}
    diagnostics: list[IgnoreDiagnostic] = []
    complete = True
    registry_key = r"Software\Tigris.org\Subversion\Config\Miscellany"
    for scope, hive_name in (
        ("machine", "HKEY_LOCAL_MACHINE"),
        ("user", "HKEY_CURRENT_USER"),
    ):
        hive = getattr(winreg, hive_name)
        try:
            with winreg.OpenKey(hive, registry_key) as key:
                value, _value_type = winreg.QueryValueEx(key, "global-ignores")
        except FileNotFoundError:
            continue
        except OSError as error:
            complete = False
            diagnostics.append(
                IgnoreDiagnostic(
                    code="registry-config-read-failed",
                    message=f"Unable to read {hive_name} Subversion settings: {error}",
                    source=f"{hive_name}\\{registry_key}",
                )
            )
            continue
        if not isinstance(value, str):
            complete = False
            diagnostics.append(
                IgnoreDiagnostic(
                    code="registry-config-invalid-value",
                    message=f"{hive_name} Subversion global-ignores must be a string value.",
                    source=f"{hive_name}\\{registry_key}\\global-ignores",
                )
            )
            continue
        registry_values[scope] = (
            f"Subversion runtime configuration registry: {hive_name}\\{registry_key}",
            value,
        )
    return registry_values, complete, diagnostics
