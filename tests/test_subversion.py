"""Subversion property policy checked against native-client status fixtures."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Literal

import pytest

from gitignore_walk import IgnoreWalker, SubversionIgnorePolicy

ORACLE_ROOT = Path(__file__).parent / "oracles" / "svn"
CASES = json.loads((ORACLE_ROOT / "cases.json").read_text(encoding="utf-8"))["cases"]
APR_GLOB_CASES = [case for case in CASES if case["dimension"].startswith("apr-glob-")]
PROPERTY_SPACE_CASE = next(
    case for case in CASES if case["id"] == "svn.property-space-delimited-pattern-is-single-glob"
)
INHERITED_PROPERTY_CASE = next(
    case for case in CASES if case["id"] == "svn.global-ignores-above-checkout-root"
)
SWITCHED_INHERITED_CASE = next(
    case for case in CASES if case["id"] == "svn.switched-subtree-inherits-global-ignores"
)
COLLAPSED_DIRECTORY_CASE = next(
    case for case in CASES if case["id"] == "svn.collapsed-unversioned-directory-membership"
)
IGNORED_DIRECTORY_CASE = next(
    case for case in CASES if case["id"] == "svn.ignored-unversioned-directory-collapses"
)
PATH_ROUND_TRIP_CASE = next(
    case for case in CASES if case["id"] == "svn.path-newline-and-tab-round-trip"
)
FILE_EXTERNAL_CASE = next(
    case for case in CASES if case["id"] == "svn.file-external-is-not-a-directory-boundary"
)


def _run_svn(
    command: list[str], *, cwd: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        command, cwd=cwd, env=environment, capture_output=True, timeout=60, check=False
    )
    if result.returncode:
        pytest.fail(
            f"native Subversion setup failed: {command!r}\n"
            f"stdout={result.stdout.decode(errors='replace')}\n"
            f"stderr={result.stderr.decode(errors='replace')}"
        )
    return result


def _create_working_copy(
    tmp_path: Path,
    case: dict[str, Any],
    request: pytest.FixtureRequest | None = None,
) -> tuple[Path, dict[str, str], Path]:
    setup = case["setup"]
    svn = shutil.which("svn")
    svnadmin = shutil.which("svnadmin")
    if svn is None or svnadmin is None:
        pytest.skip("Subversion client tools are not installed")
    root = tmp_path / "working-copy"
    repository = tmp_path / "repository"
    config_dir = tmp_path / "config"
    home = tmp_path / "home"
    config_dir.mkdir()
    home.mkdir()
    (config_dir / "config").write_text(
        "[miscellany]\nglobal-ignores = *.oracle-default\n", encoding="utf-8"
    )
    environment = {
        "HOME": str(home),
        "LC_ALL": "C",
        "LANG": "C",
        "PATH": os.environ.get("PATH", ""),
    }
    _run_svn([svnadmin, "create", str(repository)], cwd=tmp_path, environment=environment)
    if setup.get("repository_protocol") == "svnserve":
        svnserve = shutil.which("svnserve")
        if svnserve is None:
            pytest.skip("Subversion server tools are not installed")
        if request is None:
            raise ValueError("svnserve fixtures require a pytest request for server cleanup")
        server_config = tmp_path / "svnserve.conf"
        server_config.write_text(
            "[general]\nanon-access = write\nauth-access = write\n", encoding="utf-8"
        )
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        server = subprocess.Popen(
            [
                svnserve,
                "--foreground",
                "--daemon",
                "--listen-host",
                "127.0.0.1",
                "--listen-port",
                str(port),
                "--root",
                str(repository),
                "--config-file",
                str(server_config),
            ],
            cwd=tmp_path,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        def stop_server() -> None:
            if server.poll() is None:
                server.terminate()
                server.wait(timeout=5)

        request.addfinalizer(stop_server)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if server.poll() is not None:
                pytest.fail(f"svnserve exited during startup with status {server.returncode}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            pytest.fail("svnserve did not start listening on loopback")
        repository_url = f"svn://127.0.0.1:{port}"
    else:
        repository_url = repository.as_uri()
    url = f"{repository_url}/trunk"
    svn_prefix = [svn, "--config-dir", str(config_dir)]
    mkdir_targets = [
        url,
        *(f"{repository_url}/{relative}" for relative in setup.get("repository_directories", [])),
    ]
    _run_svn(
        [*svn_prefix, "mkdir", *mkdir_targets, "-m", "init"], cwd=tmp_path, environment=environment
    )
    for relative in setup.get("repository_subdirectories", []):
        _run_svn(
            [*svn_prefix, "mkdir", f"{url}/{relative}", "-m", "nested repository directory"],
            cwd=tmp_path,
            environment=environment,
        )
    checkout_subpath = setup.get("checkout_subpath")
    if checkout_subpath:
        parent_working_copy = tmp_path / "parent-working-copy"
        _run_svn(
            [*svn_prefix, "checkout", url, str(parent_working_copy)],
            cwd=tmp_path,
            environment=environment,
        )
        for relative, properties in setup.get("repository_properties", {}).items():
            target = "." if relative == "." else relative
            for name, value in properties.items():
                _run_svn(
                    [*svn_prefix, "propset", name, value, target],
                    cwd=parent_working_copy,
                    environment=environment,
                )
        _run_svn(
            [*svn_prefix, "commit", "-m", "repository parent properties", "."],
            cwd=parent_working_copy,
            environment=environment,
        )
        _run_svn(
            [*svn_prefix, "checkout", f"{url}/{checkout_subpath}", str(root)],
            cwd=tmp_path,
            environment=environment,
        )
    elif setup.get("repository_properties"):
        repository_working_copy = tmp_path / "repository-working-copy"
        _run_svn(
            [*svn_prefix, "checkout", repository_url, str(repository_working_copy)],
            cwd=tmp_path,
            environment=environment,
        )
        for relative, properties in setup["repository_properties"].items():
            target = "." if relative == "." else relative
            for name, value in properties.items():
                _run_svn(
                    [*svn_prefix, "propset", name, value, target],
                    cwd=repository_working_copy,
                    environment=environment,
                )
        _run_svn(
            [*svn_prefix, "commit", "-m", "repository properties", "."],
            cwd=repository_working_copy,
            environment=environment,
        )
        _run_svn([*svn_prefix, "checkout", url, str(root)], cwd=tmp_path, environment=environment)
    else:
        _run_svn([*svn_prefix, "checkout", url, str(root)], cwd=tmp_path, environment=environment)
    for relative in setup.get("directories", []):
        (root / relative).mkdir(parents=True, exist_ok=True)
    for relative, content in setup.get("versioned_files", {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _run_svn([*svn_prefix, "add", "--force", "."], cwd=root, environment=environment)
    for relative, properties in setup.get("properties", {}).items():
        target = "." if relative == "." else relative
        for name, value in properties.items():
            if repository_url.startswith("svn://"):
                authority = repository_url.removeprefix("svn://").split("/", 1)[0]
                value = value.replace("<repository_authority>", authority)
            value = value.replace("<repository_url>", repository_url).replace(
                "<repository_path>", repository.as_uri().removeprefix("file://")
            )
            _run_svn(
                [*svn_prefix, "propset", name, value, target], cwd=root, environment=environment
            )
    _run_svn([*svn_prefix, "commit", "-m", "fixture"], cwd=root, environment=environment)
    for copy in setup.get("repository_copies", []):
        _run_svn(
            [
                *svn_prefix,
                "copy",
                f"{repository_url}/{copy['source']}",
                f"{repository_url}/{copy['destination']}",
                "-m",
                copy.get("message", "repository copy"),
            ],
            cwd=tmp_path,
            environment=environment,
        )
    for switch in setup.get("switches", []):
        _run_svn(
            [*svn_prefix, "switch", f"{repository_url}/{switch['url']}", switch["path"]],
            cwd=root,
            environment=environment,
        )
    if setup.get("external_files"):
        _run_svn([*svn_prefix, "update"], cwd=root, environment=environment)
    for relative, depth in setup.get("sparse_depths", {}).items():
        _run_svn(
            [*svn_prefix, "update", "--set-depth", depth, relative],
            cwd=root,
            environment=environment,
        )
    for relative, content in setup.get("unversioned_files", {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for relative, content in setup.get("external_files", {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for index, (relative, nested_setup) in enumerate(
        setup.get("nested_working_copies", {}).items()
    ):
        nested_repository = tmp_path / f"nested-repository-{index}"
        _run_svn(
            [svnadmin, "create", str(nested_repository)], cwd=tmp_path, environment=environment
        )
        nested_url = (nested_repository / "trunk").as_uri()
        _run_svn(
            [*svn_prefix, "mkdir", nested_url, "-m", "nested"],
            cwd=tmp_path,
            environment=environment,
        )
        nested_path = root / relative
        _run_svn(
            [*svn_prefix, "checkout", nested_url, str(nested_path)],
            cwd=tmp_path,
            environment=environment,
        )
        for nested_relative, content in nested_setup.get("unversioned_files", {}).items():
            nested_file = nested_path / nested_relative
            nested_file.parent.mkdir(parents=True, exist_ok=True)
            nested_file.write_text(content, encoding="utf-8")
    return root, environment, config_dir


@pytest.fixture
def subversion_policy(tmp_path: Path) -> SubversionIgnorePolicy:
    case = CASES[0]
    root, environment, config_dir = _create_working_copy(tmp_path, case)
    return SubversionIgnorePolicy(root, config_dir=config_dir, environment=environment)


def test_subversion_properties_keep_local_inherited_and_membership_scopes(
    subversion_policy: SubversionIgnorePolicy,
) -> None:
    policy = subversion_policy

    assert policy.is_ignored("root.tmp")
    assert policy.is_ignored("root.cache")
    assert policy.is_ignored("pkg/child.cache")
    assert policy.is_ignored("pkg/local.tmp")
    assert policy.is_ignored("pkg/deeper/a.deep")
    assert policy.is_ignored("configured.oracle-default")
    assert policy.is_ignored("tracked.tmp")
    assert policy.is_ignored("ignored.tmp/child.txt")
    assert not policy.is_ignored("pkg/child.tmp")
    assert not policy.is_ignored("pkg/keep.tmp")
    assert not policy.is_ignored("pkg/visible.txt")
    assert not policy.is_ignored("case.only")

    trace = policy.trace("pkg/local.tmp")
    assert trace.complete
    assert trace.decision.property_name == "svn:ignore"
    assert trace.decision.scope == "pkg"
    assert trace.decision.source == str(policy.workspace_root / "pkg")

    configured_trace = policy.trace("configured.oracle-default")
    assert configured_trace.decision.property_name == "global-ignores"
    assert configured_trace.decision.source == (
        f"Subversion runtime configuration: {policy.config_dir / 'config'}"
    )


@pytest.mark.parametrize(
    "case",
    [
        *APR_GLOB_CASES,
        PROPERTY_SPACE_CASE,
        PATH_ROUND_TRIP_CASE,
        INHERITED_PROPERTY_CASE,
        SWITCHED_INHERITED_CASE,
    ],
    ids=lambda case: case["id"],
)
def test_subversion_policy_matches_native_status(tmp_path: Path, case: dict[str, Any]) -> None:
    if os.name == "nt" and case.get("windows_skip_reason"):
        pytest.skip(case["windows_skip_reason"])
    root, environment, config_dir = _create_working_copy(tmp_path, case)
    policy = SubversionIgnorePolicy(root, config_dir=config_dir, environment=environment)
    svn = shutil.which("svn")
    assert svn is not None
    native = _run_svn(
        [svn, "--config-dir", str(config_dir), "status", "--xml", "--no-ignore", "."],
        cwd=root,
        environment=environment,
    )
    document = ET.fromstring(native.stdout)
    native_ignored = {
        entry.attrib["path"].replace("\\", "/")
        for entry in document.findall(".//entry")
        if (status := entry.find("wc-status")) is not None
        and status.attrib.get("item") == "ignored"
    }
    fixture_paths = set(case["setup"]["unversioned_files"])
    expected = set(case["expected_ignored_paths"])

    assert native_ignored == expected
    assert {path for path in fixture_paths if policy.is_ignored(path)} == expected


@pytest.mark.parametrize("topdown", [True, False])
def test_subversion_walk_scopes_inherited_rules_to_switched_subtree(
    tmp_path: Path, topdown: bool
) -> None:
    case = SWITCHED_INHERITED_CASE
    root, environment, config_dir = _create_working_copy(tmp_path, case)
    policy = SubversionIgnorePolicy(root, config_dir=config_dir, environment=environment)
    walker = IgnoreWalker(root, policy=policy)

    ignored = {
        path.relative_to(root).as_posix()
        for path in walker.iter_files(selection="ignored", topdown=topdown)
        if ".svn" not in path.relative_to(root).parts
    }
    included = {
        path.relative_to(root).as_posix()
        for path in walker.iter_files(selection="included", topdown=topdown)
        if ".svn" not in path.relative_to(root).parts
    }

    assert ignored == {"pkg/ignored.branchtmp"}
    assert included == {"outside.branchtmp", "pkg/base.txt"}


@pytest.mark.parametrize("topdown", [True, False])
def test_subversion_collapsed_unversioned_directory_keeps_child_membership_unknown(
    tmp_path: Path, topdown: bool
) -> None:
    root, environment, config_dir = _create_working_copy(tmp_path, COLLAPSED_DIRECTORY_CASE)
    policy = SubversionIgnorePolicy(
        root,
        config_dir=config_dir,
        environment=environment,
        membership_aware=True,
    )
    svn = shutil.which("svn")
    assert svn is not None
    native = _run_svn(
        [
            svn,
            "--config-dir",
            str(config_dir),
            "status",
            "--xml",
            "--verbose",
            "--no-ignore",
            "--depth",
            "infinity",
            ".",
        ],
        cwd=root,
        environment=environment,
    )
    document = ET.fromstring(native.stdout)
    native_entries = {
        entry.attrib["path"].replace("\\", "/"): status.attrib["item"]
        for entry in document.findall("./target/entry")
        if (status := entry.find("wc-status")) is not None
    }
    child = policy.explain("cache/a.tmp")

    assert native_entries == {".": "normal", "cache": "unversioned"}
    assert child.ignored
    assert child.membership is None

    walker = IgnoreWalker(root, policy=policy)
    ignored = {
        path.relative_to(root).as_posix()
        for path in walker.iter_files(selection="ignored", topdown=topdown)
        if ".svn" not in path.relative_to(root).parts
    }
    included = {
        path.relative_to(root).as_posix()
        for path in walker.iter_files(selection="included", topdown=topdown)
        if ".svn" not in path.relative_to(root).parts
    }
    assert ignored == {"cache/a.tmp"}
    assert included == {"cache/visible.txt"}


@pytest.mark.parametrize("topdown", [True, False])
def test_subversion_ignored_directory_keeps_descendant_rules_and_membership_distinct(
    tmp_path: Path, topdown: bool
) -> None:
    root, environment, config_dir = _create_working_copy(tmp_path, IGNORED_DIRECTORY_CASE)
    policy = SubversionIgnorePolicy(
        root,
        config_dir=config_dir,
        environment=environment,
        membership_aware=True,
    )
    svn = shutil.which("svn")
    assert svn is not None
    native = _run_svn(
        [
            svn,
            "--config-dir",
            str(config_dir),
            "status",
            "--xml",
            "--verbose",
            "--no-ignore",
            "--depth",
            "infinity",
            ".",
        ],
        cwd=root,
        environment=environment,
    )
    document = ET.fromstring(native.stdout)
    native_entries = {
        entry.attrib["path"].replace("\\", "/"): status.attrib["item"]
        for entry in document.findall("./target/entry")
        if (status := entry.find("wc-status")) is not None
    }
    assert native_entries == {".": "normal", "cache": "ignored", "visible.txt": "unversioned"}

    parent = policy.explain("cache")
    child = policy.explain("cache/a.tmp")
    assert parent.ignored
    assert parent.membership == "unversioned"
    assert child.ignored
    assert child.membership is None

    walker = IgnoreWalker(root, policy=policy)
    ignored = {
        path.relative_to(root).as_posix()
        for path in walker.iter_files(selection="ignored", topdown=topdown)
        if ".svn" not in path.relative_to(root).parts
    }
    included = {
        path.relative_to(root).as_posix()
        for path in walker.iter_files(selection="included", topdown=topdown)
        if ".svn" not in path.relative_to(root).parts
    }
    assert ignored == {"cache/a.tmp", "cache/nested/b.txt"}
    assert included == {"visible.txt"}


def test_subversion_file_external_keeps_rule_matching_separate_from_membership(
    tmp_path: Path,
) -> None:
    root, environment, config_dir = _create_working_copy(tmp_path, FILE_EXTERNAL_CASE)
    policy = SubversionIgnorePolicy(root, config_dir=config_dir, environment=environment)
    walker = IgnoreWalker(root, policy=policy)
    svn = shutil.which("svn")
    assert svn is not None
    native = _run_svn(
        [svn, "--config-dir", str(config_dir), "status", "--xml", "--no-ignore", "."],
        cwd=root,
        environment=environment,
    )
    document = ET.fromstring(native.stdout)
    file_external = next(
        entry
        for entry in document.findall(".//entry")
        if entry.attrib["path"] == "external-file.txt"
    )
    status = file_external.find("wc-status")
    assert status is not None
    assert status.attrib["item"] == "normal"
    assert status.attrib["file-external"] == "true"
    native_ignored = {
        entry.attrib["path"]
        for entry in document.findall(".//entry")
        if (wc_status := entry.find("wc-status")) is not None
        and wc_status.attrib.get("item") == "ignored"
    }
    assert "external-file.txt" not in native_ignored

    # Default decisions preserve rule matching and leave membership unknown.
    assert policy.is_ignored("external-file.txt")
    assert root / "external-file.txt" in set(walker.iter_files(selection="ignored"))
    assert policy.explain("external-file.txt").membership is None

    membership_policy = SubversionIgnorePolicy(
        root,
        config_dir=config_dir,
        environment=environment,
        membership_aware=True,
    )
    membership_walker = IgnoreWalker(root, policy=membership_policy)
    file_external_decision = membership_policy.explain("external-file.txt")
    loose_decision = membership_policy.explain("loose.txt")

    assert file_external_decision.ignored
    assert file_external_decision.membership == "versioned"
    assert loose_decision.membership == "unversioned"
    assert root / "external-file.txt" not in set(membership_walker.iter_files(selection="ignored"))
    assert root / "external-file.txt" in set(membership_walker.iter_files(selection="included"))


def test_subversion_membership_tracks_working_copy_status_transitions(tmp_path: Path) -> None:
    case = {
        "setup": {
            "properties": {".": {"svn:ignore": "*.tmp\n"}},
            "versioned_files": {
                "normal.tmp": "normal\n",
                "modified.tmp": "before\n",
                "deleted.tmp": "deleted\n",
                "missing.tmp": "missing\n",
                "replaced.tmp": "replaced\n",
                "obstructed.tmp": "obstructed\n",
                "conflicted.tmp": "base\n",
            },
            "unversioned_files": {"loose.tmp": "unversioned and ignored\n"},
        }
    }
    root, environment, config_dir = _create_working_copy(tmp_path, case)
    svn = shutil.which("svn")
    assert svn is not None
    (root / "modified.tmp").write_text("after\n", encoding="utf-8")
    (root / "added.tmp").write_text("added after checkout\n", encoding="utf-8")
    _run_svn([svn, "add", "added.tmp"], cwd=root, environment=environment)
    _run_svn([svn, "delete", "--keep-local", "deleted.tmp"], cwd=root, environment=environment)
    _run_svn([svn, "delete", "--keep-local", "replaced.tmp"], cwd=root, environment=environment)
    _run_svn([svn, "add", "replaced.tmp"], cwd=root, environment=environment)
    repository_url = (
        _run_svn([svn, "info", "--show-item", "url", "."], cwd=root, environment=environment)
        .stdout.decode("utf-8")
        .strip()
    )
    other_working_copy = tmp_path / "other-working-copy"
    _run_svn(
        [svn, "checkout", repository_url, str(other_working_copy)],
        cwd=tmp_path,
        environment=environment,
    )
    (other_working_copy / "conflicted.tmp").write_text("theirs\n", encoding="utf-8")
    _run_svn(
        [svn, "commit", "-m", "conflict fixture change", "conflicted.tmp"],
        cwd=other_working_copy,
        environment=environment,
    )
    (root / "conflicted.tmp").write_text("ours\n", encoding="utf-8")
    _run_svn([svn, "update", "--accept", "postpone", "."], cwd=root, environment=environment)
    (root / "missing.tmp").unlink()
    (root / "obstructed.tmp").unlink()
    (root / "obstructed.tmp").mkdir()
    (root / "obstructed.tmp" / "child.txt").write_text("beneath obstruction\n", encoding="utf-8")

    native = _run_svn(
        [
            svn,
            "--config-dir",
            str(config_dir),
            "status",
            "--xml",
            "--verbose",
            "--no-ignore",
            "--depth",
            "infinity",
            ".",
        ],
        cwd=root,
        environment=environment,
    )
    document = ET.fromstring(native.stdout)
    native_items = {
        entry.attrib["path"]: status.attrib["item"]
        for entry in document.findall("./target/entry")
        if (status := entry.find("wc-status")) is not None
    }
    expected_items = {
        "normal.tmp": "normal",
        "modified.tmp": "modified",
        "added.tmp": "added",
        "deleted.tmp": "deleted",
        "missing.tmp": "missing",
        "replaced.tmp": "replaced",
        "obstructed.tmp": "obstructed",
        "conflicted.tmp": "conflicted",
        "loose.tmp": "ignored",
    }
    assert {path: native_items.get(path) for path in expected_items} == expected_items

    policy = SubversionIgnorePolicy(
        root,
        config_dir=config_dir,
        environment=environment,
        membership_aware=True,
    )
    decisions = {path: policy.explain(path) for path in expected_items}
    assert all(decision.ignored for decision in decisions.values())
    for path in expected_items.keys() - {"loose.tmp"}:
        assert decisions[path].membership == "versioned"
    assert decisions["loose.tmp"].membership == "unversioned"

    walker = IgnoreWalker(root, policy=policy)
    ignored_paths = {
        path.relative_to(root).as_posix()
        for path in walker.iter_files(selection="ignored")
        if path.relative_to(root).parts[0] != ".svn"
    }
    included_paths = {
        path.relative_to(root).as_posix()
        for path in walker.iter_files(selection="included")
        if path.relative_to(root).parts[0] != ".svn"
    }
    assert ignored_paths == {"loose.tmp", "obstructed.tmp/child.txt"}
    assert {
        "normal.tmp",
        "modified.tmp",
        "added.tmp",
        "deleted.tmp",
        "replaced.tmp",
        "conflicted.tmp",
    } <= included_paths


@pytest.mark.parametrize("topdown", [True, False])
def test_subversion_walk_round_trips_control_character_paths(tmp_path: Path, topdown: bool) -> None:
    if os.name == "nt":
        pytest.skip(PATH_ROUND_TRIP_CASE["windows_skip_reason"])
    case = PATH_ROUND_TRIP_CASE
    root, environment, config_dir = _create_working_copy(tmp_path, case)
    policy = SubversionIgnorePolicy(root, config_dir=config_dir, environment=environment)
    walker = IgnoreWalker(root, policy=policy)
    expected_ignored = set(case["expected_ignored_paths"])

    ignored = {
        path.relative_to(root).as_posix()
        for path in walker.iter_files(selection="ignored", topdown=topdown)
    }
    included = {
        path.relative_to(root).as_posix()
        for path in walker.iter_files(selection="included", topdown=topdown)
    }
    all_paths = {
        path.relative_to(root).as_posix()
        for path in walker.iter_files(selection="all", topdown=topdown)
    }

    assert expected_ignored <= ignored
    assert expected_ignored.isdisjoint(included)
    assert expected_ignored <= all_paths


def test_subversion_builtin_global_ignores_match_native_status(tmp_path: Path) -> None:
    case = CASES[0]
    root, environment, config_dir = _create_working_copy(tmp_path, case)
    config_file = config_dir / "config"
    config_file.write_text("[miscellany]\n", encoding="utf-8")
    probes = {
        "build.o": "compiled object\n",
        "image.pyc": "compiled Python bytecode\n",
        "__pycache__/module.pyc": "bytecode cache\n",
        ".DS_Store": "Finder metadata\n",
        "Thumbs.db": "Explorer metadata\n",
        "visible.bin": "visible file\n",
    }
    for relative, content in probes.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    policy = SubversionIgnorePolicy(root, config_dir=config_dir, environment=environment)
    svn = shutil.which("svn")
    assert svn is not None
    native = _run_svn(
        [svn, "--config-dir", str(config_dir), "status", "--xml", "--no-ignore", "."],
        cwd=root,
        environment=environment,
    )
    document = ET.fromstring(native.stdout)
    native_ignored = {
        entry.attrib["path"].replace("\\", "/")
        for entry in document.findall(".//entry")
        if (status := entry.find("wc-status")) is not None
        and status.attrib.get("item") == "ignored"
    }
    native_ignored_probes = {
        relative for relative in native_ignored if relative in probes or relative == "__pycache__"
    }
    candidate_ignored = {
        relative for relative in native_ignored_probes if policy.is_ignored(relative)
    }

    assert native_ignored_probes == {
        "build.o",
        "image.pyc",
        "__pycache__",
        ".DS_Store",
        "Thumbs.db",
    }
    assert candidate_ignored == native_ignored_probes
    assert policy.is_ignored("__pycache__/module.pyc")
    assert not policy.is_ignored("visible.bin")
    assert policy.trace("image.pyc").decision.source == (
        "Subversion built-in global-ignores defaults"
    )


def test_sparse_empty_directory_keeps_its_native_ignore_property(tmp_path: Path) -> None:
    case = next(case for case in CASES if case["id"] == "svn.sparse-empty-directory-property")
    root, environment, config_dir = _create_working_copy(tmp_path, case)
    policy = SubversionIgnorePolicy(root, config_dir=config_dir, environment=environment)
    walker = IgnoreWalker(root, policy=policy)
    svn = shutil.which("svn")
    assert svn is not None

    native = _run_svn(
        [svn, "--config-dir", str(config_dir), "status", "--xml", "--no-ignore", "."],
        cwd=root,
        environment=environment,
    )
    document = ET.fromstring(native.stdout)
    native_ignored = {
        entry.attrib["path"].replace("\\", "/")
        for entry in document.findall(".//entry")
        if (status := entry.find("wc-status")) is not None
        and status.attrib.get("item") == "ignored"
    }
    policy_ignored = {
        path.relative_to(root).as_posix()
        for path in walker.iter_files(selection="ignored")
        if path.is_file() and path.relative_to(root).parts[0] != ".svn"
    }

    assert not (root / "pkg" / "tracked.tmp").exists()
    assert policy.is_ignored("pkg/tracked.tmp")
    assert native_ignored == {"pkg/loose.tmp"}
    assert policy_ignored == native_ignored


def test_sparse_excluded_directory_is_a_walk_barrier_and_reports_incomplete_rules(
    tmp_path: Path,
) -> None:
    case = next(
        case for case in CASES if case["id"] == "svn.sparse-excluded-directory-does-not-descend"
    )
    root, environment, config_dir = _create_working_copy(tmp_path, case)
    policy = SubversionIgnorePolicy(root, config_dir=config_dir, environment=environment)
    walker = IgnoreWalker(root, policy=policy)
    svn = shutil.which("svn")
    assert svn is not None

    native = _run_svn(
        [svn, "--config-dir", str(config_dir), "status", "--xml", "--no-ignore", "."],
        cwd=root,
        environment=environment,
    )
    document = ET.fromstring(native.stdout)
    native_paths = {
        entry.attrib["path"].replace("\\", "/") for entry in document.findall(".//entry")
    }
    native_ignored = {
        entry.attrib["path"].replace("\\", "/")
        for entry in document.findall(".//entry")
        if (status := entry.find("wc-status")) is not None
        and status.attrib.get("item") == "ignored"
    }
    sparse_decision = policy.explain("pkg/loose.tmp")
    sparse_trace = policy.trace("pkg/loose.tmp")
    walked_user_files = {
        path.relative_to(root).as_posix()
        for path in walker.iter_files(selection="all")
        if path.is_file() and path.relative_to(root).parts[0] != ".svn"
    }

    assert native_paths == {"pkg"}
    assert not native_ignored
    assert not walked_user_files
    assert not policy.should_descend_directory(root / "pkg")
    assert not sparse_decision.discovery_complete
    assert {item.code for item in sparse_decision.diagnostics} == {"sparse-path-excluded"}
    assert not sparse_trace.complete

    membership_policy = SubversionIgnorePolicy(
        root,
        config_dir=config_dir,
        environment=environment,
        membership_aware=True,
    )
    membership_status = _run_svn(
        [
            svn,
            "--config-dir",
            str(config_dir),
            "status",
            "--xml",
            "--verbose",
            "--no-ignore",
            "--depth",
            "infinity",
            ".",
        ],
        cwd=root,
        environment=environment,
    )
    membership_document = ET.fromstring(membership_status.stdout)
    membership_paths = {
        entry.attrib["path"].replace("\\", "/")
        for entry in membership_document.findall("./target/entry")
    }
    omitted_decision = membership_policy.explain("pkg/loose.tmp")
    assert "pkg" in membership_paths
    assert "pkg/loose.tmp" not in membership_paths
    assert omitted_decision.membership is None
    assert not omitted_decision.discovery_complete
    membership_walker = IgnoreWalker(root, policy=membership_policy)
    membership_files = {
        path.relative_to(root).as_posix()
        for path in membership_walker.iter_files(selection="all")
        if path.is_file() and path.relative_to(root).parts[0] != ".svn"
    }
    assert not membership_files


@pytest.mark.skipif(os.name == "nt", reason="Windows uses APPDATA and Registry config sources")
def test_subversion_ambient_user_config_is_discovered_and_matches_native_status(
    tmp_path: Path,
) -> None:
    case = CASES[0]
    root, environment, _config_dir = _create_working_copy(tmp_path, case)
    user_config = Path(environment["HOME"]) / ".subversion" / "config"
    user_config.parent.mkdir(parents=True)
    user_config.write_text("[miscellany]\nglobal-ignores = *.ambient-hide\n", encoding="utf-8")
    (root / "secret.ambient-hide").write_text("hidden by user configuration\n", encoding="utf-8")
    (root / "visible.ambient-show").write_text("visible\n", encoding="utf-8")

    policy = SubversionIgnorePolicy(root, environment=environment)
    trace = policy.trace("secret.ambient-hide")
    svn = shutil.which("svn")
    assert svn is not None
    native = _run_svn(
        [svn, "status", "--xml", "--no-ignore", "."],
        cwd=root,
        environment=environment,
    )
    document = ET.fromstring(native.stdout)
    native_ignored = {
        entry.attrib["path"].replace("\\", "/")
        for entry in document.findall(".//entry")
        if (status := entry.find("wc-status")) is not None
        and status.attrib.get("item") == "ignored"
    }

    assert trace.decision.ignored
    assert trace.decision.discovery_complete
    assert trace.decision.source == f"Subversion runtime configuration: {user_config}"
    assert "secret.ambient-hide" in native_ignored
    assert policy.is_ignored("secret.ambient-hide")
    assert not policy.is_ignored("visible.ambient-show")


@pytest.mark.parametrize("topdown", [True, False])
def test_subversion_walk_keeps_membership_separate_and_does_not_prune(
    subversion_policy: SubversionIgnorePolicy, topdown: bool
) -> None:
    root = subversion_policy.root
    walker = IgnoreWalker(root, policy=subversion_policy)
    expected_all = {
        "tracked.tmp",
        "root.tmp",
        "root.cache",
        "case.only",
        "visible.txt",
        "configured.oracle-default",
        "ignored.tmp/child.txt",
        "pkg/child.tmp",
        "pkg/child.cache",
        "pkg/deeper/a.deep",
        "pkg/keep.tmp",
        "pkg/local.tmp",
        "pkg/visible.txt",
    }
    included = {
        "visible.txt",
        "case.only",
        "pkg/child.tmp",
        "pkg/keep.tmp",
        "pkg/visible.txt",
    }
    ignored = expected_all - included

    def as_relative(selection: Literal["included", "ignored", "all"]) -> set[str]:
        return {
            path.relative_to(root).as_posix()
            for path in walker.iter_files(selection=selection, topdown=topdown)
        }

    # "all" intentionally includes ignored entries, including live .svn metadata. Compare the
    # fixture paths and verify metadata is classified as ignored without depending on its files.
    assert expected_all <= as_relative("all")
    assert as_relative("included") == included
    ignored_paths = as_relative("ignored")
    assert ignored <= ignored_paths
    assert any(path.startswith(".svn/") for path in ignored_paths)


@pytest.mark.parametrize("topdown", [True, False])
def test_subversion_walk_stops_at_nested_working_copy_boundary(
    tmp_path: Path, topdown: bool
) -> None:
    case = next(case for case in CASES if case["id"] == "svn.walk-nested-working-copy-boundary")
    root, environment, config_dir = _create_working_copy(tmp_path, case)
    policy = SubversionIgnorePolicy(root, config_dir=config_dir, environment=environment)
    walker = IgnoreWalker(policy.root, policy=policy)
    nested_file = policy.root / "child" / "nested.txt"

    included = set(walker.iter_files(topdown=topdown))
    ignored = set(walker.iter_files(selection="ignored", topdown=topdown))
    all_files = set(walker.iter_files(selection="all", topdown=topdown))

    assert included == {policy.root / "visible.txt"}
    assert nested_file not in ignored
    assert nested_file not in all_files
    assert list(walker.iter_files("child", selection="all", topdown=topdown)) == []


@pytest.mark.parametrize("topdown", [True, False])
def test_subversion_walk_follows_native_listed_externals(tmp_path: Path, topdown: bool) -> None:
    case = next(case for case in CASES if case["id"] == "svn.walk-descends-into-externals")
    root, environment, config_dir = _create_working_copy(tmp_path, case)
    policy = SubversionIgnorePolicy(root, config_dir=config_dir, environment=environment)
    walker = IgnoreWalker(policy.root, policy=policy)
    native_status_files = {
        policy.root / relative
        for relative in case["expected_status_paths"]
        if (policy.root / relative).is_file()
    }

    included = set(walker.iter_files(topdown=topdown))
    ignored = set(walker.iter_files(selection="ignored", topdown=topdown))
    all_files = set(walker.iter_files(selection="all", topdown=topdown))
    expected_ignored = {policy.root / relative for relative in case["expected_ignored_paths"]}
    workspace_ignored = {
        path for path in ignored if ".svn" not in path.relative_to(policy.root).parts
    }

    assert included == native_status_files - expected_ignored
    assert workspace_ignored == expected_ignored
    assert policy.is_ignored("ext/ignored.tmp")
    assert policy.trace("ext/ignored.tmp").decision.source == str(policy.root / "ext")
    assert policy.is_ignored("ext/nested/ignored.deep")
    assert not policy.is_ignored("ext/nested/root-only.tmp")
    assert policy.trace("ext/nested/ignored.deep").decision.source == str(
        policy.root / "ext" / "nested"
    )
    assert native_status_files <= all_files
    assert {root.relative_to(policy.root).as_posix() for root in policy._load_external_roots()} == {
        "ext",
        "ext-operative",
        "ext-peg",
        "ext-parent",
        "ext-absolute",
        "ext-absolute/nested",
        "ext-server-root",
        "ext-server-root/nested",
        "ext/nested",
        "ext-parent/nested",
    }
    assert set(walker.iter_files("ext", topdown=topdown)) == {
        path
        for path in native_status_files - expected_ignored
        if path.is_relative_to(policy.root / "ext")
        and ".svn" not in path.relative_to(policy.root).parts
    }


def test_subversion_directory_external_membership_uses_its_own_status_scope(
    tmp_path: Path,
) -> None:
    case = next(case for case in CASES if case["id"] == "svn.walk-descends-into-externals")
    root, environment, config_dir = _create_working_copy(tmp_path, case)
    policy = SubversionIgnorePolicy(
        root,
        config_dir=config_dir,
        environment=environment,
        membership_aware=True,
    )
    svn = shutil.which("svn")
    assert svn is not None
    arguments = [
        svn,
        "--config-dir",
        str(config_dir),
        "status",
        "--xml",
        "--verbose",
        "--no-ignore",
        "--depth",
        "infinity",
        ".",
    ]
    parent_status = _run_svn(arguments, cwd=root, environment=environment)
    parent_document = ET.fromstring(parent_status.stdout)
    parent_items: dict[str, set[str]] = {}
    for entry in parent_document.findall("./target/entry"):
        if (status := entry.find("wc-status")) is not None:
            parent_items.setdefault(entry.attrib["path"], set()).add(status.attrib["item"])
    external_status = _run_svn(arguments, cwd=root / "ext", environment=environment)
    external_document = ET.fromstring(external_status.stdout)
    external_items = {
        entry.attrib["path"]: status.attrib["item"]
        for entry in external_document.findall("./target/entry")
        if (status := entry.find("wc-status")) is not None
    }
    external_root, external_file, external_ignored = policy.explain_many(
        ("ext", "ext/external.txt", "ext/ignored.tmp")
    )

    assert "external" in parent_items["ext"]
    assert external_items["external.txt"] == "unversioned"
    assert external_items["ignored.tmp"] == "ignored"
    assert external_root.membership == "versioned"
    assert external_file.membership == "unversioned"
    assert external_ignored.ignored
    assert external_ignored.membership == "unversioned"


@pytest.mark.parametrize("topdown", [True, False])
def test_subversion_walk_follows_scheme_relative_external(
    tmp_path: Path, request: pytest.FixtureRequest, topdown: bool
) -> None:
    case = next(case for case in CASES if case["id"] == "svn.walk-scheme-relative-external")
    root, environment, config_dir = _create_working_copy(tmp_path, case, request)
    policy = SubversionIgnorePolicy(root, config_dir=config_dir, environment=environment)
    walker = IgnoreWalker(policy.root, policy=policy)
    native_status_files = {
        policy.root / relative
        for relative in case["expected_status_paths"]
        if (policy.root / relative).is_file()
    }

    included = set(walker.iter_files(topdown=topdown))
    ignored = set(walker.iter_files(selection="ignored", topdown=topdown))

    assert included == native_status_files
    assert not (native_status_files & ignored)
    assert {path.relative_to(policy.root).as_posix() for path in policy._load_external_roots()} == {
        "ext-scheme-relative"
    }
