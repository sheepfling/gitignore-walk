"""Client-independent tests for Subversion property discovery contracts."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from gitignore_walk import (
    SubversionIgnoreError,
    SubversionIgnorePolicy,
    SubversionPolicyConfig,
    SubversionPolicySelection,
    select_policy,
)
from gitignore_walk._schemes.subversion import _config
from gitignore_walk._schemes.subversion._glob import (
    matches_svn_glob,
    split_svn_property_patterns,
)

INFO_XML = b"<info><entry><wc-info><wcroot-abspath>{root}</wcroot-abspath></wc-info></entry></info>"
PROPLIST_XML = b"""<properties><target path=".">
<property name="svn:ignore">*.tmp</property>
</target><target path="pkg">
<property name="svn:global-ignores">*.cache</property>
</target></properties>"""
_MACHINE_HIVE = object()
_USER_HIVE = object()


@pytest.mark.parametrize(
    ("pattern", "name", "expected"),
    [
        (r"\a", "a", True),
        (r"\*", "*", True),
        ("[!a]", "x", True),
        ("[!a]", "a", False),
        ("[^a]", "x", True),
        ("[^a]", "a", False),
        ("file[", "file[", True),
        ("[[:digit:]]", "1", False),
    ],
)
def test_subversion_glob_matches_observed_apr_forms(
    pattern: str, name: str, expected: bool
) -> None:
    assert matches_svn_glob(name, pattern) is expected


def test_subversion_property_patterns_split_only_cr_and_lf() -> None:
    assert split_svn_property_patterns("first\r\nsecond\rthird\n") == (
        "first",
        "second",
        "third",
    )
    assert split_svn_property_patterns("two words\tremain\vone pattern\u2028still data") == (
        "two words\tremain\vone pattern\u2028still data",
    )


def _install_fake_winreg(
    monkeypatch: pytest.MonkeyPatch,
    values: dict[tuple[object, str, str], object],
    *,
    unreadable: set[tuple[object, str]] | None = None,
) -> None:
    """Install a small ``winreg`` fake for platform-independent config tests."""
    registry = ModuleType("winreg")
    machine_hive = _MACHINE_HIVE
    user_hive = _USER_HIVE

    class RegistryKey:
        def __init__(self, hive: object, path: str) -> None:
            self.identity = (hive, path)

        def __enter__(self) -> tuple[object, str]:
            return self.identity

        def __exit__(self, *_exc: object) -> None:
            return None

    def open_key(hive: object, path: str) -> RegistryKey:
        identity = (hive, path)
        if identity in (unreadable or set()):
            raise PermissionError("registry access denied")
        if not any(key[:2] == identity for key in values):
            raise FileNotFoundError(path)
        return RegistryKey(hive, path)

    def query_value(key: tuple[object, str], name: str) -> tuple[object, int]:
        return values[(key[0], key[1], name)], 1

    registry.HKEY_LOCAL_MACHINE = machine_hive
    registry.HKEY_CURRENT_USER = user_hive
    registry.OpenKey = open_key
    registry.QueryValueEx = query_value
    monkeypatch.setitem(sys.modules, "winreg", registry)


def test_policy_parses_native_property_snapshot_without_a_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".svn").mkdir()
    commands: list[tuple[str, ...]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        del kwargs
        operation = command[2]
        commands.append(tuple(command))
        stdout = (
            INFO_XML.replace(b"{root}", str(tmp_path).encode())
            if operation == "info"
            else PROPLIST_XML
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr("gitignore_walk._schemes.subversion.policy.subprocess.run", run)
    policy = SubversionIgnorePolicy(tmp_path, environment={})

    decisions = policy.explain_many(["root.tmp", "pkg/deep/file.cache", "pkg/root.tmp"])
    assert [decision.ignored for decision in decisions] == [True, True, False]
    assert not decisions[0].discovery_complete
    expected_diagnostics = {"user-config-location-unknown"}
    if os.name == "nt":
        expected_diagnostics.add("system-config-location-unknown")
    assert {item.code for item in decisions[0].diagnostics} == expected_diagnostics
    assert [command[2] for command in commands] == [
        "info",
        "info",
        "proplist",
        "info",
        "proplist",
    ]


def test_policy_loads_inherited_global_ignores_above_the_working_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".svn").mkdir()
    source_url = "https://example.invalid/repo/trunk"
    inherited_xml = (
        '<properties><target path="'
        + source_url
        + '"><inherited_property name="svn:global-ignores">*.tmp</inherited_property>'
        "</target></properties>"
    ).encode()
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        del kwargs
        commands.append(command)
        operation = command[2]
        stdout = (
            INFO_XML.replace(b"{root}", str(tmp_path).encode())
            if operation == "info"
            else inherited_xml
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr("gitignore_walk._schemes.subversion.policy.subprocess.run", run)
    policy = SubversionIgnorePolicy(tmp_path, environment={})
    trace = policy.trace("root.tmp")

    assert trace.decision.ignored
    assert trace.decision.source == source_url
    assert trace.decision.property_name == "svn:global-ignores"
    assert trace.decision.scope == "."
    assert any("--show-inherited-props" in command for command in commands)


def test_explicit_runtime_config_patterns_keep_provenance_and_reach_svn_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".svn").mkdir()
    config_dir = tmp_path / "svn-config"
    config_dir.mkdir()
    config_file = config_dir / "config"
    config_file.write_text(
        "[miscellany]\nglobal-ignores = *.runtime-cache  *.runtime-temp\n", encoding="utf-8"
    )
    commands: list[tuple[str, ...]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        del kwargs
        operation = next(argument for argument in command if argument in ("info", "proplist"))
        commands.append(tuple(command))
        stdout = (
            INFO_XML.replace(b"{root}", str(tmp_path).encode())
            if operation == "info"
            else b"<properties/>"
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr("gitignore_walk._schemes.subversion.policy.subprocess.run", run)
    policy = SubversionIgnorePolicy(tmp_path, config_dir=config_dir, environment={})

    assert policy.explain("artifact.runtime-cache").ignored
    assert policy.trace("artifact.runtime-temp").decision.source == (
        f"Subversion runtime configuration: {config_file}"
    )
    assert policy.trace("artifact.runtime-temp").complete
    assert [
        next(argument for argument in command if argument in ("info", "proplist"))
        for command in commands
    ] == ["info", "info", "proplist", "info", "proplist", "info", "proplist", "info", "proplist"]
    for command in commands:
        config_dir_index = command.index("--config-dir")
        assert command[config_dir_index + 1] == str(config_dir.resolve())


def test_malformed_runtime_config_reports_config_file_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".svn").mkdir()
    config_dir = tmp_path / "svn-config"
    config_dir.mkdir()
    config_file = config_dir / "config"
    config_file.write_text("[miscellany\nglobal-ignores = *.tmp\n", encoding="utf-8")

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        del kwargs
        if "info" in command:
            stdout = INFO_XML.replace(b"{root}", str(tmp_path).encode())
        elif "proplist" in command:
            stdout = b"<properties/>"
        else:
            stdout = b"<status/>"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr("gitignore_walk._schemes.subversion.policy.subprocess.run", run)

    with pytest.raises(SubversionIgnoreError, match="runtime configuration") as raised:
        SubversionIgnorePolicy(tmp_path, config_dir=config_dir, environment={})

    assert raised.value.operation == "config"
    assert raised.value.path == str(config_file)


@pytest.mark.skipif(os.name == "nt", reason="Tests Unix system and per-user config precedence")
def test_ambient_user_config_overrides_system_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system_config = tmp_path / "system" / "config"
    user_config = tmp_path / "home" / ".subversion" / "config"
    system_config.parent.mkdir()
    user_config.parent.mkdir(parents=True)
    system_config.write_text("[miscellany]\nglobal-ignores = *.system-hide\n", encoding="utf-8")
    user_config.write_text("[miscellany]\nglobal-ignores = *.user-hide\n", encoding="utf-8")
    monkeypatch.setattr(_config, "_SYSTEM_CONFIG_FILE", system_config)

    runtime = _config.load_runtime_global_ignores(
        config_dir=None,
        environment={"HOME": str(user_config.parents[1])},
        default_patterns=("*.default-hide",),
    )

    assert runtime.patterns == ("*.user-hide",)
    assert runtime.source == f"Subversion runtime configuration: {user_config}"
    assert runtime.discovery_complete
    assert not runtime.diagnostics


def test_ambient_windows_config_paths() -> None:
    config_files, complete, diagnostics = _config._ambient_config_files(
        {"PROGRAMDATA": "/machine-data", "APPDATA": "/user-data"}, windows=True
    )

    assert config_files == (
        Path("/machine-data/Subversion/config"),
        Path("/user-data/Subversion/config"),
    )
    assert complete
    assert not diagnostics


def test_windows_registry_and_file_config_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = r"Software\Tigris.org\Subversion\Config\Miscellany"
    _install_fake_winreg(
        monkeypatch,
        {
            (_MACHINE_HIVE, key, "global-ignores"): "*.machine-registry",
            (_USER_HIVE, key, "global-ignores"): "*.user-registry",
        },
    )
    machine_file = tmp_path / "machine" / "Subversion" / "config"
    user_file = tmp_path / "user" / "Subversion" / "config"
    machine_file.parent.mkdir(parents=True)
    user_file.parent.mkdir(parents=True)
    machine_file.write_text("[miscellany]\nglobal-ignores = *.machine-file\n", encoding="utf-8")
    user_file.write_text("[miscellany]\nglobal-ignores = *.user-file\n", encoding="utf-8")

    environment = {
        "PROGRAMDATA": str(tmp_path / "machine"),
        "APPDATA": str(tmp_path / "user"),
    }

    runtime = _config.load_runtime_global_ignores(
        config_dir=None,
        environment=environment,
        default_patterns=("*.default",),
        windows=True,
    )

    assert runtime.patterns == ("*.user-file",)
    assert runtime.source == f"Subversion runtime configuration: {user_file}"
    assert runtime.discovery_complete
    assert not runtime.diagnostics

    user_file.unlink()
    runtime = _config.load_runtime_global_ignores(
        config_dir=None,
        environment=environment,
        default_patterns=("*.default",),
        windows=True,
    )
    assert runtime.patterns == ("*.user-registry",)
    assert "HKEY_CURRENT_USER" in runtime.source

    _install_fake_winreg(
        monkeypatch,
        {(_MACHINE_HIVE, key, "global-ignores"): "*.machine-registry"},
    )
    runtime = _config.load_runtime_global_ignores(
        config_dir=None,
        environment=environment,
        default_patterns=("*.default",),
        windows=True,
    )
    assert runtime.patterns == ("*.machine-file",)
    assert runtime.source == f"Subversion runtime configuration: {machine_file}"


def test_windows_registry_is_used_when_config_files_are_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = r"Software\Tigris.org\Subversion\Config\Miscellany"
    _install_fake_winreg(
        monkeypatch,
        {(_USER_HIVE, key, "global-ignores"): "*.registry-ignore"},
    )

    runtime = _config.load_runtime_global_ignores(
        config_dir=None,
        environment={"PROGRAMDATA": "C:/ProgramData", "APPDATA": "C:/Users/test/AppData"},
        default_patterns=("*.default",),
        windows=True,
    )

    assert runtime.patterns == ("*.registry-ignore",)
    assert runtime.source == (
        "Subversion runtime configuration registry: HKEY_CURRENT_USER\\"
        r"Software\Tigris.org\Subversion\Config\Miscellany"
    )
    assert runtime.discovery_complete
    assert not runtime.diagnostics


def test_windows_registry_access_failure_is_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = r"Software\Tigris.org\Subversion\Config\Miscellany"
    _install_fake_winreg(
        monkeypatch,
        {},
        unreadable={(_MACHINE_HIVE, key)},
    )

    runtime = _config.load_runtime_global_ignores(
        config_dir=None,
        environment={"PROGRAMDATA": "C:/ProgramData", "APPDATA": "C:/Users/test/AppData"},
        default_patterns=("*.default",),
        windows=True,
    )

    assert runtime.patterns == ("*.default",)
    assert not runtime.discovery_complete
    assert [diagnostic.code for diagnostic in runtime.diagnostics] == [
        "registry-config-read-failed"
    ]


def test_explicit_empty_runtime_setting_disables_builtin_global_ignores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".svn").mkdir()
    config_dir = tmp_path / "svn-config"
    config_dir.mkdir()
    (config_dir / "config").write_text("[miscellany]\nglobal-ignores =\n", encoding="utf-8")

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        del kwargs
        stdout = (
            INFO_XML.replace(b"{root}", str(tmp_path).encode())
            if "info" in command
            else b"<properties/>"
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr("gitignore_walk._schemes.subversion.policy.subprocess.run", run)
    policy = SubversionIgnorePolicy(tmp_path, config_dir=config_dir, environment={})

    assert not policy.is_ignored("image.pyc")


def test_selector_builds_the_tagged_subversion_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".svn").mkdir()

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        del kwargs
        stdout = (
            INFO_XML.replace(b"{root}", str(tmp_path).encode())
            if "info" in command
            else b"<properties/>"
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr("gitignore_walk._schemes.subversion.policy.subprocess.run", run)
    config_dir = tmp_path / "svn-config"
    config_dir.mkdir()
    selection = select_policy(
        tmp_path,
        SubversionPolicyConfig(config_dir=config_dir, environment={}, membership_aware=True),
    )

    assert isinstance(selection, SubversionPolicySelection)
    assert selection.mode == "subversion"
    assert selection.backend == "subversion-native-properties"
    assert selection.fallback_reason is None
    assert isinstance(selection.policy, SubversionIgnorePolicy)
    assert selection.policy.config_dir == config_dir.resolve()
    assert selection.policy.membership_aware


def test_native_property_discovery_errors_keep_operation_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".svn").mkdir()

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        del kwargs
        if command[2] == "info":
            stdout = INFO_XML.replace(b"{root}", str(tmp_path).encode())
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")
        return subprocess.CompletedProcess(command, 1, stdout=b"", stderr=b"property read failed")

    monkeypatch.setattr("gitignore_walk._schemes.subversion.policy.subprocess.run", run)

    with pytest.raises(SubversionIgnoreError, match="property read failed") as raised:
        SubversionIgnorePolicy(tmp_path, environment={})

    assert raised.value.operation == "proplist"
    assert raised.value.path == str(tmp_path)
