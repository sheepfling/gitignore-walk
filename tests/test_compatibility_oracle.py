"""Integrity checks for captured Sapling/Jujutsu Git-ignore compatibility probes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.oracles.compat.run import _sapling_status_paths

ORACLE_ROOT = Path(__file__).parent / "oracles" / "compat"
CAPTURE_FILES = (
    "sapling-0.2.20261103-jj-0.47.1-macos-arm64.json",
    "sapling-0.2.20261103-jj-0.47.1-git-2.56.0-macos-arm64.json",
    "sapling-0.2.20261103-jj-0.47.1-git-2.56.0-debian13-x86_64.json",
    "sapling-0.2.20261103-jj-0.47.1-debian13-arm64.json",
    "sapling-0.2.20261103-jj-0.47.1-debian13-x86_64.json",
)
PATTERN_CAPTURE_FILES = (CAPTURE_FILES[0], CAPTURE_FILES[3], CAPTURE_FILES[4])
EARLIER_PATTERN_CAPTURE_FILES = (CAPTURE_FILES[1], CAPTURE_FILES[2])
PATTERN_FIXTURE = json.loads((ORACLE_ROOT / "cases.json").read_text(encoding="utf-8"))
PATTERN_QUERY_FILES = sorted(PATTERN_FIXTURE["pattern_query_files"])
PATTERN_IGNORED = sorted(PATTERN_FIXTURE["expected_pattern_ignored"])
PATTERN_INCLUDED = sorted(set(PATTERN_QUERY_FILES) - set(PATTERN_IGNORED))
EARLIER_PATTERN_QUERY_FILES = [
    "blocked/keep.txt",
    "cache/drop.tmp",
    "cache/keep.tmp",
    "nested/deep/deep.log",
    "nested/root-only.tmp",
    "root-only.tmp",
]
EARLIER_PATTERN_IGNORED = [
    "blocked/keep.txt",
    "cache/drop.tmp",
    "nested/deep/deep.log",
    "root-only.tmp",
]
EARLIER_PATTERN_INCLUDED = ["cache/keep.tmp", "nested/root-only.tmp"]
LINKED_WORKTREE_CAPTURE_FILES = (
    "linked-worktree-sapling-0.2.20261103-jj-0.47.1-macos-arm64.json",
    "linked-worktree-sapling-0.2.20261103-jj-0.47.1-debian13-arm64.json",
    "linked-worktree-sapling-0.2.20261103-jj-0.47.1-debian13-x86_64.json",
)
LINKED_WORKTREE_JJ_CAPTURE_FILES = (
    "linked-worktree-jj-0.47.1-macos-arm64.json",
    "linked-worktree-jj-0.47.1-windows-x64.json",
)
ENVIRONMENT_GLOBAL_CAPTURE_FILES = (
    CAPTURE_FILES[0],
    CAPTURE_FILES[2],
    CAPTURE_FILES[3],
    CAPTURE_FILES[4],
)
SYMLINK_CAPTURE_FILES = (CAPTURE_FILES[0], CAPTURE_FILES[3], CAPTURE_FILES[4])
CAPTURES: dict[str, dict[str, Any]] = {
    profile: json.loads((ORACLE_ROOT / "results" / profile).read_text(encoding="utf-8"))
    for profile in CAPTURE_FILES
}


def test_sapling_status_paths_normalize_windows_separators_without_rewriting_posix_names() -> None:
    """Interpret native Windows separators while preserving literal POSIX backslashes."""
    output = "? root.txt\0I nested\\probe.txt\0I literal\\name.txt\0"

    assert _sapling_status_paths(output, windows_paths=True) == (
        {"root.txt"},
        {"nested/probe.txt", "literal/name.txt"},
    )
    assert _sapling_status_paths(output, windows_paths=False) == (
        {"root.txt"},
        {"nested\\probe.txt", "literal\\name.txt"},
    )


WINDOWS_JJ_CAPTURE = json.loads(
    (ORACLE_ROOT / "results" / "jj-0.47.1-windows-x64.json").read_text(encoding="utf-8")
)
JJ_045_FULL_CAPTURE_FILES = (
    "jj-0.45.1-macos-arm64.json",
    "jj-0.45.1-debian13-x86_64.json",
)
JJ_045_FULL_CAPTURES = {
    filename: json.loads((ORACLE_ROOT / "results" / filename).read_text(encoding="utf-8"))
    for filename in JJ_045_FULL_CAPTURE_FILES
}
OLDER_SAPLING_PROFILE_FILES = (
    "sapling-0.2.20261028-jj-0.47.1-debian13-arm64.json",
    "sapling-0.2.20261028-jj-0.47.1-debian13-x86_64.json",
)
OLDER_SAPLING_PROFILES = {
    filename: json.loads((ORACLE_ROOT / "results" / filename).read_text(encoding="utf-8"))
    for filename in OLDER_SAPLING_PROFILE_FILES
}
JJ_SYMLINK_VERSION_CAPTURES = {
    filename: json.loads((ORACLE_ROOT / "results" / filename).read_text(encoding="utf-8"))
    for filename in (
        "jj-0.45.1-macos-arm64-symlink.json",
        "jj-0.45.1-debian13-x86_64-symlink.json",
        "jj-0.46.0-macos-arm64-symlink.json",
        "jj-0.46.0-debian13-x86_64-symlink.json",
    )
}
LINKED_WORKTREE_CAPTURES = {
    filename: json.loads((ORACLE_ROOT / "results" / filename).read_text(encoding="utf-8"))
    for filename in LINKED_WORKTREE_CAPTURE_FILES
}
LINKED_WORKTREE_JJ_CAPTURES = {
    filename: json.loads((ORACLE_ROOT / "results" / filename).read_text(encoding="utf-8"))
    for filename in LINKED_WORKTREE_JJ_CAPTURE_FILES
}
OBSERVATIONS = {
    profile: {case["id"]: case for case in capture["cases"]}
    for profile, capture in CAPTURES.items()
}


@pytest.mark.parametrize("profile", CAPTURE_FILES)
def test_compatibility_capture_records_exact_client_families(profile: str) -> None:
    capture = CAPTURES[profile]

    assert capture["status"] == "captured"
    assert capture["clients"]["git"].startswith("git version ")
    assert "Sapling 0.2.20261103" in capture["clients"]["sapling"]
    assert capture["clients"]["jujutsu"].startswith("jj 0.47.1")


@pytest.mark.parametrize("profile", LINKED_WORKTREE_CAPTURE_FILES)
def test_linked_worktree_capture_reconciles_scheme_specific_exclude_sources(
    profile: str,
) -> None:
    capture = LINKED_WORKTREE_CAPTURES[profile]
    cases = {case["id"]: case for case in capture["cases"]}

    assert capture["status"] == "captured"
    assert capture["workspace"] == "Git linked worktree"
    assert "gitignore-walk-linked-worktree-" not in json.dumps(capture)
    assert capture["clients"]["git"].startswith("git version ")
    assert "Sapling 0.2.20261103" in capture["clients"]["sapling"]
    assert capture["clients"]["jujutsu"].startswith("jj 0.47.1")
    assert {name: case["ignored"] for name, case in cases.items()} == {
        "git": ["probe.commonignore"],
        "sapling.git-mode": ["probe.commonignore"],
        "jj.colocated": ["probe.worktreeignore"],
    }
    assert all(case["candidate_matches"] for case in cases.values())


@pytest.mark.parametrize("profile", LINKED_WORKTREE_JJ_CAPTURE_FILES)
def test_linked_worktree_jujutsu_only_capture_reconciles_sources(profile: str) -> None:
    capture = LINKED_WORKTREE_JJ_CAPTURES[profile]
    cases = {case["id"]: case for case in capture["cases"]}

    assert capture["status"] == "captured"
    assert capture["workspace"] == "Git linked worktree"
    assert "gitignore-walk-linked-worktree-" not in json.dumps(capture)
    assert set(capture["clients"]) == {"git", "jujutsu"}
    assert {name: case["ignored"] for name, case in cases.items()} == {
        "git": ["probe.commonignore"],
        "jj.colocated": ["probe.worktreeignore"],
    }
    assert all(case["candidate_matches"] for case in cases.values())


def test_linked_worktree_windows_capture_records_the_pinned_clients() -> None:
    capture = LINKED_WORKTREE_JJ_CAPTURES["linked-worktree-jj-0.47.1-windows-x64.json"]

    assert capture["platform"].startswith("Windows-2025Server")
    assert capture["clients"]["git"].startswith("git version 2.56.0.windows")
    assert capture["clients"]["jujutsu"].startswith("jj 0.47.1")
    assert capture["cases"][0]["query_stdout"].startswith("<temporary>/main/.git/info/exclude")
    assert "Working copy  (@) : <working-copy>" in capture["cases"][1]["status_stdout"]
    assert "Parent commit (@-): <parent>" in capture["cases"][1]["status_stdout"]


@pytest.mark.parametrize(
    ("profile", "architecture"),
    [
        ("sapling-0.2.20261103-jj-0.47.1-debian13-arm64.json", "aarch64"),
        ("sapling-0.2.20261103-jj-0.47.1-debian13-x86_64.json", "x86_64"),
    ],
)
def test_linux_compatibility_capture_records_its_architecture(
    profile: str, architecture: str
) -> None:
    assert architecture in CAPTURES[profile]["platform"]


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize("case_id", sorted(OBSERVATIONS[CAPTURE_FILES[0]]))
def test_compatibility_capture_reconciles_ignore_candidates(profile: str, case_id: str) -> None:
    observation = OBSERVATIONS[profile][case_id]

    assert observation["isolated_temporary_workspace"] is True
    assert observation["candidate_matches"] is True
    assert observation["ignored"] == ["a.tmp"]
    assert observation["included"] == ["b.log", "visible.txt"]


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize("case_id", sorted(OBSERVATIONS[CAPTURE_FILES[0]]))
def test_compatibility_capture_reconciles_ignore_source_discovery(
    profile: str, case_id: str
) -> None:
    source_discovery = OBSERVATIONS[profile][case_id]["source_discovery"]
    expected_ignored = {
        "sapling.git-mode": ["global.global", "info.priority", "local.local"],
        "sapling.sl-mode": [],
        "jj.colocated": ["global.global", "info.priority", "local.local"],
        "jj.noncolocated": ["global.global", "priority.global"],
    }

    assert source_discovery["candidate_matches"] is True
    assert source_discovery["query_files"] == [
        "global.global",
        "info.priority",
        "local.local",
        "local.priority",
        "priority.global",
    ]
    assert source_discovery["ignored"] == expected_ignored[case_id]


@pytest.mark.parametrize("profile", PATTERN_CAPTURE_FILES)
@pytest.mark.parametrize("case_id", sorted(OBSERVATIONS[CAPTURE_FILES[0]]))
def test_compatibility_capture_reconciles_path_pattern_discovery(
    profile: str, case_id: str
) -> None:
    pattern_discovery = OBSERVATIONS[profile][case_id]["pattern_discovery"]

    assert pattern_discovery["candidate_matches"] is True
    assert pattern_discovery["query_files"] == PATTERN_QUERY_FILES
    assert pattern_discovery["ignored"] == PATTERN_IGNORED
    assert pattern_discovery["included"] == PATTERN_INCLUDED


@pytest.mark.parametrize("profile", EARLIER_PATTERN_CAPTURE_FILES)
@pytest.mark.parametrize("case_id", sorted(OBSERVATIONS[CAPTURE_FILES[1]]))
def test_git_256_captures_reconcile_the_earlier_path_pattern_subset(
    profile: str, case_id: str
) -> None:
    """Retain integrity checks for Git 2.56 profiles captured before the expanded matrix."""
    pattern_discovery = OBSERVATIONS[profile][case_id]["pattern_discovery"]

    assert pattern_discovery["candidate_matches"] is True
    assert pattern_discovery["query_files"] == EARLIER_PATTERN_QUERY_FILES
    assert pattern_discovery["ignored"] == EARLIER_PATTERN_IGNORED
    assert pattern_discovery["included"] == EARLIER_PATTERN_INCLUDED


def test_jujutsu_windows_capture_reconciles_the_expanded_pattern_matrix() -> None:
    """Keep hosted Windows Jujutsu output aligned with the current pattern fixture."""
    capture = WINDOWS_JJ_CAPTURE
    assert capture["status"] == "captured"
    assert capture["platform"].startswith("Windows-2025Server")
    assert capture["clients"]["git"].startswith("git version 2.56.0.windows")
    assert capture["clients"]["jujutsu"].startswith("jj 0.47.1")
    cases = {case["id"]: case for case in capture["cases"]}
    assert set(cases) == {"jj.colocated", "jj.noncolocated"}
    for case in cases.values():
        pattern = case["pattern_discovery"]
        assert pattern["candidate_matches"]
        assert pattern["query_files"] == PATTERN_QUERY_FILES
        assert pattern["ignored"] == PATTERN_IGNORED
        assert pattern["included"] == PATTERN_INCLUDED


@pytest.mark.parametrize("filename", JJ_045_FULL_CAPTURE_FILES)
def test_jujutsu_045_capture_reconciles_config_profiles_and_legacy_symlink_behavior(
    filename: str,
) -> None:
    """Keep the full 0.45.1 profile, including its pre-0.46 symlink behavior, reviewable."""
    capture = JJ_045_FULL_CAPTURES[filename]
    assert capture["status"] == "captured"
    if "macos" in filename:
        assert capture["platform"].startswith("macOS-26")
        assert "arm64" in capture["platform"]
    else:
        assert capture["platform"].startswith("Linux-")
        assert "x86_64" in capture["platform"]
    assert capture["clients"]["jujutsu"].startswith("jj 0.45.1")
    cases = {case["id"]: case for case in capture["cases"]}
    assert set(cases) == {"jj.colocated", "jj.noncolocated"}
    for case in cases.values():
        assert case["isolated_temporary_workspace"] is True
        assert case["candidate_matches"] is True
        assert case["source_discovery"]["candidate_matches"] is True
        assert case["pattern_discovery"]["candidate_matches"] is True
        assert case["symlinked_gitignore"]["candidate_matches"] is True
        assert case["symlinked_gitignore"]["ignored"] == ["nested/probe.symlink"]
        for name in (
            "configured_global",
            "configured_system",
            "conditional_global",
            "conditional_gitdir_i",
            "conditional_worktree",
            "conditional_worktree_i",
            "conditional_onbranch",
            "conditional_remote_url",
            "conditional_gitdir_override",
            "environment_global",
            "environment_count",
            "configured_repository",
        ):
            assert case[name]["candidate_matches"] is True, (case["id"], name)


@pytest.mark.parametrize("filename", OLDER_SAPLING_PROFILE_FILES)
def test_older_sapling_capture_keeps_pattern_probe_exclusion_explicit(filename: str) -> None:
    """Validate old Sapling configuration while preserving its known pattern-probe limitation."""
    capture = OLDER_SAPLING_PROFILES[filename]
    assert capture["status"] == "captured"
    assert capture["platform"].startswith("Linux-")
    expected_architecture = "aarch64" if "arm64" in filename else "x86_64"
    assert expected_architecture in capture["platform"]
    assert capture["clients"]["sapling"].startswith("Sapling 0.2.20261028")
    assert capture["clients"]["jujutsu"].startswith("jj 0.47.1")
    assert capture["excluded_probes"] == ["sapling.sl-mode.pattern_discovery"]
    cases = {case["id"]: case for case in capture["cases"]}
    assert set(cases) == {
        "sapling.git-mode",
        "sapling.sl-mode",
        "jj.colocated",
        "jj.noncolocated",
    }
    for case_id in ("sapling.git-mode", "sapling.sl-mode"):
        case = cases[case_id]
        assert case["candidate_matches"] is True
        if case_id == "sapling.sl-mode":
            assert case["pattern_discovery"] == {
                "native_status": "skipped",
                "reason": "Excluded by --skip-sapling-pattern-mode sl.",
            }
        else:
            assert case["pattern_discovery"]["candidate_matches"] is True
            assert case["pattern_discovery"]["query_files"] == PATTERN_QUERY_FILES
            assert case["pattern_discovery"]["ignored"] == PATTERN_IGNORED
            assert case["pattern_discovery"]["included"] == PATTERN_INCLUDED
        assert case["source_discovery"]["candidate_matches"] is True
        for name in (
            "configured_global",
            "configured_system",
            "conditional_global",
            "conditional_gitdir_i",
            "conditional_worktree",
            "conditional_worktree_i",
            "conditional_onbranch",
            "conditional_remote_url",
            "conditional_gitdir_override",
            "environment_global",
            "environment_count",
            "configured_repository",
        ):
            assert case[name]["candidate_matches"] is True, (case_id, name)
    for case_id in ("jj.colocated", "jj.noncolocated"):
        assert cases[case_id]["pattern_discovery"]["candidate_matches"] is True


@pytest.mark.parametrize("profile", SYMLINK_CAPTURE_FILES)
def test_native_capture_reconciles_symlinked_nested_gitignore(profile: str) -> None:
    observations = OBSERVATIONS[profile]
    expected_ignored = {
        "sapling.git-mode": [],
        "sapling.sl-mode": ["nested/probe.symlink"],
        "jj.colocated": [],
        "jj.noncolocated": [],
    }

    for case_id, observation in observations.items():
        probe = observation["symlinked_gitignore"]
        assert probe["native_status"] == "captured"
        assert probe["source_is_symlink"] is True
        assert probe["source_target_outside_workspace"] is True
        assert probe["candidate_matches"] is True
        assert probe["query_files"] == ["nested/probe.symlink"]
        assert probe["ignored"] == expected_ignored[case_id]


@pytest.mark.parametrize(
    ("filename", "version", "expected_follow"),
    [
        ("jj-0.45.1-macos-arm64-symlink.json", "0.45.1", True),
        ("jj-0.45.1-debian13-x86_64-symlink.json", "0.45.1", True),
        ("jj-0.46.0-macos-arm64-symlink.json", "0.46.0", False),
        ("jj-0.46.0-debian13-x86_64-symlink.json", "0.46.0", False),
    ],
)
def test_jj_release_boundary_for_symlinked_ignore_sources(
    filename: str, version: str, expected_follow: bool
) -> None:
    capture = JJ_SYMLINK_VERSION_CAPTURES[filename]
    expected_ignored = ["nested/probe.symlink"] if expected_follow else []

    assert capture["status"] == "captured"
    if "macos" in filename:
        assert capture["platform"].startswith("macOS-26")
    else:
        assert capture["platform"].startswith("Linux-")
        assert "x86_64" in capture["platform"]
    assert capture["clients"]["jujutsu"].startswith(f"jj {version}")
    assert capture["expected_follow_symlink"] is expected_follow
    assert {case["id"] for case in capture["cases"]} == {"jj.colocated", "jj.noncolocated"}
    for case in capture["cases"]:
        probe = case
        assert probe["native_status"] == "captured"
        assert probe["source_is_symlink"] is True
        assert probe["source_target_outside_workspace"] is True
        assert probe["candidate_matches"] is True
        assert probe["ignored"] == expected_ignored


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize("case_id", sorted(OBSERVATIONS[CAPTURE_FILES[0]]))
def test_compatibility_capture_reconciles_configured_global_ignore(
    profile: str, case_id: str
) -> None:
    configured_global = OBSERVATIONS[profile][case_id]["configured_global"]
    expected_ignored = {
        "sapling.git-mode": ["configured.custom"],
        "sapling.sl-mode": [],
        "jj.colocated": ["configured.custom"],
        "jj.noncolocated": ["configured.custom"],
    }

    assert configured_global["candidate_matches"] is True
    assert configured_global["query_files"] == [
        "configured.custom",
        "configured.global",
        "configured.system",
        "configured.visible",
    ]
    assert configured_global["ignored"] == expected_ignored[case_id]


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize("case_id", sorted(OBSERVATIONS[CAPTURE_FILES[0]]))
def test_compatibility_capture_reconciles_system_global_ignore(profile: str, case_id: str) -> None:
    configured_system = OBSERVATIONS[profile][case_id]["configured_system"]
    expected_ignored = {
        "sapling.git-mode": ["system.system"],
        "sapling.sl-mode": [],
        "jj.colocated": ["system.system"],
        "jj.noncolocated": ["system.system"],
    }

    assert configured_system["candidate_matches"] is True
    assert configured_system["query_files"] == [
        "system.custom",
        "system.system",
        "system.visible",
    ]
    assert configured_system["ignored"] == expected_ignored[case_id]


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize("case_id", sorted(OBSERVATIONS[CAPTURE_FILES[0]]))
def test_compatibility_capture_reconciles_conditional_global_ignore(
    profile: str, case_id: str
) -> None:
    conditional_global = OBSERVATIONS[profile][case_id]["conditional_global"]
    expected_ignored = {
        "sapling.git-mode": ["conditional.custom"],
        "sapling.sl-mode": [],
        "jj.colocated": ["conditional.custom"],
        "jj.noncolocated": [],
    }

    assert conditional_global["candidate_matches"] is True
    assert conditional_global["query_files"] == [
        "conditional.custom",
        "conditional.global",
        "conditional.visible",
    ]
    assert conditional_global["ignored"] == expected_ignored[case_id]


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize("case_id", sorted(OBSERVATIONS[CAPTURE_FILES[0]]))
def test_compatibility_capture_reconciles_case_insensitive_gitdir_include(
    profile: str, case_id: str
) -> None:
    conditional_gitdir_i = OBSERVATIONS[profile][case_id]["conditional_gitdir_i"]
    expected_ignored = {
        "sapling.git-mode": ["conditional.casefold"],
        "sapling.sl-mode": [],
        "jj.colocated": ["conditional.casefold"],
        "jj.noncolocated": [],
    }

    assert conditional_gitdir_i["candidate_matches"] is True
    assert conditional_gitdir_i["query_files"] == [
        "conditional.casefold",
        "conditional.global",
        "conditional.visible",
    ]
    assert conditional_gitdir_i["ignored"] == expected_ignored[case_id]


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize("case_id", sorted(OBSERVATIONS[CAPTURE_FILES[0]]))
def test_compatibility_capture_reconciles_worktree_conditional_include(
    profile: str, case_id: str
) -> None:
    conditional_worktree = OBSERVATIONS[profile][case_id]["conditional_worktree"]
    expected_ignored = (
        ["conditional.worktree"]
        if case_id == "sapling.git-mode" and conditional_worktree["git_config_matches"]
        else []
    )

    assert conditional_worktree["candidate_matches"] is True
    assert conditional_worktree["query_files"] == [
        "conditional.visible",
        "conditional.worktree",
    ]
    assert conditional_worktree["ignored"] == expected_ignored
    assert conditional_worktree["native_matches_git_config"] is (
        "conditional.worktree" in expected_ignored or not conditional_worktree["git_config_matches"]
    )


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize("case_id", sorted(OBSERVATIONS[CAPTURE_FILES[0]]))
def test_compatibility_capture_reconciles_case_insensitive_worktree_include(
    profile: str, case_id: str
) -> None:
    conditional_worktree_i = OBSERVATIONS[profile][case_id]["conditional_worktree_i"]
    expected_ignored = (
        ["conditional.worktreei"]
        if case_id == "sapling.git-mode" and conditional_worktree_i["git_config_matches"]
        else []
    )

    assert conditional_worktree_i["candidate_matches"] is True
    assert conditional_worktree_i["query_files"] == [
        "conditional.visible",
        "conditional.worktreei",
    ]
    assert conditional_worktree_i["ignored"] == expected_ignored
    assert conditional_worktree_i["native_matches_git_config"] is (
        "conditional.worktreei" in expected_ignored
        or not conditional_worktree_i["git_config_matches"]
    )


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize("case_id", sorted(OBSERVATIONS[CAPTURE_FILES[0]]))
def test_compatibility_capture_records_caller_gitdir_context_divergence(
    profile: str, case_id: str
) -> None:
    conditional_override = OBSERVATIONS[profile][case_id]["conditional_gitdir_override"]

    assert conditional_override["git_config_matches"] is True
    assert conditional_override["git_config_path"] == "<home>/gitdir-override-ignore"
    assert conditional_override["native_matches_git_config"] is False
    assert conditional_override["candidate_matches"] is True
    assert conditional_override["ignored"] == []
    assert conditional_override["query_files"] == [
        "conditional.gitdiroverride",
        "conditional.gitdirvisible",
    ]


def test_git_256_profile_records_jujutsu_worktree_include_divergence() -> None:
    profile = "sapling-0.2.20261103-jj-0.47.1-git-2.56.0-macos-arm64.json"
    capture = CAPTURES[profile]
    colocated = OBSERVATIONS[profile]["jj.colocated"]["conditional_worktree"]
    colocated_i = OBSERVATIONS[profile]["jj.colocated"]["conditional_worktree_i"]

    assert capture["clients"]["git"].startswith("git version 2.56.0")
    assert colocated["git_config_matches"] is True
    assert colocated["ignored"] == []
    assert colocated["native_matches_git_config"] is False
    assert colocated_i["git_config_matches"] is True
    assert colocated_i["ignored"] == []
    assert colocated_i["native_matches_git_config"] is False


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize("case_id", sorted(OBSERVATIONS[CAPTURE_FILES[0]]))
def test_compatibility_capture_reconciles_onbranch_conditional_global_ignore(
    profile: str, case_id: str
) -> None:
    conditional_onbranch = OBSERVATIONS[profile][case_id]["conditional_onbranch"]
    expected_ignored = {
        "sapling.git-mode": ["conditional.branch"],
        "sapling.sl-mode": [],
        "jj.colocated": ["conditional.branch"],
        "jj.noncolocated": ["conditional.branch"],
    }

    assert conditional_onbranch["candidate_matches"] is True
    assert conditional_onbranch["query_files"] == [
        "conditional.branch",
        "conditional.global",
        "conditional.visible",
    ]
    assert conditional_onbranch["ignored"] == expected_ignored[case_id]


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize("case_id", sorted(OBSERVATIONS[CAPTURE_FILES[0]]))
def test_compatibility_capture_reconciles_remote_url_conditional_global_ignore(
    profile: str, case_id: str
) -> None:
    conditional_remote = OBSERVATIONS[profile][case_id]["conditional_remote_url"]
    expected_ignored = {
        "sapling.git-mode": ["conditional.remote"],
        "sapling.sl-mode": [],
        "jj.colocated": ["conditional.remote"],
        "jj.noncolocated": ["conditional.remote"],
    }

    assert conditional_remote["candidate_matches"] is True
    assert conditional_remote["query_files"] == [
        "conditional.global",
        "conditional.remote",
        "conditional.visible",
    ]
    assert conditional_remote["ignored"] == expected_ignored[case_id]


@pytest.mark.parametrize("profile", CAPTURE_FILES)
@pytest.mark.parametrize("case_id", sorted(OBSERVATIONS[CAPTURE_FILES[0]]))
def test_compatibility_capture_reconciles_repository_core_excludes_file(
    profile: str, case_id: str
) -> None:
    configured_repository = OBSERVATIONS[profile][case_id]["configured_repository"]
    expected_ignored = {
        "sapling.git-mode": ["repository.local"],
        "sapling.sl-mode": [],
        "jj.colocated": ["repository.local"],
        "jj.noncolocated": ["repository.local"],
    }

    assert configured_repository["candidate_matches"] is True
    assert configured_repository["query_files"] == [
        "repository.global",
        "repository.local",
        "repository.system",
        "repository.visible",
    ]
    assert configured_repository["ignored"] == expected_ignored[case_id]


@pytest.mark.parametrize("profile", ENVIRONMENT_GLOBAL_CAPTURE_FILES)
@pytest.mark.parametrize("case_id", sorted(OBSERVATIONS[CAPTURE_FILES[0]]))
def test_compatibility_capture_reconciles_environment_selected_global_config(
    profile: str, case_id: str
) -> None:
    observation = OBSERVATIONS[profile][case_id]["environment_global"]
    expected = {
        "sapling.git-mode": ["environment.global"],
        "sapling.sl-mode": [],
        "jj.colocated": ["environment.global"],
        "jj.noncolocated": ["environment.global"],
    }

    assert observation["config_environment_variable"] == "GIT_CONFIG_GLOBAL"
    assert observation["query_files"] == ["environment.global", "environment.visible"]
    assert observation["ignored"] == expected[case_id]
    assert observation["included"] == sorted(
        set(observation["query_files"]) - set(expected[case_id])
    )
    assert observation["candidate_matches"] is True


@pytest.mark.parametrize(
    ("case_id", "expected_markers"),
    [
        ("sapling.git-mode", [".git"]),
        ("sapling.sl-mode", [".sl"]),
        ("jj.colocated", [".git", ".jj"]),
        ("jj.noncolocated", [".jj"]),
    ],
)
@pytest.mark.parametrize("profile", CAPTURE_FILES)
def test_compatibility_modes_keep_their_distinct_repository_markers(
    profile: str, case_id: str, expected_markers: list[str]
) -> None:
    assert OBSERVATIONS[profile][case_id]["metadata_markers"] == expected_markers


def test_jujutsu_probe_records_that_status_snapshotted_only_a_temp_workspace() -> None:
    for observations in OBSERVATIONS.values():
        for case_id in ("jj.colocated", "jj.noncolocated"):
            observation: dict[str, Any] = observations[case_id]
            assert observation["status_snapshots_disposable_workspace"] is True
