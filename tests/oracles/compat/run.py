"""Probe Sapling and Jujutsu ignore behavior in disposable repositories."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _run(
    command: Sequence[str], *, cwd: Path, environment: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        env=dict(environment),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )


def _capture_sapling(executable: str, mode: str, fixture: Mapping[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"gitignore-walk-sapling-{mode}-") as temporary:
        base = Path(temporary)
        home = base / "home"
        home.mkdir()
        root = base / "workspace"
        root.mkdir()
        environment = {
            **os.environ,
            "HOME": str(home),
            "USERPROFILE": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "SL_USER": "Oracle <oracle@example.invalid>",
            "PAGER": "cat",
            "HGPLAIN": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        if mode == "git":
            _require_success(
                _run(["git", "init", "-q", str(root)], cwd=root, environment=environment),
                "git init",
            )
            _set_oracle_branch(root, environment)
            _set_oracle_remote(root, environment)
        else:
            _require_success(
                _run([executable, "init", str(root)], cwd=root, environment=environment), "sl init"
            )
        _write_files(root, fixture["probe_files"])
        _write_source_probes(root, home, fixture)
        status = _run([executable, "status", "-iu", "--print0"], cwd=root, environment=environment)
        _require_success(status, "sl status")
        included, ignored = _sapling_status_paths(status.stdout)
        source_query_files = set(fixture["source_query_files"])
        source_ignored = sorted(ignored & source_query_files)
        pattern_query_files = set(fixture["pattern_query_files"])
        _write_pattern_probes(root, fixture)
        pattern_status = _run(
            [executable, "status", "-iu", "--print0"], cwd=root, environment=environment
        )
        _require_success(pattern_status, "sl status pattern probes")
        _, pattern_status_ignored = _sapling_status_paths(pattern_status.stdout)
        pattern_ignored = _expand_ignored_paths(pattern_status_ignored, pattern_query_files)
        (
            configured_global,
            configured_system,
            conditional_global,
            conditional_gitdir_i,
            conditional_worktree,
            conditional_worktree_i,
            conditional_onbranch,
            conditional_remote,
            configured_repository,
        ) = _capture_configured_global_sapling(executable, mode, root, home, environment, fixture)
        return {
            "id": f"sapling.{mode}-mode",
            "vcs": "sapling",
            "mode": mode,
            "version": _version(executable),
            "included": sorted(included & set(fixture["query_files"])),
            "ignored": sorted(ignored & set(fixture["query_files"])),
            "status_exit_code": status.returncode,
            "status_stdout": status.stdout.replace(str(root), "<workspace>"),
            "status_stderr": status.stderr.replace(str(root), "<workspace>"),
            "metadata_markers": sorted(
                marker for marker in (".git", ".sl") if (root / marker).exists()
            ),
            "isolated_temporary_workspace": True,
            "source_discovery": {
                "query_files": sorted(source_query_files),
                "ignored": source_ignored,
                "included": sorted(source_query_files - set(source_ignored)),
            },
            "pattern_discovery": {
                "query_files": sorted(pattern_query_files),
                "ignored": sorted(pattern_ignored),
                "included": sorted(pattern_query_files - pattern_ignored),
                "status_stdout": pattern_status.stdout.replace(str(root), "<workspace>"),
                "status_stderr": pattern_status.stderr.replace(str(root), "<workspace>"),
            },
            "configured_global": configured_global,
            "configured_system": configured_system,
            "conditional_global": conditional_global,
            "conditional_gitdir_i": conditional_gitdir_i,
            "conditional_worktree": conditional_worktree,
            "conditional_worktree_i": conditional_worktree_i,
            "conditional_onbranch": conditional_onbranch,
            "conditional_remote_url": conditional_remote,
            "configured_repository": configured_repository,
        }


def _capture_jj(executable: str, mode: str, fixture: Mapping[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"gitignore-walk-jj-{mode}-") as temporary:
        base = Path(temporary)
        home = base / "home"
        home.mkdir()
        config_dir = home / ".config" / "jj"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text(
            '[user]\nname = "Oracle"\nemail = "oracle@example.invalid"\n',
            encoding="utf-8",
        )
        root = base / "workspace"
        root.mkdir()
        environment = {
            **os.environ,
            "HOME": str(home),
            "USERPROFILE": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "PAGER": "cat",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        command = [executable, "git", "init"]
        if mode == "noncolocated":
            command.append("--no-colocate")
        command.append(str(root))
        _require_success(_run(command, cwd=root, environment=environment), "jj git init")
        _set_oracle_branch(root, environment)
        _set_oracle_remote_jj(executable, root, environment)
        _write_files(root, fixture["probe_files"])
        _write_source_probes(root, home, fixture)
        status = _run([executable, "status", "--no-pager"], cwd=root, environment=environment)
        _require_success(status, "jj status")
        listed = _run([executable, "file", "list"], cwd=root, environment=environment)
        _require_success(listed, "jj file list")
        files = _jujutsu_paths(listed.stdout)
        query_files = set(fixture["query_files"])
        source_query_files = set(fixture["source_query_files"])
        source_ignored = sorted(source_query_files - files)
        pattern_query_files = set(fixture["pattern_query_files"])
        _write_pattern_probes(root, fixture)
        pattern_status = _run(
            [executable, "status", "--no-pager"], cwd=root, environment=environment
        )
        _require_success(pattern_status, "jj status pattern probes")
        pattern_listed = _run([executable, "file", "list"], cwd=root, environment=environment)
        _require_success(pattern_listed, "jj file list pattern probes")
        pattern_files = _jujutsu_paths(pattern_listed.stdout)
        pattern_ignored = pattern_query_files - pattern_files
        (
            configured_global,
            configured_system,
            conditional_global,
            conditional_gitdir_i,
            conditional_worktree,
            conditional_worktree_i,
            conditional_onbranch,
            conditional_remote,
            configured_repository,
        ) = _capture_configured_global_jj(executable, mode, root, home, environment, fixture)
        return {
            "id": f"jj.{mode}",
            "vcs": "jujutsu",
            "mode": mode,
            "version": _version(executable),
            "included": sorted(files & query_files),
            "ignored": sorted(query_files - files),
            "status_exit_code": status.returncode,
            "status_stdout": status.stdout.replace(str(root), "<workspace>"),
            "status_stderr": status.stderr.replace(str(root), "<workspace>"),
            "metadata_markers": sorted(
                marker for marker in (".git", ".jj") if (root / marker).exists()
            ),
            "isolated_temporary_workspace": True,
            "status_snapshots_disposable_workspace": True,
            "source_discovery": {
                "query_files": sorted(source_query_files),
                "ignored": source_ignored,
                "included": sorted(source_query_files - set(source_ignored)),
            },
            "pattern_discovery": {
                "query_files": sorted(pattern_query_files),
                "ignored": sorted(pattern_ignored),
                "included": sorted(pattern_query_files - pattern_ignored),
                "status_stdout": pattern_status.stdout.replace(str(root), "<workspace>"),
                "status_stderr": pattern_status.stderr.replace(str(root), "<workspace>"),
                "file_list_stdout": pattern_listed.stdout.replace(str(root), "<workspace>"),
            },
            "configured_global": configured_global,
            "configured_system": configured_system,
            "conditional_global": conditional_global,
            "conditional_gitdir_i": conditional_gitdir_i,
            "conditional_worktree": conditional_worktree,
            "conditional_worktree_i": conditional_worktree_i,
            "conditional_onbranch": conditional_onbranch,
            "conditional_remote_url": conditional_remote,
            "configured_repository": configured_repository,
        }


def _write_source_probes(root: Path, home: Path, fixture: Mapping[str, Any]) -> None:
    """Seed isolated Git-style global and per-clone ignore sources."""
    _write_files(root, fixture["source_probe_files"])
    xdg_ignore = home / ".config" / "git" / "ignore"
    xdg_ignore.parent.mkdir(parents=True, exist_ok=True)
    xdg_ignore.write_text(fixture["source_rules"]["xdg_git_ignore"], encoding="utf-8")
    git_dir = root / ".git"
    if git_dir.is_dir():
        info_dir = git_dir / "info"
        info_dir.mkdir(exist_ok=True)
        (info_dir / "exclude").write_text(
            fixture["source_rules"]["git_info_exclude"], encoding="utf-8"
        )


def _write_configured_global_probe(root: Path, home: Path, fixture: Mapping[str, Any]) -> list[str]:
    """Configure system/global ``core.excludesFile`` and return its probe paths."""
    custom_ignore = home / "custom-git-ignore"
    custom_ignore.write_text(fixture["source_rules"]["core_excludes_file"], encoding="utf-8")
    system_ignore = home / "system-git-ignore"
    system_ignore.write_text(fixture["source_rules"]["system_core_excludes_file"], encoding="utf-8")
    (home / "system-git-config").write_text(
        f"[core]\n\texcludesFile = {system_ignore}\n", encoding="utf-8"
    )
    (home / "included-git-config").write_text(
        f"[core]\n\texcludesFile = {custom_ignore}\n", encoding="utf-8"
    )
    (home / ".gitconfig").write_text("[include]\n\tpath = included-git-config\n", encoding="utf-8")
    files: Mapping[str, str] = fixture["configured_global_probe_files"]
    _write_files(root, files)
    return sorted(files)


def _system_config_environment(environment: Mapping[str, str], home: Path) -> dict[str, str]:
    """Enable an isolated system Git config while retaining the disposable home settings."""
    result = dict(environment)
    result.pop("GIT_CONFIG_NOSYSTEM", None)
    result["GIT_CONFIG_SYSTEM"] = str(home / "system-git-config")
    return result


def _capture_configured_global_sapling(
    executable: str,
    mode: str,
    root: Path,
    home: Path,
    environment: Mapping[str, str],
    fixture: Mapping[str, Any],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    """Capture Sapling's global-over-system and system-over-XDG source selection."""
    query_files = _write_configured_global_probe(root, home, fixture)
    probe_environment = _system_config_environment(environment, home)
    status = _run(
        [executable, "status", "-iu", "--print0"], cwd=root, environment=probe_environment
    )
    _require_success(status, "sl status configured core.excludesFile")
    _, ignored_paths = _sapling_status_paths(status.stdout)
    ignored = sorted(ignored_paths & set(query_files))
    expected = fixture["expected_configured_global_ignored"][f"sapling.{mode}-mode"]
    configured_global = {
        "query_files": query_files,
        "ignored": ignored,
        "included": sorted(set(query_files) - set(ignored)),
        "candidate_matches": ignored == expected,
        "status_stdout": status.stdout.replace(str(root), "<workspace>"),
    }
    (home / ".gitconfig").unlink(missing_ok=True)
    system_files: Mapping[str, str] = fixture["configured_system_probe_files"]
    _write_files(root, system_files)
    status = _run(
        [executable, "status", "-iu", "--print0"], cwd=root, environment=probe_environment
    )
    _require_success(status, "sl status system core.excludesFile")
    _, ignored_paths = _sapling_status_paths(status.stdout)
    system_query_files = sorted(system_files)
    system_ignored = sorted(ignored_paths & set(system_query_files))
    expected = fixture["expected_configured_system_ignored"][f"sapling.{mode}-mode"]
    configured_system = {
        "query_files": system_query_files,
        "ignored": system_ignored,
        "included": sorted(set(system_query_files) - set(system_ignored)),
        "candidate_matches": system_ignored == expected,
        "status_stdout": status.stdout.replace(str(root), "<workspace>"),
    }
    conditional_global = _capture_conditional_global_sapling(
        executable, mode, root, home, probe_environment, fixture
    )
    conditional_gitdir_i = _capture_conditional_gitdir_i_sapling(
        executable, mode, root, home, probe_environment, fixture
    )
    conditional_worktree = _capture_conditional_worktree_sapling(
        executable, mode, root, home, probe_environment, fixture
    )
    conditional_worktree_i = _capture_conditional_worktree_i_sapling(
        executable, mode, root, home, probe_environment, fixture
    )
    conditional_onbranch = _capture_conditional_onbranch_sapling(
        executable, mode, root, home, probe_environment, fixture
    )
    conditional_remote = _capture_conditional_remote_sapling(
        executable, mode, root, home, probe_environment, fixture
    )
    configured_repository = _capture_configured_repository_sapling(
        executable, mode, root, home, probe_environment, fixture
    )
    return (
        configured_global,
        configured_system,
        conditional_global,
        conditional_gitdir_i,
        conditional_worktree,
        conditional_worktree_i,
        conditional_onbranch,
        conditional_remote,
        configured_repository,
    )


