"""Mercurial policy behavior checked against captured native-client observations."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal

import pytest

from gitignore_walk import (
    IgnoreDecision,
    IgnoreWalker,
    MercurialIgnoreError,
    MercurialIgnorePolicy,
    MercurialPolicyConfig,
    MercurialPolicySelection,
    select_policy,
)
from gitignore_walk._schemes import mercurial as mercurial_scheme
from gitignore_walk._schemes.mercurial import _ignore_loader as mercurial_loader_module
from gitignore_walk._schemes.mercurial import policy as mercurial_policy_module
from tests.oracles.hg.run import (
    _has_init_failures,
    _ignored,
    _query_skip_reason,
    _status_observation,
    _symlink_is_directory,
)

ORACLE_ROOT = Path(__file__).parent / "oracles" / "hg"
CASES = json.loads((ORACLE_ROOT / "cases.json").read_text(encoding="utf-8"))["cases"]
MATCHING_CAPTURE_FILES = (
    "hg-7.2.4-macos-arm64.json",
    "hg-7.0.1-linux-aarch64.json",
    "hg-7.0.1-linux-x86_64.json",
    "hg-7.1.2-windows-x86_64.json",
)
MATCHING_OBSERVATIONS = {
    path: {
        case["id"]: case
        for case in json.loads((ORACLE_ROOT / "results" / path).read_text(encoding="utf-8"))[
            "cases"
        ]
    }
    for path in MATCHING_CAPTURE_FILES
}
CAPTURED_CASE_PROFILE_PARAMS = [
    pytest.param(
        case,
        profile,
        id=f"{Path(profile).stem.removeprefix('hg-')}:{case['id']}",
    )
    for profile in MATCHING_CAPTURE_FILES
    for case in CASES
    if case["id"] in MATCHING_OBSERVATIONS[profile]
]
WALK_CASES = json.loads((ORACLE_ROOT / "walk_cases.json").read_text(encoding="utf-8"))["cases"]
WALK_CAPTURE_FILES = (
    "hg-walk-7.2.4-macos-arm64.json",
    "hg-walk-7.0.1-linux-aarch64.json",
    "hg-walk-7.0.1-linux-x86_64.json",
    "hg-walk-7.1.2-windows-x86_64.json",
)
WALK_OBSERVATIONS = {
    path: {
        case["id"]: case
        for case in json.loads((ORACLE_ROOT / "results" / path).read_text(encoding="utf-8"))[
            "cases"
        ]
    }
    for path in WALK_CAPTURE_FILES
}


def _make_case(
    root: Path,
    case: dict[str, Any],
    *,
    profile: str | None = None,
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> tuple[MercurialIgnorePolicy, str]:
    """Create one disposable repo fixture and map explicit configured ignore paths."""
    root.mkdir()
    (root / ".hg").mkdir()
    home = root / "home"
    home.mkdir()
    for relative, content in case["setup"].get("files", {}).items():
        expanded = relative.replace("<home>", str(home))
        path = Path(expanded)
        if not path.is_absolute():
            path = root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.replace("<home>", str(home)), encoding="utf-8")
    for relative, contents_hex in case["setup"].get("files_bytes_hex", {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes.fromhex(contents_hex))
    for relative, content in case["setup"].get("outside_files", {}).items():
        path = (root.parent / relative).resolve()
        try:
            path.relative_to(root.parent.resolve())
        except ValueError as error:
            message = f"outside fixture path escapes its temporary root: {relative}"
            raise ValueError(message) from error
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for relative, mode in case["setup"].get("file_modes", {}).items():
        (root / relative).chmod(mode)
    for relative, target in case["setup"].get("symlinks", {}).items():
        link = root / relative
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(
                target,
                target_is_directory=_symlink_is_directory(
                    relative, target, case["setup"], link.parent
                ),
            )
        except OSError as error:
            pytest.skip(f"filesystem cannot create Mercurial source symlink: {error}")
    config = case["setup"].get("config", {})
    if case.get("policy_mode") == "client-config":
        if profile is None or monkeypatch is None:
            raise ValueError(
                "client-config oracle cases require a captured profile and monkeypatch"
            )
        hgrc = root.parent / "oracle-hgrc"
        lines = ["[ui]"]
        lines.extend(
            f"{key.partition('.')[2]} = {value.replace('<home>', str(home))}"
            for key, value in config.items()
        )
        hgrc.write_text("\n".join(lines) + "\n", encoding="utf-8")
        environment = os.environ.copy()
        environment.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "HGRCPATH": str(hgrc),
                "HGPLAIN": "1",
                "LC_ALL": "C",
            }
        )
        configuration = MATCHING_OBSERVATIONS[profile][case["id"]]["configuration"]
        if configuration is None or configuration["exit_code"] != 0:
            raise AssertionError(f"{case['id']}: native config capture is incomplete")
        config_stdout = (
            configuration["stdout"].replace("<repo>", str(root)).replace("<home>", str(home))
        )

        def captured_config(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            assert command[1:] == ["config", "--debug", "ui"]
            assert Path(kwargs["cwd"]) == root
            return subprocess.CompletedProcess(command, 0, config_stdout, "")

        monkeypatch.setattr(mercurial_policy_module.subprocess, "run", captured_config)
        return (
            MercurialIgnorePolicy(root, read_client_config=True, environment=environment),
            case["query"],
        )
    extra_sources = [
        Path(value.replace("<home>", str(home)))
        for key, value in config.items()
        if key.startswith("ui.ignore.")
    ]
    return MercurialIgnorePolicy(root, ignore_files=extra_sources), case["query"]


def _make_walk_case(root: Path, case: dict[str, Any]) -> MercurialIgnorePolicy:
    """Create one disposable workspace fixture for captured walk comparisons."""
    root.mkdir()
    (root / ".hg").mkdir()
    for relative, content in case["setup"]["files"].items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for relative, target in case["setup"].get("symlinks", {}).items():
        link = root / relative
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(
                target,
                target_is_directory=_symlink_is_directory(
                    relative, target, case["setup"], link.parent
                ),
            )
        except OSError as error:
            pytest.skip(f"filesystem cannot create Mercurial walk symlink: {error}")
    for relative in case["setup"].get("nested_repositories", []):
        (root / relative / ".hg").mkdir(parents=True)
    return MercurialIgnorePolicy(root)


def _expected_candidate_for_os(case: dict[str, Any], native_os: str) -> Any:
    """Resolve profile-specific native expectations while retaining the POSIX baseline."""
    return case.get("expected_candidate_by_os", {}).get(native_os, case.get("expected_candidate"))


@pytest.mark.parametrize(("case", "profile"), CAPTURED_CASE_PROFILE_PARAMS)
def test_policy_matches_captured_native_observation(
    tmp_path: Path,
    case: dict[str, Any],
    profile: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observation = MATCHING_OBSERVATIONS[profile][case["id"]]
    if observation["native_status"] == "skipped":
        pytest.skip(observation["skip_reason"])
    if os.name == "nt" and case["setup"].get("file_modes"):
        pytest.skip("Windows cannot reproduce POSIX unreadable-file permissions")
    if os.name == "nt" and case["setup"].get("files_bytes_hex"):
        pytest.skip("Windows cannot reproduce POSIX raw-byte ignore-file fixtures")
    if os.name == "nt" and "\\" in case["query"]:
        pytest.skip("Windows paths cannot represent a POSIX filename containing backslash")
    if os.name == "nt" and any(character in case["query"] for character in '<>:"|?*'):
        pytest.skip("Windows paths cannot represent a filename containing a reserved character")
    policy, query = _make_case(tmp_path / "repo", case, profile=profile, monkeypatch=monkeypatch)
    if case["id"] == "hg.include-unreadable-source":
        unreadable_source = (tmp_path / "repo" / "rules.ignore").resolve()
        original_open = Path.open

        def deny_unreadable_source(path: Path, *args: Any, **kwargs: Any) -> Any:
            if path.resolve() == unreadable_source:
                raise PermissionError("simulated unreadable Mercurial ignore source")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", deny_unreadable_source)
    decision = policy.explain(query)
    profile_os = "nt" if "windows" in profile else "posix"
    profile_candidate = _expected_candidate_for_os(case, profile_os)
    current_candidate = _expected_candidate_for_os(case, os.name)
    if isinstance(profile_candidate, bool):
        assert observation["candidate_matches"]
        assert observation["observed_ignored"] is profile_candidate
    if not isinstance(current_candidate, bool):
        current_candidate = observation["observed_ignored"]
    if current_candidate is not None:
        assert decision.ignored is current_candidate
    expected_complete = case.get("expected_policy_discovery_complete_by_os", {}).get(
        os.name, case.get("expected_policy_discovery_complete")
    )
    if expected_complete is not None:
        assert decision.discovery_complete is expected_complete
        expected_diagnostics = case.get("expected_policy_diagnostics_by_os", {}).get(
            os.name, case.get("expected_policy_diagnostics", [])
        )
        assert [item.code for item in decision.diagnostics] == expected_diagnostics
    if case["id"] == "hg.include-unreadable-source":
        assert "skipping unreadable pattern file" in observation["stderr"]
    if case["id"] == "hg.include-cycle":
        assert not decision.discovery_complete
        assert {item.code for item in decision.diagnostics} == {"include-cycle"}


LIVE_PATTERN_SEMANTIC_CASES = [
    case
    for case in CASES
    if case["dimension"] in {"regex-byte-semantics", "glob-byte-semantics"}
    or (case["id"].startswith("hg.regex-") and case["dimension"] == "regex-extensions")
]


@pytest.mark.skipif(shutil.which("hg") is None, reason="Mercurial client is not installed")
@pytest.mark.parametrize("case", LIVE_PATTERN_SEMANTIC_CASES, ids=lambda case: case["id"])
def test_pattern_semantics_match_installed_native_client(
    tmp_path: Path, case: dict[str, Any]
) -> None:
    """Compare supported Mercurial regex and glob behavior with the installed client."""
    hg = shutil.which("hg")
    assert hg is not None
    root = tmp_path / "repo"
    root.mkdir()
    hgrc = tmp_path / "hgrc"
    hgrc.write_text("", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(tmp_path),
            "USERPROFILE": str(tmp_path),
            "HGRCPATH": str(hgrc),
            "HGPLAIN": "1",
            "LC_ALL": "C",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    initialized = subprocess.run(
        [hg, "init", str(root)], env=environment, capture_output=True, check=False, timeout=30
    )
    assert initialized.returncode == 0, initialized.stderr.decode(errors="replace")
    for relative, content in case["setup"]["files"].items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    native = subprocess.run(
        [hg, "debugignore", "-v", "--", case["query"]],
        cwd=root,
        env=environment,
        capture_output=True,
        check=False,
        timeout=30,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert native.returncode == 0, native.stderr
    native_ignored = _ignored(native.stdout)
    if native_ignored is None and case.get("native_observation_fallback") == "status-membership":
        fallback = _status_observation(
            hg,
            root,
            environment,
            case["query"],
            known_unknown_paths=case.get("native_observation_fallback_known_unknown_paths", ()),
        )
        native_ignored = fallback["observed_ignored"]
    expected = _expected_candidate_for_os(case, os.name)
    policy = MercurialIgnorePolicy(root)
    if expected is None:
        assert native_ignored is not None, (
            "native debugignore and status gave no candidate result: "
            f"{fallback if case.get('native_observation_fallback') else native.stdout!r}"
        )
        assert policy.explain(case["query"]).ignored is native_ignored
        pytest.skip("the native Windows result is live-checked but not yet in the captured profile")
    assert native_ignored is expected
    assert policy.explain(case["query"]).ignored is expected


@pytest.mark.skipif(shutil.which("hg") is None, reason="Mercurial client is not installed")
def test_unicode_regex_flag_is_rejected_by_native_and_policy(tmp_path: Path) -> None:
    """Mercurial's byte regex engine rejects Python's Unicode-only ``(?u)`` flag."""
    hg = shutil.which("hg")
    assert hg is not None
    root = tmp_path / "repo"
    root.mkdir()
    hgrc = tmp_path / "hgrc"
    hgrc.write_text("", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(tmp_path),
            "USERPROFILE": str(tmp_path),
            "HGRCPATH": str(hgrc),
            "HGPLAIN": "1",
            "LC_ALL": "C",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    initialized = subprocess.run(
        [hg, "init", str(root)], env=environment, capture_output=True, check=False, timeout=30
    )
    assert initialized.returncode == 0, initialized.stderr.decode(errors="replace")
    source = root / ".hgignore"
    source.write_text(r"(?u)^\w+$" + "\n", encoding="utf-8")
    native = subprocess.run(
        [hg, "debugignore", "-v", "--", "é"],
        cwd=root,
        env=environment,
        capture_output=True,
        check=False,
        timeout=30,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert native.returncode != 0
    assert "invalid pattern" in native.stderr
    with pytest.raises(MercurialIgnoreError, match="cannot use 'u' flag with a bytes pattern"):
        MercurialIgnorePolicy(root)


def test_glob_matching_preserves_unicode_normalization_form(tmp_path: Path) -> None:
    """Mercurial compares the code-point spelling of a path without Unicode normalization."""
    if os.name == "nt":
        pytest.skip("Windows Mercurial matches local-code-page paths against UTF-8 ignore bytes")
    (tmp_path / ".hg").mkdir()
    (tmp_path / ".hgignore").write_text("syntax: glob\ncafé.tmp\n", encoding="utf-8")
    policy = MercurialIgnorePolicy(tmp_path)

    assert policy.explain("café.tmp").ignored
    assert not policy.explain("cafe\u0301.tmp").ignored


def test_include_follows_symlinked_source_outside_workspace(tmp_path: Path) -> None:
    case = next(case for case in CASES if case["id"] == "hg.include-symlink-outside-workspace")
    policy, query = _make_case(tmp_path / "repo", case)

    trace = policy.trace(query)

    if os.name == "nt":
        assert not trace.decision.ignored
        assert not trace.decision.discovery_complete
        assert [item.code for item in trace.decision.diagnostics] == ["source-unavailable"]
        return
    assert trace.decision.ignored
    assert Path(trace.decision.source or "").is_relative_to(tmp_path / ".oracle-outside")
    assert trace.matches[0].scope == "."


def test_native_oracle_explains_platform_specific_fixture_skips() -> None:
    """Oracle skips identify path-byte and permission limits on Windows."""
    assert _query_skip_reason("bad\udcff.tmp", native_os="nt") is not None
    assert _query_skip_reason("foo\\bar", native_os="nt") is not None
    assert _query_skip_reason("foo\\bar", native_os="posix") is None
    assert _query_skip_reason("literal*.tmp", native_os="nt") is not None
    assert _query_skip_reason("", native_os="nt") is None
    assert _query_skip_reason("bad\udcff.tmp", native_os="posix") is None
    assert _query_skip_reason("ordinary.tmp", native_os="nt") is None
    assert _query_skip_reason("a.tmp", native_os="nt", requires_posix_permissions=True) is not None
    assert not _has_init_failures([{"native_status": "skipped"}])
    assert _has_init_failures([{"native_status": "captured", "init_exit_code": 1}])


@pytest.mark.parametrize(
    "case_id",
    [
        "hg.include-symlink-outside-workspace",
        "hg.include-through-symlinked-directory",
        "hg.include-dangling-symlink-source",
    ],
)
def test_windows_source_discovery_marks_symlink_sources_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case_id: str
) -> None:
    monkeypatch.setattr(mercurial_loader_module, "_WINDOWS", True)
    case = next(case for case in CASES if case["id"] == case_id)
    policy, query = _make_case(tmp_path / "repo", case)

    decision = policy.explain(query)

    assert not decision.ignored
    assert not decision.discovery_complete
    assert [item.code for item in decision.diagnostics] == ["source-unavailable"]


def test_subinclude_match_is_corroborated_by_native_status_walks() -> None:
    """A Mercurial debugignore formatting crash does not invalidate the matched rule result."""
    assert len(MATCHING_CAPTURE_FILES) == len(WALK_CAPTURE_FILES)
    for index, profile in enumerate(MATCHING_CAPTURE_FILES):
        walk_profile = WALK_CAPTURE_FILES[index]
        debugignore = MATCHING_OBSERVATIONS[profile]["hg.subinclude-rebases"]
        status_walk = WALK_OBSERVATIONS[walk_profile]["hg.walk.subinclude-scope"]

        assert debugignore["exit_code"] != 0
        assert debugignore["observed_ignored"] is True
        assert status_walk["candidate_matches"]
        assert "pkg/build/one.tmp" in status_walk["observed_ignored_paths"]


@pytest.mark.parametrize(
    "profile", MATCHING_CAPTURE_FILES, ids=lambda name: name.removesuffix(".json")
)
def test_configured_ignore_sources_keep_captured_native_order(tmp_path: Path, profile: str) -> None:
    case = next(case for case in CASES if case["id"] == "hg.configured-ignore-source-order")
    policy, query = _make_case(tmp_path / "repo", case)
    decision = policy.explain(query)

    assert decision.source == str((policy.root / "home" / "first.ignore").resolve())
    assert "<home>/first.ignore" in MATCHING_OBSERVATIONS[profile][case["id"]]["stdout"]


@pytest.mark.parametrize(
    "case_id",
    [
        "hg.config-discovery-named-ignore-entries",
        "hg.config-discovery-repository-config",
        "hg.config-discovery-home-relative-path",
        "hg.config-discovery-included-hgrc",
    ],
)
@pytest.mark.parametrize(
    "profile", MATCHING_CAPTURE_FILES, ids=lambda name: name.removesuffix(".json")
)
def test_client_config_discovery_preserves_effective_source_order_and_paths(
    tmp_path: Path, case_id: str, profile: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = next(case for case in CASES if case["id"] == case_id)
    policy, query = _make_case(tmp_path / case_id, case, profile=profile, monkeypatch=monkeypatch)

    trace = policy.trace(query)

    assert trace.decision.ignored
    if case_id == "hg.config-discovery-named-ignore-entries":
        assert [Path(item.source).name for item in trace.matches] == [
            "first.ignore",
            "second.ignore",
        ]
    elif case_id == "hg.config-discovery-repository-config":
        assert Path(trace.decision.source or "").name == "workspace.ignore"
    elif case_id == "hg.config-discovery-home-relative-path":
        assert Path(trace.decision.source or "") == policy.root / "home" / ".project-ignore"
    else:
        assert Path(trace.decision.source or "").name == "included.ignore"


def test_selection_is_discriminated_and_has_no_cross_scheme_fallback(tmp_path: Path) -> None:
    (tmp_path / ".hg").mkdir()
    (tmp_path / ".hgignore").write_text("syntax: glob\n*.tmp\n", encoding="utf-8")

    selection = select_policy(tmp_path, MercurialPolicyConfig())

    assert isinstance(selection, MercurialPolicySelection)
    assert selection.mode == "mercurial"
    assert selection.backend == "mercurial-python"
    assert selection.fallback_reason is None
    assert isinstance(selection.policy, MercurialIgnorePolicy)
    assert selection.policy.is_ignored("nested/file.tmp")
    assert selection.policy.scheme == "mercurial"


def test_selection_can_enable_native_config_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".hg").mkdir()
    (tmp_path / ".hgignore").write_text("", encoding="utf-8")
    ignore_file = tmp_path / "configured.ignore"
    ignore_file.write_text("syntax: glob\n*.configured\n", encoding="utf-8")
    hgrc = tmp_path / "hgrc"
    hgrc.write_text(f"[ui]\nignore.project = {ignore_file}\n", encoding="utf-8")
    environment = {
        "HOME": str(tmp_path),
        "HGRCPATH": str(hgrc),
        "HGPLAIN": "1",
        "LC_ALL": "C",
    }
    output = f"{hgrc}:2: ui.ignore.project={ignore_file}\n"

    def captured_config(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command[1:] == ["config", "--debug", "ui"]
        assert Path(kwargs["cwd"]) == tmp_path
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(mercurial_policy_module.subprocess, "run", captured_config)

    selection = select_policy(
        tmp_path,
        MercurialPolicyConfig(read_client_config=True, environment=environment),
    )

    assert selection.policy.is_ignored("build/file.configured")
    assert selection.policy.trace("build/file.configured").decision.source == str(ignore_file)


def test_client_config_discovery_reports_missing_mercurial_executable(tmp_path: Path) -> None:
    (tmp_path / ".hg").mkdir()

    with pytest.raises(MercurialIgnoreError, match="Unable to discover") as error:
        MercurialIgnorePolicy(
            tmp_path,
            read_client_config=True,
            hg_executable=str(tmp_path / "missing-hg"),
        )

    assert error.value.operation == "config"


@pytest.mark.skipif(shutil.which("hg") is None, reason="Mercurial client is not installed")
def test_client_config_discovery_runs_the_installed_hg_client(tmp_path: Path) -> None:
    (tmp_path / ".hg").mkdir()
    (tmp_path / ".hgignore").write_text("", encoding="utf-8")
    ignore_file = tmp_path / "configured.ignore"
    ignore_file.write_text("syntax: glob\n*.configured\n", encoding="utf-8")
    hgrc = tmp_path / "hgrc"
    hgrc.write_text(f"[ui]\nignore.project = {ignore_file}\n", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(tmp_path),
            "HGRCPATH": str(hgrc),
            "HGPLAIN": "1",
            "LC_ALL": "C",
        }
    )

    policy = MercurialIgnorePolicy(tmp_path, read_client_config=True, environment=environment)

    assert policy.trace("nested/file.configured").decision.source == str(ignore_file)


@pytest.mark.parametrize("topdown", [True, False])
def test_walker_prunes_mercurial_ignored_directories(tmp_path: Path, topdown: bool) -> None:
    root = tmp_path / "repo"
    (root / ".hg").mkdir(parents=True)
    (root / ".hgignore").write_text("syntax: glob\ncache\n", encoding="utf-8")
    ignored_file = root / "cache" / "nested" / "file.tmp"
    ignored_file.parent.mkdir(parents=True)
    ignored_file.write_text("ignored\n", encoding="utf-8")
    visible_file = root / "visible.txt"
    visible_file.write_text("visible\n", encoding="utf-8")
    walker = IgnoreWalker(root, policy=MercurialIgnorePolicy(root))

    assert set(walker.iter_files(topdown=topdown)) == {root / ".hgignore", visible_file}
    assert list(walker.iter_files(topdown=topdown, selection="ignored")) == [ignored_file]


@pytest.mark.parametrize("topdown", [True, False], ids=["topdown", "bottomup"])
@pytest.mark.parametrize("selection", ["included", "ignored", "all"])
@pytest.mark.parametrize("case", WALK_CASES, ids=lambda case: case["id"])
@pytest.mark.parametrize("profile", WALK_CAPTURE_FILES, ids=lambda name: name.removesuffix(".json"))
def test_walker_matches_captured_native_ignored_file_walk(
    tmp_path: Path,
    case: dict[str, Any],
    selection: Literal["included", "ignored", "all"],
    topdown: bool,
    profile: str,
) -> None:
    native = WALK_OBSERVATIONS[profile][case["id"]]
    if native["native_status"] == "skipped":
        pytest.skip(native["skip_reason"])
    if "expected_ignored_paths_by_os" in case:
        profile_os = "nt" if "windows" in profile else "posix"
        if profile_os != os.name:
            pytest.skip("platform-specific symlink behavior requires a matching native platform")
    policy = _make_walk_case(tmp_path / "repo", case)
    tracked = set(case["tracked_paths"])
    # Mercurial status reports symlinks; IgnoreWalker intentionally yields regular files only.
    symlinks = set(case["setup"].get("symlinks", {}))
    observed_ignored = set(native["observed_ignored_paths"]) - symlinks
    observed_unknown = set(native["observed_unknown_paths"]) - symlinks
    walked = {
        path.relative_to(policy.root).as_posix()
        for path in IgnoreWalker(policy.root, policy=policy).iter_files(
            selection=selection, topdown=topdown
        )
    }

    assert native["candidate_matches"]
    if selection == "included":
        assert walked - tracked == observed_unknown
    elif selection == "ignored":
        assert walked - tracked == observed_ignored
    else:
        assert walked == observed_ignored | observed_unknown | tracked
    for relative in tracked:
        # The walker answers rule matching; Mercurial status additionally filters membership.
        assert policy.is_ignored(relative)


@pytest.mark.parametrize("topdown", [True, False], ids=["topdown", "bottomup"])
@pytest.mark.parametrize("case", WALK_CASES, ids=lambda case: case["id"])
def test_pruning_does_not_change_included_files_in_native_walk_fixtures(
    tmp_path: Path, case: dict[str, Any], topdown: bool
) -> None:
    class UnprunedMercurialPolicy(MercurialIgnorePolicy):
        """Keep ordinary ignored directories traversable for the parity comparison."""

        def can_prune_ignored_directory(self, target: Path, decision: IgnoreDecision) -> bool:
            del target, decision
            return False

    root = tmp_path / "repo"
    pruned_policy = _make_walk_case(root, case)
    unpruned_policy = UnprunedMercurialPolicy(root)
    pruned = set(
        IgnoreWalker(root, policy=pruned_policy).iter_files(selection="included", topdown=topdown)
    )
    unpruned = set(
        IgnoreWalker(root, policy=unpruned_policy).iter_files(selection="included", topdown=topdown)
    )

    assert pruned == unpruned


def test_nested_hg_workspace_is_not_traversed(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / ".hg").mkdir(parents=True)
    nested_metadata = root / "subrepo" / ".hg"
    nested_metadata.mkdir(parents=True)
    (nested_metadata / "store").mkdir()
    (nested_metadata / "store" / "data").write_text("metadata\n", encoding="utf-8")
    visible = root / "subrepo" / "source.txt"
    visible.write_text("source\n", encoding="utf-8")
    policy = MercurialIgnorePolicy(root)

    assert policy.is_ignored("subrepo/.hg/store/data")
    assert list(IgnoreWalker(root, policy=policy).iter_files()) == []
    assert list(IgnoreWalker(root, policy=policy).iter_files("subrepo")) == []
    assert visible.is_file()


def test_trace_retains_source_scope_and_line(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / ".hg").mkdir(parents=True)
    (root / ".hgignore").write_text("syntax: glob\nsubinclude:pkg/rules\n", encoding="utf-8")
    (root / "pkg").mkdir()
    (root / "pkg" / "rules").write_text("rootglob:build/*\n", encoding="utf-8")
    policy = MercurialIgnorePolicy(root)

    trace = policy.trace("pkg/build/file")

    assert trace.decision.ignored
    assert trace.complete
    assert len(trace.matches) == 1
    assert trace.matches[0].source.replace("\\", "/").endswith("/pkg/rules")
    assert trace.matches[0].line == 1
    assert trace.matches[0].scope == "pkg"


def test_windows_home_relative_client_paths_prefer_userprofile() -> None:
    path = mercurial_policy_module._expand_configured_path(
        "~/.project-ignore",
        {"HOME": "/posix-home", "USERPROFILE": "C:/Users/fixture"},
        windows=True,
    )

    assert path.as_posix() == "C:/Users/fixture/.project-ignore"


def test_repeated_symlinked_source_retains_each_subinclude_scope(tmp_path: Path) -> None:
    case = next(
        case for case in WALK_CASES if case["id"] == "hg.walk.repeated-include-distinct-scopes"
    )
    policy = _make_walk_case(tmp_path / "repo", case)

    first = policy.trace("one/first.tmp")
    second = policy.trace("two/second.tmp")

    if os.name == "nt":
        for trace in (first, second):
            assert not trace.decision.ignored
            assert not trace.decision.discovery_complete
            assert [item.code for item in trace.decision.diagnostics] == [
                "source-unavailable",
                "source-unavailable",
            ]
        return
    assert first.decision.ignored
    assert second.decision.ignored
    assert first.matches[0].scope == "one"
    assert second.matches[0].scope == "two"
    assert first.matches[0].source == second.matches[0].source


def test_source_changes_apply_to_next_query_and_iteration_uses_a_snapshot(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    (root / ".hg").mkdir(parents=True)
    ignore_file = root / ".hgignore"
    ignore_file.write_text("", encoding="utf-8")
    policy = MercurialIgnorePolicy(root)

    decisions = policy.iter_explain(["first.tmp", "second.tmp"], batch_size=1)
    assert not next(decisions).ignored
    ignore_file.write_text("syntax: glob\n*.tmp\n", encoding="utf-8")
    assert not next(decisions).ignored
    assert policy.is_ignored("later.tmp")


def test_walk_session_uses_one_source_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / ".hg").mkdir(parents=True)
    ignore_file = root / ".hgignore"
    ignore_file.write_text("", encoding="utf-8")
    policy = MercurialIgnorePolicy(root)
    session = policy._open_walk()
    ignore_file.write_text("syntax: glob\n*.tmp\n", encoding="utf-8")

    assert not session.explain_many(["inside-walk.tmp"])[0].ignored
    assert policy.is_ignored("next-query.tmp")


def test_extended_globs_keep_braces_escapes_and_root_scope(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / ".hg").mkdir(parents=True)
    (root / ".hgignore").write_text(
        "syntax: glob\n*.{py,txt}\nrootglob:config/*.local\nglob:literal\\*.tmp\n",
        encoding="utf-8",
    )
    policy = MercurialIgnorePolicy(root)

    assert policy.is_ignored("nested/readme.txt")
    assert policy.is_ignored("config/one.local")
    assert not policy.is_ignored("other/config/one.local")
    assert policy.is_ignored("literal*.tmp")
    assert not policy.is_ignored("literalX.tmp")


def test_missing_include_is_reported_as_incomplete_discovery(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / ".hg").mkdir(parents=True)
    (root / ".hgignore").write_text("include:missing.ignore\n", encoding="utf-8")

    decision = MercurialIgnorePolicy(root).explain("unmatched")

    assert not decision.ignored
    assert not decision.discovery_complete
    assert [item.code for item in decision.diagnostics] == ["source-unavailable"]


def test_invalid_regexp_fails_with_source_context(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / ".hg").mkdir(parents=True)
    (root / ".hgignore").write_text("[\n", encoding="utf-8")

    with pytest.raises(MercurialIgnoreError) as error:
        MercurialIgnorePolicy(root)

    assert error.value.operation == "parse"
    assert error.value.line == 1
    assert error.value.source is not None


@pytest.mark.skipif(os.name == "nt", reason="Windows cannot represent POSIX undecodable path bytes")
def test_undecodable_ignore_bytes_match_surrogateescaped_path(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / ".hg").mkdir(parents=True)
    (root / ".hgignore").write_bytes(b"syntax: glob\nbad\xff.tmp\n")

    policy = MercurialIgnorePolicy(root)

    assert policy.is_ignored("bad\udcff.tmp")


def test_undecodable_filename_walk_matches_native_status_when_filesystem_allows_it(
    tmp_path: Path,
) -> None:
    if os.name == "nt":
        pytest.skip("Windows filesystems do not support undecodable POSIX filename bytes")
    hg = shutil.which("hg")
    if hg is None:
        pytest.skip("Mercurial client is not installed")
    root = tmp_path / "repo"
    home = tmp_path / "home"
    home.mkdir()
    hgrc = tmp_path / "hgrc"
    hgrc.write_text("", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(home),
            "HGRCPATH": str(hgrc),
            "HGPLAIN": "1",
            "LC_ALL": "C",
        }
    )
    initialized = subprocess.run(
        [hg, "init", str(root)],
        env=environment,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert initialized.returncode == 0, initialized.stderr.decode(errors="replace")
    (root / ".hgignore").write_bytes(b"syntax: glob\nbad\xff.tmp\n")
    filename = b"bad\xff.tmp"
    try:
        descriptor = os.open(os.fsencode(root) + b"/" + filename, os.O_CREAT | os.O_WRONLY, 0o600)
    except OSError as error:
        pytest.skip(f"filesystem does not permit undecodable UTF-8 path bytes: {error}")
    else:
        os.close(descriptor)

    native = subprocess.run(
        [hg, "status", "--ignored", "--no-status", "-0"],
        cwd=root,
        env=environment,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert native.returncode == 0, native.stderr.decode(errors="replace")
    native_ignored = {path for path in native.stdout.split(b"\0") if path}
    policy = MercurialIgnorePolicy(root)
    assert not policy.should_descend_directory(root / ".hg")
    policy_ignored = {
        path.relative_to(root).as_posix().encode("utf-8", errors="surrogateescape")
        for path in IgnoreWalker(root, policy=policy).iter_files(selection="ignored")
    }

    assert native_ignored == {filename}
    assert policy_ignored == native_ignored


@pytest.mark.parametrize(
    ("limit_name", "limit", "contents"),
    [
        (
            "_MAX_INCLUDE_DEPTH",
            1,
            {".hgignore": "include:first\n", "first": "include:second\n", "second": ""},
        ),
        (
            "_MAX_SOURCE_COUNT",
            2,
            {".hgignore": "include:first\ninclude:second\n", "first": "", "second": ""},
        ),
        ("_MAX_SOURCE_BYTES", 2, {".hgignore": "123"}),
        (
            "_MAX_TOTAL_BYTES",
            15,
            {".hgignore": "include:first\n", "first": "xx"},
        ),
    ],
    ids=["depth", "source-count", "source-size", "total-size"],
)
def test_include_graph_limits_report_incomplete_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    limit: int,
    contents: dict[str, str],
) -> None:
    root = tmp_path / "repo"
    (root / ".hg").mkdir(parents=True)
    for relative, content in contents.items():
        (root / relative).write_text(content, encoding="utf-8")
    monkeypatch.setattr(mercurial_scheme._ignore_loader, limit_name, limit)

    decision = MercurialIgnorePolicy(root).explain("unmatched")

    assert not decision.discovery_complete
    assert any(item.code == "source-limit" for item in decision.diagnostics)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are unavailable")
def test_included_non_regular_source_does_not_block(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / ".hg").mkdir(parents=True)
    (root / ".hgignore").write_text("include:rules.pipe\n", encoding="utf-8")
    os.mkfifo(root / "rules.pipe")

    decision = MercurialIgnorePolicy(root).explain("unmatched")

    assert not decision.discovery_complete
    assert any(item.code == "source-unavailable" for item in decision.diagnostics)


def test_pattern_size_limit_raises_with_source_context(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / ".hg").mkdir(parents=True)
    (root / ".hgignore").write_text(
        "syntax: glob\n" + ("x" * 20_001),
        encoding="utf-8",
    )

    with pytest.raises(MercurialIgnoreError, match="exceeds the 20000-byte limit") as error:
        MercurialIgnorePolicy(root)

    assert error.value.operation == "parse"
    assert error.value.source is not None
    assert error.value.line == 2