def _capture_configured_global_jj(
    executable: str,
    mode: str,
    root: Path,
    home: Path,
    environment: Mapping[str, str],
    fixture: Mapping[str, Any],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    """Capture Jujutsu's global-over-system and system-over-XDG source selection."""
    query_files = _write_configured_global_probe(root, home, fixture)
    probe_environment = _system_config_environment(environment, home)
    status = _run([executable, "status", "--no-pager"], cwd=root, environment=probe_environment)
    _require_success(status, "jj status configured core.excludesFile")
    listed = _run([executable, "file", "list"], cwd=root, environment=probe_environment)
    _require_success(listed, "jj file list configured core.excludesFile")
    included_paths = _jujutsu_paths(listed.stdout)
    ignored = sorted(set(query_files) - included_paths)
    expected = fixture["expected_configured_global_ignored"][f"jj.{mode}"]
    configured_global = {
        "query_files": query_files,
        "ignored": ignored,
        "included": sorted(set(query_files) & included_paths),
        "candidate_matches": ignored == expected,
        "status_stdout": status.stdout.replace(str(root), "<workspace>"),
        "file_list_stdout": listed.stdout.replace(str(root), "<workspace>"),
    }
    (home / ".gitconfig").unlink(missing_ok=True)
    system_files: Mapping[str, str] = fixture["configured_system_probe_files"]
    _write_files(root, system_files)
    status = _run([executable, "status", "--no-pager"], cwd=root, environment=probe_environment)
    _require_success(status, "jj status system core.excludesFile")
    listed = _run([executable, "file", "list"], cwd=root, environment=probe_environment)
    _require_success(listed, "jj file list system core.excludesFile")
    included_paths = _jujutsu_paths(listed.stdout)
    system_query_files = sorted(system_files)
    system_ignored = sorted(set(system_query_files) - included_paths)
    expected = fixture["expected_configured_system_ignored"][f"jj.{mode}"]
    configured_system = {
        "query_files": system_query_files,
        "ignored": system_ignored,
        "included": sorted(set(system_query_files) & included_paths),
        "candidate_matches": system_ignored == expected,
        "status_stdout": status.stdout.replace(str(root), "<workspace>"),
        "file_list_stdout": listed.stdout.replace(str(root), "<workspace>"),
    }
    conditional_global = _capture_conditional_global_jj(
        executable, mode, root, home, probe_environment, fixture
    )
    conditional_gitdir_i = _capture_conditional_gitdir_i_jj(
        executable, mode, root, home, probe_environment, fixture
    )
    conditional_worktree = _capture_conditional_worktree_jj(
        executable, mode, root, home, probe_environment, fixture
    )
    conditional_worktree_i = _capture_conditional_worktree_i_jj(
        executable, mode, root, home, probe_environment, fixture
    )
    conditional_onbranch = _capture_conditional_onbranch_jj(
        executable, mode, root, home, probe_environment, fixture
    )
    conditional_remote = _capture_conditional_remote_jj(
        executable, mode, root, home, probe_environment, fixture
    )
    configured_repository = _capture_configured_repository_jj(
        executable, mode, root, home, probe_environment, fixture
    )
    return (
        configured_global,
        configured_system,
        conditional_global,
        conditional_gitdir_i,
        conditional_worktree,
        conditional_worktree_i,
        conditional_onbranch,
        conditional_remote,
        configured_repository,
    )


def _write_conditional_global_probe(
    root: Path, home: Path, fixture: Mapping[str, Any]
) -> list[str]:
    """Configure a Git-dir conditional include and create its decision probes."""
    custom_ignore = home / "conditional-git-ignore"
    custom_ignore.write_text(fixture["source_rules"]["core_excludes_file"], encoding="utf-8")
    included_config = home / "conditional-git-config"
    included_config.write_text(f"[core]\n\texcludesFile = {custom_ignore}\n", encoding="utf-8")
    (home / ".gitconfig").write_text(
        '[includeIf "gitdir:**/workspace/.git"]\n\tpath = conditional-git-config\n',
        encoding="utf-8",
    )
    files: Mapping[str, str] = fixture["conditional_global_probe_files"]
    _write_files(root, files)
    return sorted(files)


def _write_conditional_onbranch_probe(
    root: Path, home: Path, fixture: Mapping[str, Any]
) -> list[str]:
    """Configure an on-branch include and create its ignore-decision probes."""
    custom_ignore = home / "onbranch-git-ignore"
    custom_ignore.write_text(fixture["conditional_branch_ignore"], encoding="utf-8")
    included_config = home / "onbranch-git-config"
    included_config.write_text(f"[core]\n\texcludesFile = {custom_ignore}\n", encoding="utf-8")
    (home / ".gitconfig").write_text(
        '[includeIf "onbranch:main"]\n\tpath = onbranch-git-config\n', encoding="utf-8"
    )
    files: Mapping[str, str] = fixture["conditional_branch_probe_files"]
    _write_files(root, files)
    return sorted(files)


def _write_conditional_gitdir_i_probe(
    root: Path, home: Path, fixture: Mapping[str, Any]
) -> list[str]:
    """Configure a case-insensitive Git-dir include and create its decision probes."""
    custom_ignore = home / "case-insensitive-gitdir-ignore"
    custom_ignore.write_text(fixture["conditional_gitdir_i_ignore"], encoding="utf-8")
    included_config = home / "case-insensitive-gitdir-config"
    included_config.write_text(f"[core]\n\texcludesFile = {custom_ignore}\n", encoding="utf-8")
    (home / ".gitconfig").write_text(
        '[includeIf "gitdir/i:**/WORKSPACE/.GIT"]\n\tpath = case-insensitive-gitdir-config\n',
        encoding="utf-8",
    )
    files: Mapping[str, str] = fixture["conditional_gitdir_i_probe_files"]
    _write_files(root, files)
    return sorted(files)


def _write_conditional_worktree_probe(
    root: Path,
    home: Path,
    environment: Mapping[str, str],
    fixture: Mapping[str, Any],
    *,
    case_insensitive: bool = False,
) -> tuple[list[str], bool]:
    """Configure a worktree include and report whether the selected Git resolves it."""
    suffix = "_i" if case_insensitive else ""
    condition = "worktree/i" if case_insensitive else "worktree"
    path_pattern = root.resolve().as_posix()
    if case_insensitive:
        path_pattern = path_pattern.upper()
    custom_ignore = home / f"worktree{suffix}-conditional-ignore"
    custom_ignore.write_text(fixture[f"conditional_worktree{suffix}_ignore"], encoding="utf-8")
    included_config = home / f"worktree{suffix}-conditional-config"
    included_config.write_text(f"[core]\n\texcludesFile = {custom_ignore}\n", encoding="utf-8")
    (home / ".gitconfig").write_text(
        f'[includeIf "{condition}:{path_pattern}"]\n\tpath = worktree{suffix}-conditional-config\n',
        encoding="utf-8",
    )
    files: Mapping[str, str] = fixture[f"conditional_worktree{suffix}_probe_files"]
    _write_files(root, files)

    config_environment = _isolated_worktree_environment(home, environment)
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"):
        config_environment.pop(name, None)
    if git_dir := _workspace_git_dir(root):
        config_environment["GIT_DIR"] = str(git_dir)
    result = _run(
        ["git", "config", "--includes", "--path", "--get", "core.excludesFile"],
        cwd=root,
        environment=config_environment,
    )
    if result.returncode not in (0, 1) or result.stderr:
        _require_success(result, "git config worktree conditional core.excludesFile")
    included = result.returncode == 0 and bool(result.stdout.strip())
    return sorted(files), included


def _isolated_worktree_environment(home: Path, environment: Mapping[str, str]) -> dict[str, str]:
    """Remove higher-scope fixture state before probing worktree includes."""
    result = dict(environment)
    result.pop("GIT_CONFIG_SYSTEM", None)
    result["GIT_CONFIG_NOSYSTEM"] = "1"
    result["GIT_CONFIG_GLOBAL"] = str(home / ".gitconfig")
    return result


def _write_conditional_remote_probe(
    root: Path, home: Path, fixture: Mapping[str, Any]
) -> list[str]:
    """Configure a remote-URL include and create its ignore-decision probes."""
    custom_ignore = home / "remote-url-git-ignore"
    custom_ignore.write_text(fixture["conditional_remote_ignore"], encoding="utf-8")
    included_config = home / "remote-url-git-config"
    included_config.write_text(f"[core]\n\texcludesFile = {custom_ignore}\n", encoding="utf-8")
    url_pattern = fixture["conditional_remote_url"]
    (home / ".gitconfig").write_text(
        f'[includeIf "hasconfig:remote.*.url:{url_pattern}"]\n\tpath = remote-url-git-config\n',
        encoding="utf-8",
    )
    files: Mapping[str, str] = fixture["conditional_remote_probe_files"]
    _write_files(root, files)
    return sorted(files)


def _write_configured_repository_probe(
    root: Path,
    home: Path,
    environment: Mapping[str, str],
    fixture: Mapping[str, Any],
) -> list[str]:
    """Set a repository-local excludes file and create its precedence probes."""
    (home / ".gitconfig").unlink(missing_ok=True)
    custom_ignore = home / "repository-git-ignore"
    custom_ignore.write_text(fixture["configured_repository_ignore"], encoding="utf-8")
    git_dir = _workspace_git_dir(root)
    if git_dir is not None:
        _require_success(
            _run(
                ["git", f"--git-dir={git_dir}", "config", "core.excludesFile", str(custom_ignore)],
                cwd=root,
                environment=environment,
            ),
            "set repository core.excludesFile",
        )
    files: Mapping[str, str] = fixture["configured_repository_probe_files"]
    _write_files(root, files)
    return sorted(files)


def _workspace_git_dir(root: Path) -> Path | None:
    """Return the Git directory for a disposable Git or Jujutsu workspace, if present."""
    candidates = (root / ".git", root / ".jj" / "repo" / "store" / "git")
    return next((path for path in candidates if path.is_dir()), None)


def _set_oracle_branch(root: Path, environment: Mapping[str, str]) -> None:
    """Give each Git-backed disposable workspace the same current branch name."""
    git_dir = _workspace_git_dir(root)
    if git_dir is not None:
        _require_success(
            _run(
                ["git", f"--git-dir={git_dir}", "symbolic-ref", "HEAD", "refs/heads/main"],
                cwd=root,
                environment=environment,
            ),
            "set disposable Git branch",
        )


def _set_oracle_remote(root: Path, environment: Mapping[str, str]) -> None:
    """Add a deterministic remote URL to a Sapling Git-storage probe."""
    _require_success(
        _run(
            ["git", "remote", "add", "origin", "https://example.invalid/acme/project.git"],
            cwd=root,
            environment=environment,
        ),
        "set disposable Git remote",
    )


def _set_oracle_remote_jj(executable: str, root: Path, environment: Mapping[str, str]) -> None:
    """Add a deterministic remote URL through Jujutsu's Git backend."""
    _require_success(
        _run(
            [
                executable,
                "git",
                "remote",
                "add",
                "origin",
                "https://example.invalid/acme/project.git",
            ],
            cwd=root,
            environment=environment,
        ),
        "set disposable Jujutsu Git remote",
    )


def _capture_conditional_global_sapling(
    executable: str,
    mode: str,
    root: Path,
    home: Path,
    environment: Mapping[str, str],
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture Sapling's Git-dir conditional global ignore behavior."""
    query_files = _write_conditional_global_probe(root, home, fixture)
    status = _run([executable, "status", "-iu", "--print0"], cwd=root, environment=environment)
    _require_success(status, "sl status conditional core.excludesFile")
    _, ignored_paths = _sapling_status_paths(status.stdout)
    ignored = sorted(ignored_paths & set(query_files))
    expected = fixture["expected_conditional_global_ignored"][f"sapling.{mode}-mode"]
    return {
        "query_files": query_files,
        "ignored": ignored,
        "included": sorted(set(query_files) - set(ignored)),
        "candidate_matches": ignored == expected,
        "status_stdout": status.stdout.replace(str(root), "<workspace>"),
    }


def _capture_conditional_gitdir_i_sapling(
    executable: str,
    mode: str,
    root: Path,
    home: Path,
    environment: Mapping[str, str],
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture Sapling's case-insensitive Git-dir conditional ignore behavior."""
    query_files = _write_conditional_gitdir_i_probe(root, home, fixture)
    status = _run([executable, "status", "-iu", "--print0"], cwd=root, environment=environment)
    _require_success(status, "sl status case-insensitive gitdir core.excludesFile")
    _, ignored_paths = _sapling_status_paths(status.stdout)
    ignored = sorted(ignored_paths & set(query_files))
    expected = fixture["expected_conditional_gitdir_i_ignored"][f"sapling.{mode}-mode"]
    return {
        "query_files": query_files,
        "ignored": ignored,
        "included": sorted(set(query_files) - set(ignored)),
        "candidate_matches": ignored == expected,
        "status_stdout": status.stdout.replace(str(root), "<workspace>"),
    }


def _capture_conditional_worktree_sapling(
    executable: str,
    mode: str,
    root: Path,
    home: Path,
    environment: Mapping[str, str],
    fixture: Mapping[str, Any],
    *,
    case_insensitive: bool = False,
) -> dict[str, Any]:
    """Capture Sapling's native worktree-conditional ignore behavior."""
    query_files, git_config_matches = _write_conditional_worktree_probe(
        root, home, environment, fixture, case_insensitive=case_insensitive
    )
    condition = "worktree/i" if case_insensitive else "worktree"
    native_environment = _isolated_worktree_environment(home, environment)
    status = _run(
        [executable, "status", "-iu", "--print0"], cwd=root, environment=native_environment
    )
    _require_success(status, f"sl status {condition} conditional core.excludesFile")
    _, ignored_paths = _sapling_status_paths(status.stdout)
    ignored = sorted(ignored_paths & set(query_files))
    expected_key = (
        "expected_conditional_worktree_i_ignored_when_supported"
        if case_insensitive
        else "expected_conditional_worktree_ignored_when_supported"
    )
    expected = fixture[expected_key][f"sapling.{mode}-mode"] if git_config_matches else []
    return {
        "query_files": query_files,
        "ignored": ignored,
        "included": sorted(set(query_files) - set(ignored)),
        "git_config_matches": git_config_matches,
        "native_matches_git_config": bool(ignored) == git_config_matches,
        "candidate_matches": ignored == expected,
        "status_stdout": status.stdout.replace(str(root), "<workspace>"),
    }


def _capture_conditional_worktree_i_sapling(
    executable: str,
    mode: str,
    root: Path,
    home: Path,
    environment: Mapping[str, str],
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture Sapling's case-insensitive worktree-conditional ignore behavior."""
    return _capture_conditional_worktree_sapling(
        executable, mode, root, home, environment, fixture, case_insensitive=True
    )


def _capture_conditional_global_jj(
    executable: str,
    mode: str,
    root: Path,
    home: Path,
    environment: Mapping[str, str],
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture Jujutsu's Git-dir conditional global ignore behavior."""
    query_files = _write_conditional_global_probe(root, home, fixture)
    status = _run([executable, "status", "--no-pager"], cwd=root, environment=environment)
    _require_success(status, "jj status conditional core.excludesFile")
    listed = _run([executable, "file", "list"], cwd=root, environment=environment)
    _require_success(listed, "jj file list conditional core.excludesFile")
    included_paths = _jujutsu_paths(listed.stdout)
    ignored = sorted(set(query_files) - included_paths)
    expected = fixture["expected_conditional_global_ignored"][f"jj.{mode}"]
    return {
        "query_files": query_files,
        "ignored": ignored,
        "included": sorted(set(query_files) & included_paths),
        "candidate_matches": ignored == expected,
        "status_stdout": status.stdout.replace(str(root), "<workspace>"),
        "file_list_stdout": listed.stdout.replace(str(root), "<workspace>"),
    }


def _capture_conditional_gitdir_i_jj(
    executable: str,
    mode: str,
    root: Path,
    home: Path,
    environment: Mapping[str, str],
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture Jujutsu's case-insensitive Git-dir conditional ignore behavior."""
    query_files = _write_conditional_gitdir_i_probe(root, home, fixture)
    status = _run([executable, "status", "--no-pager"], cwd=root, environment=environment)
    _require_success(status, "jj status case-insensitive gitdir core.excludesFile")
    listed = _run([executable, "file", "list"], cwd=root, environment=environment)
    _require_success(listed, "jj file list case-insensitive gitdir core.excludesFile")
    included_paths = _jujutsu_paths(listed.stdout)
    ignored = sorted(set(query_files) - included_paths)
    expected = fixture["expected_conditional_gitdir_i_ignored"][f"jj.{mode}"]
    return {
        "query_files": query_files,
        "ignored": ignored,
        "included": sorted(set(query_files) & included_paths),
        "candidate_matches": ignored == expected,
        "status_stdout": status.stdout.replace(str(root), "<workspace>"),
        "file_list_stdout": listed.stdout.replace(str(root), "<workspace>"),
    }


def _capture_conditional_worktree_jj(
    executable: str,
    mode: str,
    root: Path,
    home: Path,
    environment: Mapping[str, str],
    fixture: Mapping[str, Any],
    *,
    case_insensitive: bool = False,
) -> dict[str, Any]:
    """Capture Jujutsu's native worktree-conditional ignore behavior."""
    query_files, git_config_matches = _write_conditional_worktree_probe(
        root, home, environment, fixture, case_insensitive=case_insensitive
    )
    condition = "worktree/i" if case_insensitive else "worktree"
    native_environment = _isolated_worktree_environment(home, environment)
    status = _run([executable, "status", "--no-pager"], cwd=root, environment=native_environment)
    _require_success(status, f"jj status {condition} conditional core.excludesFile")
    listed = _run([executable, "file", "list"], cwd=root, environment=native_environment)
    _require_success(listed, f"jj file list {condition} conditional core.excludesFile")
    included_paths = _jujutsu_paths(listed.stdout)
    ignored = sorted(set(query_files) - included_paths)
    expected_key = (
        "expected_conditional_worktree_i_ignored_when_supported"
        if case_insensitive
        else "expected_conditional_worktree_ignored_when_supported"
    )
    expected = fixture[expected_key][f"jj.{mode}"] if git_config_matches else []
    return {
        "query_files": query_files,
        "ignored": ignored,
        "included": sorted(set(query_files) & included_paths),
        "git_config_matches": git_config_matches,
        "native_matches_git_config": bool(ignored) == git_config_matches,
        "candidate_matches": ignored == expected,
        "status_stdout": status.stdout.replace(str(root), "<workspace>"),
        "file_list_stdout": listed.stdout.replace(str(root), "<workspace>"),
    }


def _capture_conditional_worktree_i_jj(
    executable: str,
    mode: str,
    root: Path,
    home: Path,
    environment: Mapping[str, str],
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture Jujutsu's case-insensitive worktree-conditional ignore behavior."""
    return _capture_conditional_worktree_jj(
        executable, mode, root, home, environment, fixture, case_insensitive=True
    )


def _capture_conditional_onbranch_sapling(
    executable: str,
    mode: str,
    root: Path,
    home: Path,
    environment: Mapping[str, str],
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture Sapling's on-branch conditional global ignore behavior."""
    query_files = _write_conditional_onbranch_probe(root, home, fixture)
    status = _run([executable, "status", "-iu", "--print0"], cwd=root, environment=environment)
    _require_success(status, "sl status conditional onbranch core.excludesFile")
    _, ignored_paths = _sapling_status_paths(status.stdout)
    ignored = sorted(ignored_paths & set(query_files))
    expected = fixture["expected_conditional_branch_ignored"][f"sapling.{mode}-mode"]
    return {
        "query_files": query_files,
        "ignored": ignored,
        "included": sorted(set(query_files) - set(ignored)),
        "candidate_matches": ignored == expected,
        "status_stdout": status.stdout.replace(str(root), "<workspace>"),
    }


def _capture_conditional_onbranch_jj(
    executable: str,
    mode: str,
    root: Path,
    home: Path,
    environment: Mapping[str, str],
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture Jujutsu's on-branch conditional global ignore behavior."""
    query_files = _write_conditional_onbranch_probe(root, home, fixture)
    status = _run([executable, "status", "--no-pager"], cwd=root, environment=environment)
    _require_success(status, "jj status conditional onbranch core.excludesFile")
    listed = _run([executable, "file", "list"], cwd=root, environment=environment)
    _require_success(listed, "jj file list conditional onbranch core.excludesFile")
    included_paths = _jujutsu_paths(listed.stdout)
    ignored = sorted(set(query_files) - included_paths)
    expected = fixture["expected_conditional_branch_ignored"][f"jj.{mode}"]
    return {
        "query_files": query_files,
        "ignored": ignored,
        "included": sorted(set(query_files) & included_paths),
        "candidate_matches": ignored == expected,
        "status_stdout": status.stdout.replace(str(root), "<workspace>"),
        "file_list_stdout": listed.stdout.replace(str(root), "<workspace>"),
    }


def _capture_conditional_remote_sapling(
    executable: str,
    mode: str,
    root: Path,
    home: Path,
    environment: Mapping[str, str],
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture Sapling's remote-URL conditional global ignore behavior."""
    query_files = _write_conditional_remote_probe(root, home, fixture)
    status = _run([executable, "status", "-iu", "--print0"], cwd=root, environment=environment)
    _require_success(status, "sl status conditional remote URL core.excludesFile")
    _, ignored_paths = _sapling_status_paths(status.stdout)
    ignored = sorted(ignored_paths & set(query_files))
    expected = fixture["expected_conditional_remote_ignored"][f"sapling.{mode}-mode"]
    return {
        "query_files": query_files,
        "ignored": ignored,
        "included": sorted(set(query_files) - set(ignored)),
        "candidate_matches": ignored == expected,
        "status_stdout": status.stdout.replace(str(root), "<workspace>"),
    }


def _capture_conditional_remote_jj(
    executable: str,
    mode: str,
    root: Path,
    home: Path,
    environment: Mapping[str, str],
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture Jujutsu's remote-URL conditional global ignore behavior."""
    query_files = _write_conditional_remote_probe(root, home, fixture)
    status = _run([executable, "status", "--no-pager"], cwd=root, environment=environment)
    _require_success(status, "jj status conditional remote URL core.excludesFile")
    listed = _run([executable, "file", "list"], cwd=root, environment=environment)
    _require_success(listed, "jj file list conditional remote URL core.excludesFile")
    included_paths = _jujutsu_paths(listed.stdout)
    ignored = sorted(set(query_files) - included_paths)
    expected = fixture["expected_conditional_remote_ignored"][f"jj.{mode}"]
    return {
        "query_files": query_files,
        "ignored": ignored,
        "included": sorted(set(query_files) & included_paths),
        "candidate_matches": ignored == expected,
        "status_stdout": status.stdout.replace(str(root), "<workspace>"),
        "file_list_stdout": listed.stdout.replace(str(root), "<workspace>"),
    }


def _capture_configured_repository_sapling(
    executable: str,
    mode: str,
    root: Path,
    home: Path,
    environment: Mapping[str, str],
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture Sapling's repository-local ``core.excludesFile`` behavior."""
    query_files = _write_configured_repository_probe(root, home, environment, fixture)
    status = _run([executable, "status", "-iu", "--print0"], cwd=root, environment=environment)
    _require_success(status, "sl status repository core.excludesFile")
    _, ignored_paths = _sapling_status_paths(status.stdout)
    ignored = sorted(ignored_paths & set(query_files))
    expected = fixture["expected_configured_repository_ignored"][f"sapling.{mode}-mode"]
    return {
        "query_files": query_files,
        "ignored": ignored,
        "included": sorted(set(query_files) - set(ignored)),
        "candidate_matches": ignored == expected,
        "status_stdout": status.stdout.replace(str(root), "<workspace>"),
    }


def _capture_configured_repository_jj(
    executable: str,
    mode: str,
    root: Path,
    home: Path,
    environment: Mapping[str, str],
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture Jujutsu's repository-local ``core.excludesFile`` behavior."""
    query_files = _write_configured_repository_probe(root, home, environment, fixture)
    status = _run([executable, "status", "--no-pager"], cwd=root, environment=environment)
    _require_success(status, "jj status repository core.excludesFile")
    listed = _run([executable, "file", "list"], cwd=root, environment=environment)
    _require_success(listed, "jj file list repository core.excludesFile")
    included_paths = _jujutsu_paths(listed.stdout)
    ignored = sorted(set(query_files) - included_paths)
    expected = fixture["expected_configured_repository_ignored"][f"jj.{mode}"]
    return {
        "query_files": query_files,
        "ignored": ignored,
        "included": sorted(set(query_files) & included_paths),
        "candidate_matches": ignored == expected,
        "status_stdout": status.stdout.replace(str(root), "<workspace>"),
        "file_list_stdout": listed.stdout.replace(str(root), "<workspace>"),
    }


def _write_pattern_probes(root: Path, fixture: Mapping[str, Any]) -> None:
    """Add a path matrix for negation, directory barriers, anchoring, and ``**``."""
    _write_files(root, fixture["pattern_probe_files"])
    (root / ".gitignore").write_text(fixture["pattern_rules"], encoding="utf-8")


def _jujutsu_paths(output: str) -> set[str]:
    """Normalize Jujutsu's platform-specific path separators for fixture comparison."""
    return {line.strip().replace("\\", "/") for line in output.splitlines() if line.strip()}


def _expand_ignored_paths(ignored: set[str], query_files: set[str]) -> set[str]:
    """Expand native ignored-directory summaries to the fixture's queried files."""
    normalized = {path.rstrip("/") for path in ignored}
    return {
        path
        for path in query_files
        if path in normalized or any(path.startswith(prefix + "/") for prefix in normalized)
    }


def _sapling_status_paths(output: str) -> tuple[set[str], set[str]]:
    included: set[str] = set()
    ignored: set[str] = set()
    for line in output.split("\0"):
        if len(line) < 3 or line[1] != " ":
            continue
        path = line[2:].removeprefix("./")
        if line[0] == "I":
            ignored.add(path)
        elif line[0] in ("?", "A", "M", "R"):
            included.add(path)
    return included, ignored


def _write_files(root: Path, files: Mapping[str, str]) -> None:
    for relative, contents in files.items():
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as error:
            raise ValueError(f"fixture path escapes temporary workspace: {relative}") from error
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as stream:
            stream.write(contents)


def _version(executable: str) -> str:
    with tempfile.TemporaryDirectory(prefix="gitignore-walk-compat-version-") as temporary:
        result = subprocess.run(
            [executable, "--version"],
            cwd=temporary,
            capture_output=True,
            text=True,
            timeout=30,
        )
    if result.returncode != 0:
        raise RuntimeError(f"unable to get version for {executable}: {result.stderr.strip()}")
    return result.stdout.strip()


def _require_success(result: subprocess.CompletedProcess[str], operation: str) -> None:
    if result.returncode != 0:
        raise RuntimeError(f"{operation} failed: {result.stderr.strip() or result.stdout.strip()}")


def capture(sapling: str | None, jj: str) -> dict[str, Any]:
    fixture = json.loads(Path(__file__).with_name("cases.json").read_text(encoding="utf-8"))
    client_versions = {"git": _version("git")}
    captures = []
    if sapling is not None:
        client_versions["sapling"] = _version(sapling)
        captures.extend(_capture_sapling(sapling, mode, fixture) for mode in ("git", "sl"))
    client_versions["jujutsu"] = _version(jj)
    captures.extend(_capture_jj(jj, mode, fixture) for mode in ("colocated", "noncolocated"))
    expected_included = sorted(fixture["expected_included"])
    expected_ignored = sorted(fixture["expected_ignored"])
    for result in captures:
        result["candidate_matches"] = (
            result["included"] == expected_included and result["ignored"] == expected_ignored
        )
        result["source_discovery"]["candidate_matches"] = (
            result["source_discovery"]["ignored"]
            == fixture["expected_source_ignored"][result["id"]]
        )
        result["pattern_discovery"]["candidate_matches"] = (
            result["pattern_discovery"]["ignored"] == fixture["expected_pattern_ignored"]
        )
    return {
        "schema_version": 1,
        "status": "captured",
        "platform": platform.platform(),
        "clients": client_versions,
        "cases": captures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sl", default="sl", help="Sapling executable")
    parser.add_argument("--jj", default="jj", help="Jujutsu executable")
    parser.add_argument(
        "--jj-only",
        action="store_true",
        help="capture only Jujutsu when the Sapling client cannot run on this platform",
    )
    parser.add_argument("--output", type=Path, required=True, help="capture JSON destination")
    arguments = parser.parse_args()
    result = capture(None if arguments.jj_only else arguments.sl, arguments.jj)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    matched = sum(
        case["candidate_matches"]
        and case["source_discovery"]["candidate_matches"]
        and case["pattern_discovery"]["candidate_matches"]
        and case["configured_global"]["candidate_matches"]
        and case["configured_system"]["candidate_matches"]
        and case["conditional_global"]["candidate_matches"]
        and case["conditional_gitdir_i"]["candidate_matches"]
        and case["conditional_worktree"]["candidate_matches"]
        and case["conditional_worktree_i"]["candidate_matches"]
        and case["conditional_onbranch"]["candidate_matches"]
        and case["conditional_remote_url"]["candidate_matches"]
        and case["configured_repository"]["candidate_matches"]
        for case in result["cases"]
    )
    vcs_names = "Sapling/Jujutsu" if "sapling" in result["clients"] else "Jujutsu"
    print(f"Captured {len(result['cases'])} {vcs_names} cases")
    print(f"Ignore, source, and path-pattern candidates matching: {matched}/{len(result['cases'])}")
    print(f"Capture: {arguments.output}")
    return 0 if matched == len(result["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
