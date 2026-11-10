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


def _git_config_path(path: Path) -> str:
    """Serialize an absolute path using Git config's portable slash form."""
    return path.as_posix()


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
        conditional_gitdir_override = _capture_conditional_gitdir_override(
            executable, "sapling", mode, root, home, environment, fixture
        )
        environment_global = _capture_environment_global_sapling(executable, mode, fixture)
        symlinked_gitignore = _capture_symlinked_gitignore_sapling(executable, mode, fixture)
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
            "conditional_gitdir_override": conditional_gitdir_override,
            "environment_global": environment_global,
            "symlinked_gitignore": symlinked_gitignore,
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
        conditional_gitdir_override = _capture_conditional_gitdir_override(
            executable, "jujutsu", mode, root, home, environment, fixture
        )
        environment_global = _capture_environment_global_jj(executable, mode, fixture)
        symlinked_gitignore = _capture_symlinked_gitignore_jj(executable, mode, fixture)
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
            "conditional_gitdir_override": conditional_gitdir_override,
            "environment_global": environment_global,
            "symlinked_gitignore": symlinked_gitignore,
            "configured_repository": configured_repository,
        }


def _symlink_result(
    root: Path, home: Path, fixture: Mapping[str, Any], mode_id: str
) -> dict[str, Any]:
    """Create a nested symlinked ignore file, recording unsupported links as explicit skips."""
    ignore_source = home / "external.gitignore"
    ignore_source.write_text(fixture["symlinked_gitignore_source"], encoding="utf-8")
    nested = root / "nested"
    nested.mkdir()
    link = nested / ".gitignore"
    try:
        link.symlink_to(ignore_source)
    except OSError as error:
        return {
            "id": mode_id,
            "native_status": "skipped",
            "reason": f"unable to create symlink: {error}",
            "source": "nested/.gitignore",
            "source_is_symlink": False,
            "query_files": fixture["symlinked_gitignore_query_files"],
            "ignored": [],
            "candidate_matches": None,
        }
    for relative, content in fixture["symlinked_gitignore_probe_files"].items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return {
        "id": mode_id,
        "native_status": "captured",
        "source": "nested/.gitignore",
        "source_is_symlink": link.is_symlink(),
        "source_target_outside_workspace": not ignore_source.is_relative_to(root),
        "query_files": fixture["symlinked_gitignore_query_files"],
        "ignored": [],
        "candidate_matches": None,
    }


def _symlink_probe_environment(home: Path, *, sapling: bool) -> dict[str, str]:
    """Isolate probe settings from ambient Git and Sapling workspace overrides."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_CONFIG_")
        and key not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"}
    }
    environment.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "PAGER": "cat",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
    )
    if sapling:
        environment.update(
            {
                "SL_USER": "Oracle <oracle@example.invalid>",
                "HGPLAIN": "1",
            }
        )
    return environment


def _capture_symlinked_gitignore_sapling(
    executable: str, mode: str, fixture: Mapping[str, Any]
) -> dict[str, Any]:
    """Capture Sapling's handling of a nested symlinked `.gitignore`."""
    mode_id = f"sapling.{mode}-mode"
    with tempfile.TemporaryDirectory(prefix=f"gitignore-walk-symlink-{mode_id}-") as temporary:
        base = Path(temporary)
        home = base / "home"
        home.mkdir()
        root = base / "workspace"
        root.mkdir()
        environment = _symlink_probe_environment(home, sapling=True)
        if mode == "git":
            _require_success(
                _run(["git", "init", "-q", str(root)], cwd=root, environment=environment),
                "git init symlink probe",
            )
            _set_oracle_branch(root, environment)
            _set_oracle_remote(root, environment)
        else:
            _require_success(
                _run([executable, "init", str(root)], cwd=root, environment=environment),
                "sl init symlink probe",
            )
        result = _symlink_result(root, home, fixture, mode_id)
        if result["native_status"] == "skipped":
            return result
        native = _run([executable, "status", "-iu", "--print0"], cwd=root, environment=environment)
        _require_success(native, "sl status symlink probe")
        _, ignored = _sapling_status_paths(native.stdout)
        query_files = set(fixture["symlinked_gitignore_query_files"])
        result["ignored"] = sorted(ignored & query_files)
        expected = fixture["expected_symlinked_gitignore_ignored"][mode_id]
        result["candidate_matches"] = result["ignored"] == expected
        result["status_exit_code"] = native.returncode
        result["status_stdout"] = native.stdout.replace(str(root), "<workspace>")
        result["status_stderr"] = native.stderr.replace(str(root), "<workspace>")
        return result


def _capture_symlinked_gitignore_jj(
    executable: str,
    mode: str,
    fixture: Mapping[str, Any],
    *,
    expected_ignored: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Capture Jujutsu's handling of a nested symlinked `.gitignore`."""
    mode_id = f"jj.{mode}"
    with tempfile.TemporaryDirectory(prefix=f"gitignore-walk-symlink-{mode_id}-") as temporary:
        base = Path(temporary)
        home = base / "home"
        config_dir = home / ".config" / "jj"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text(
            '[user]\nname = "Oracle"\nemail = "oracle@example.invalid"\n',
            encoding="utf-8",
        )
        root = base / "workspace"
        root.mkdir()
        environment = _symlink_probe_environment(home, sapling=False)
        command = [executable, "git", "init"]
        if mode == "noncolocated":
            command.append("--no-colocate")
        command.append(str(root))
        _require_success(_run(command, cwd=root, environment=environment), "jj git init")
        _set_oracle_branch(root, environment)
        _set_oracle_remote_jj(executable, root, environment)
        result = _symlink_result(root, home, fixture, mode_id)
        if result["native_status"] == "skipped":
            return result
        status = _run([executable, "status", "--no-pager"], cwd=root, environment=environment)
        _require_success(status, "jj status symlink probe")
        listed = _run([executable, "file", "list"], cwd=root, environment=environment)
        _require_success(listed, "jj file list symlink probe")
        files = _jujutsu_paths(listed.stdout)
        query_files = set(fixture["symlinked_gitignore_query_files"])
        result["ignored"] = sorted(query_files - files)
        expected = (
            fixture["expected_symlinked_gitignore_ignored"][mode_id]
            if expected_ignored is None
            else expected_ignored
        )
        result["candidate_matches"] = result["ignored"] == expected
        result["status_exit_code"] = status.returncode
        result["status_stdout"] = status.stdout.replace(str(root), "<workspace>")
        result["status_stderr"] = status.stderr.replace(str(root), "<workspace>")
        result["file_list_stdout"] = listed.stdout.replace(str(root), "<workspace>")
        return result


def _write_environment_global_probe(
    root: Path, home: Path, fixture: Mapping[str, Any]
) -> tuple[list[str], dict[str, str]]:
    """Select an alternate global Git config path through the documented environment variable."""
    (home / ".gitconfig").unlink(missing_ok=True)
    ignore_file = home / "environment-global-ignore"
    ignore_file.write_text(fixture["environment_global_ignore"], encoding="utf-8")
    alternate_config = home / "alternate-gitconfig"
    alternate_config.write_text(
        f"[core]\n\texcludesFile = {_git_config_path(ignore_file)}\n", encoding="utf-8"
    )
    probe_environment = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "PAGER": "cat",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(alternate_config),
        "HGPLAIN": "1",
        "SL_USER": "Oracle <oracle@example.invalid>",
    }
    files: Mapping[str, str] = fixture["environment_global_probe_files"]
    _write_files(root, files)
    return sorted(files), probe_environment


def _capture_environment_global_sapling(
    executable: str,
    mode: str,
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture Sapling behavior for a non-default global Git config path."""
    with tempfile.TemporaryDirectory(prefix=f"gitignore-walk-sapling-global-{mode}-") as temporary:
        base = Path(temporary)
        home = base / "home"
        home.mkdir()
        root = base / "workspace"
        root.mkdir()
        query_files, probe_environment = _write_environment_global_probe(root, home, fixture)
        if mode == "git":
            _require_success(
                _run(["git", "init", "-q", str(root)], cwd=root, environment=probe_environment),
                "git init GIT_CONFIG_GLOBAL",
            )
            _set_oracle_branch(root, probe_environment)
            _set_oracle_remote(root, probe_environment)
        else:
            _require_success(
                _run([executable, "init", str(root)], cwd=root, environment=probe_environment),
                "sl init GIT_CONFIG_GLOBAL",
            )
        status = _run(
            [executable, "status", "-iu", "--print0"], cwd=root, environment=probe_environment
        )
        _require_success(status, "sl status GIT_CONFIG_GLOBAL")
        _, ignored_paths = _sapling_status_paths(status.stdout)
        ignored = sorted(ignored_paths & set(query_files))
        expected = fixture["expected_environment_global_ignored"][f"sapling.{mode}-mode"]
        return {
            "config_environment_variable": "GIT_CONFIG_GLOBAL",
            "query_files": query_files,
            "ignored": ignored,
            "included": sorted(set(query_files) - set(ignored)),
            "candidate_matches": ignored == expected,
            "status_stdout": status.stdout.replace(str(root), "<workspace>"),
        }


def _capture_environment_global_jj(
    executable: str,
    mode: str,
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture Jujutsu behavior for a non-default global Git config path."""
    with tempfile.TemporaryDirectory(prefix=f"gitignore-walk-jj-global-{mode}-") as temporary:
        base = Path(temporary)
        home = base / "home"
        home.mkdir()
        config_dir = home / ".config" / "jj"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text(
            '[user]\nname = "Oracle"\nemail = "oracle@example.invalid"\n', encoding="utf-8"
        )
        root = base / "workspace"
        root.mkdir()
        query_files, probe_environment = _write_environment_global_probe(root, home, fixture)
        command = [executable, "git", "init"]
        if mode == "noncolocated":
            command.append("--no-colocate")
        command.append(str(root))
        _require_success(
            _run(command, cwd=root, environment=probe_environment), "jj git init GIT_CONFIG_GLOBAL"
        )
        _set_oracle_branch(root, probe_environment)
        _set_oracle_remote_jj(executable, root, probe_environment)
        status = _run([executable, "status", "--no-pager"], cwd=root, environment=probe_environment)
        _require_success(status, "jj status GIT_CONFIG_GLOBAL")
        listed = _run([executable, "file", "list"], cwd=root, environment=probe_environment)
        _require_success(listed, "jj file list GIT_CONFIG_GLOBAL")
        included_paths = _jujutsu_paths(listed.stdout)
        ignored = sorted(set(query_files) - included_paths)
        expected = fixture["expected_environment_global_ignored"][f"jj.{mode}"]
        return {
            "config_environment_variable": "GIT_CONFIG_GLOBAL",
            "query_files": query_files,
            "ignored": ignored,
            "included": sorted(set(query_files) & included_paths),
            "candidate_matches": ignored == expected,
            "status_stdout": status.stdout.replace(str(root), "<workspace>"),
            "file_list_stdout": listed.stdout.replace(str(root), "<workspace>"),
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
        f"[core]\n\texcludesFile = {_git_config_path(system_ignore)}\n", encoding="utf-8"
    )
    (home / "included-git-config").write_text(
        f"[core]\n\texcludesFile = {_git_config_path(custom_ignore)}\n", encoding="utf-8"
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
    included_config.write_text(
        f"[core]\n\texcludesFile = {_git_config_path(custom_ignore)}\n", encoding="utf-8"
    )
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
    included_config.write_text(
        f"[core]\n\texcludesFile = {_git_config_path(custom_ignore)}\n", encoding="utf-8"
    )
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
    included_config.write_text(
        f"[core]\n\texcludesFile = {_git_config_path(custom_ignore)}\n", encoding="utf-8"
    )
    (home / ".gitconfig").write_text(
        '[includeIf "gitdir/i:**/WORKSPACE/.GIT"]\n\tpath = case-insensitive-gitdir-config\n',
        encoding="utf-8",
    )
    files: Mapping[str, str] = fixture["conditional_gitdir_i_probe_files"]
    _write_files(root, files)
    return sorted(files)


def _capture_conditional_gitdir_override(
    executable: str,
    vcs: str,
    mode: str,
    root: Path,
    home: Path,
    environment: Mapping[str, str],
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare native ignores with a Git-dir include selected by caller-provided context."""
    external_git_dir = home / "external.git"
    isolated_environment = _isolated_worktree_environment(home, environment)
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"):
        isolated_environment.pop(name, None)
    _require_success(
        _run(
            ["git", "init", "--bare", "-q", str(external_git_dir)],
            cwd=root,
            environment=isolated_environment,
        ),
        "initialize external Git-dir context",
    )
    custom_ignore = home / "gitdir-override-ignore"
    custom_ignore.write_text(fixture["conditional_gitdir_override_ignore"], encoding="utf-8")
    included_config = home / "gitdir-override-config"
    included_config.write_text(
        f"[core]\n\texcludesFile = {_git_config_path(custom_ignore)}\n", encoding="utf-8"
    )
    (home / ".gitconfig").write_text(
        '[includeIf "gitdir:**/external.git"]\n\tpath = gitdir-override-config\n',
        encoding="utf-8",
    )
    query_files = sorted(fixture["conditional_gitdir_override_probe_files"])
    _write_files(root, fixture["conditional_gitdir_override_probe_files"])
    probe_environment = dict(isolated_environment)
    probe_environment["GIT_DIR"] = str(external_git_dir)
    git_config = _run(
        ["git", "config", "--includes", "--path", "--get", "core.excludesFile"],
        cwd=root,
        environment=probe_environment,
    )
    if git_config.returncode not in (0, 1) or git_config.stderr:
        _require_success(git_config, "git config caller-provided GIT_DIR include")
    git_config_path = Path(git_config.stdout.strip()) if git_config.stdout.strip() else None
    git_config_matches = git_config_path == custom_ignore

    if vcs == "sapling":
        status = _run(
            [executable, "status", "-iu", "--print0"], cwd=root, environment=probe_environment
        )
        _require_success(status, "sl status caller-provided GIT_DIR include")
        _, ignored_paths = _sapling_status_paths(status.stdout)
        ignored = sorted(ignored_paths & set(query_files))
        output = {"status_stdout": status.stdout.replace(str(root), "<workspace>")}
    else:
        status = _run([executable, "status", "--no-pager"], cwd=root, environment=probe_environment)
        _require_success(status, "jj status caller-provided GIT_DIR include")
        listed = _run([executable, "file", "list"], cwd=root, environment=probe_environment)
        _require_success(listed, "jj file list caller-provided GIT_DIR include")
        included_paths = _jujutsu_paths(listed.stdout)
        ignored = sorted(set(query_files) - included_paths)
        output = {
            "status_stdout": status.stdout.replace(str(root), "<workspace>"),
            "file_list_stdout": listed.stdout.replace(str(root), "<workspace>"),
        }

    expected_key = f"{vcs}.{mode}-mode" if vcs == "sapling" else f"jj.{mode}"
    expected = fixture["expected_conditional_gitdir_override_ignored"][expected_key]
    return {
        "query_files": query_files,
        "git_config_path": (
            str(git_config_path).replace(str(home), "<home>")
            if git_config_path is not None
            else None
        ),
        "git_config_matches": git_config_matches,
        "ignored": ignored,
        "included": sorted(set(query_files) - set(ignored)),
        "native_matches_git_config": bool(ignored) == git_config_matches,
        "candidate_matches": ignored == expected,
        **output,
    }


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
    included_config.write_text(
        f"[core]\n\texcludesFile = {_git_config_path(custom_ignore)}\n", encoding="utf-8"
    )
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
    included_config.write_text(
        f"[core]\n\texcludesFile = {_git_config_path(custom_ignore)}\n", encoding="utf-8"
    )
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


def capture_jj_symlink_profile(jj: str, *, expected_follow_symlink: bool) -> dict[str, Any]:
    """Capture Jujutsu's native nested-ignore symlink behavior for one client release."""
    fixture = json.loads(Path(__file__).with_name("cases.json").read_text(encoding="utf-8"))
    expected_ignored = fixture["symlinked_gitignore_query_files"] if expected_follow_symlink else []
    return {
        "schema_version": 1,
        "status": "captured",
        "platform": platform.platform(),
        "clients": {"jujutsu": _version(jj)},
        "expected_follow_symlink": expected_follow_symlink,
        "cases": [
            _capture_symlinked_gitignore_jj(jj, mode, fixture, expected_ignored=expected_ignored)
            for mode in ("colocated", "noncolocated")
        ],
    }


def capture_linked_worktree_profile(sapling: str | None, jj: str) -> dict[str, Any]:
    """Compare Git, Sapling, and colocated Jujutsu excludes in a linked Git worktree."""
    fixture = json.loads(Path(__file__).with_name("cases.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="gitignore-walk-linked-worktree-") as temporary:
        base = Path(temporary)
        home = base / "home"
        home.mkdir()
        common_root = base / "main"
        common_root.mkdir()
        worktree = base / "linked"
        environment = _symlink_probe_environment(home, sapling=sapling is not None)
        jj_config = home / ".config" / "jj" / "config.toml"
        jj_config.parent.mkdir(parents=True)
        jj_config.write_text(
            '[user]\nname = "Oracle"\nemail = "oracle@example.invalid"\n',
            encoding="utf-8",
        )
        _require_success(
            _run(["git", "init", "-q", str(common_root)], cwd=common_root, environment=environment),
            "git init linked-worktree probe",
        )
        for key, value in (("user.name", "Oracle"), ("user.email", "oracle@example.invalid")):
            _require_success(
                _run(
                    ["git", "-C", str(common_root), "config", key, value],
                    cwd=common_root,
                    environment=environment,
                ),
                f"set linked-worktree Git {key}",
            )
        (common_root / "tracked.txt").write_text("seed\n", encoding="utf-8")
        _require_success(
            _run(
                ["git", "-C", str(common_root), "add", "tracked.txt"],
                cwd=common_root,
                environment=environment,
            ),
            "stage linked-worktree seed",
        )
        _require_success(
            _run(
                ["git", "-C", str(common_root), "commit", "-qm", "seed"],
                cwd=common_root,
                environment=environment,
            ),
            "commit linked-worktree seed",
        )
        _require_success(
            _run(
                ["git", "-C", str(common_root), "worktree", "add", "-qb", "linked", str(worktree)],
                cwd=common_root,
                environment=environment,
            ),
            "create linked Git worktree",
        )
        git_marker = worktree / ".git"
        marker_line = git_marker.read_text(encoding="utf-8").splitlines()[0]
        prefix = "gitdir: "
        if not marker_line.startswith(prefix):
            raise RuntimeError(f"unexpected linked-worktree .git marker: {marker_line!r}")
        worktree_git_dir = Path(marker_line[len(prefix) :])
        if not worktree_git_dir.is_absolute():
            worktree_git_dir = worktree / worktree_git_dir
        worktree_git_dir = worktree_git_dir.resolve()
        common_dir = common_root / ".git"
        common_exclude = common_dir / "info" / "exclude"
        worktree_exclude = worktree_git_dir / "info" / "exclude"
        common_exclude.parent.mkdir(parents=True, exist_ok=True)
        worktree_exclude.parent.mkdir(parents=True, exist_ok=True)
        common_exclude.write_text(fixture["linked_worktree_common_exclude"], encoding="utf-8")
        worktree_exclude.write_text(fixture["linked_worktree_specific_exclude"], encoding="utf-8")
        _require_success(
            _run([jj, "git", "init", "--colocate"], cwd=worktree, environment=environment),
            "jj init linked Git worktree",
        )
        _write_files(worktree, fixture["linked_worktree_probe_files"])
        query_files = sorted(fixture["linked_worktree_probe_files"])

        git_result = _run(
            ["git", "check-ignore", "--no-index", "-v", *query_files],
            cwd=worktree,
            environment=environment,
        )
        git_ignored = sorted(
            line.rsplit("\t", 1)[1] for line in git_result.stdout.splitlines() if "\t" in line
        )
        results = [
            {
                "id": "git",
                "native_status": "captured",
                "query_files": query_files,
                "ignored": git_ignored,
                "expected_ignored": fixture["expected_linked_worktree_ignored"]["git"],
                "candidate_matches": git_ignored
                == fixture["expected_linked_worktree_ignored"]["git"],
                "query_exit_code": git_result.returncode,
                "query_stdout": git_result.stdout.replace(str(base), "<temporary>"),
                "query_stderr": git_result.stderr.replace(str(base), "<temporary>"),
            }
        ]
        if sapling is not None:
            status = _run(
                [sapling, "status", "-iu", "--print0"], cwd=worktree, environment=environment
            )
            _require_success(status, "sl status linked Git worktree")
            _, ignored = _sapling_status_paths(status.stdout)
            sapling_ignored = sorted(ignored & set(query_files))
            expected = fixture["expected_linked_worktree_ignored"]["sapling.git-mode"]
            results.append(
                {
                    "id": "sapling.git-mode",
                    "native_status": "captured",
                    "query_files": query_files,
                    "ignored": sapling_ignored,
                    "expected_ignored": expected,
                    "candidate_matches": sapling_ignored == expected,
                    "status_exit_code": status.returncode,
                    "status_stdout": status.stdout.replace(str(worktree), "<worktree>"),
                    "status_stderr": status.stderr.replace(str(worktree), "<worktree>"),
                }
            )
        status = _run([jj, "status", "--no-pager"], cwd=worktree, environment=environment)
        _require_success(status, "jj status linked Git worktree")
        listed = _run([jj, "file", "list"], cwd=worktree, environment=environment)
        _require_success(listed, "jj file list linked Git worktree")
        jj_files = set(_jujutsu_paths(listed.stdout))
        jj_ignored = sorted(set(query_files) - jj_files)
        expected = fixture["expected_linked_worktree_ignored"]["jj.colocated"]
        results.append(
            {
                "id": "jj.colocated",
                "native_status": "captured",
                "query_files": query_files,
                "ignored": jj_ignored,
                "expected_ignored": expected,
                "candidate_matches": jj_ignored == expected,
                "status_exit_code": status.returncode,
                "status_stdout": status.stdout.replace(str(worktree), "<worktree>"),
                "status_stderr": status.stderr.replace(str(worktree), "<worktree>"),
                "file_list_stdout": listed.stdout.replace(str(worktree), "<worktree>"),
            }
        )
        return {
            "schema_version": 1,
            "status": "captured",
            "platform": platform.platform(),
            "clients": {
                "git": _version("git"),
                **({"sapling": _version(sapling)} if sapling is not None else {}),
                "jujutsu": _version(jj),
            },
            "workspace": "Git linked worktree",
            "common_exclude_scope": "main Git directory/info/exclude",
            "worktree_exclude_scope": "linked worktree Git directory/info/exclude",
            "cases": results,
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
    parser.add_argument(
        "--symlink-only",
        action="store_true",
        help="capture only Jujutsu's nested .gitignore symlink behavior",
    )
    parser.add_argument(
        "--linked-worktree-only",
        action="store_true",
        help="capture Git, Sapling, and colocated Jujutsu linked-worktree excludes",
    )
    parser.add_argument(
        "--expect-jj-follows-symlink",
        action="store_true",
        help="expect Jujutsu to follow the nested .gitignore symlink (pre-0.46.0 profile)",
    )
    parser.add_argument("--output", type=Path, required=True, help="capture JSON destination")
    arguments = parser.parse_args()
    if arguments.expect_jj_follows_symlink and not arguments.symlink_only:
        parser.error("--expect-jj-follows-symlink requires --symlink-only")
    if arguments.linked_worktree_only and arguments.symlink_only:
        parser.error("--linked-worktree-only and --symlink-only cannot be combined")
    if arguments.symlink_only:
        result = capture_jj_symlink_profile(
            arguments.jj,
            expected_follow_symlink=arguments.expect_jj_follows_symlink,
        )
    elif arguments.linked_worktree_only:
        result = capture_linked_worktree_profile(
            None if arguments.jj_only else arguments.sl,
            arguments.jj,
        )
    else:
        result = capture(None if arguments.jj_only else arguments.sl, arguments.jj)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if arguments.symlink_only:
        matched = sum(
            case["native_status"] == "captured" and case["candidate_matches"]
            for case in result["cases"]
        )
        skipped = sum(case["native_status"] == "skipped" for case in result["cases"])
        print(f"Captured Jujutsu symlink behavior: {matched}/{len(result['cases'])} cases match")
        if skipped:
            print(f"Symlink probes explicitly skipped: {skipped}/{len(result['cases'])}")
        print(f"Capture: {arguments.output}")
        return 0 if matched + skipped == len(result["cases"]) else 1
    if arguments.linked_worktree_only:
        matched = sum(case["candidate_matches"] for case in result["cases"])
        print(f"Captured linked-worktree source cases matching: {matched}/{len(result['cases'])}")
        print(f"Capture: {arguments.output}")
        return 0 if matched == len(result["cases"]) else 1
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
        and case["environment_global"]["candidate_matches"]
        and case["symlinked_gitignore"]["native_status"] == "captured"
        and case["symlinked_gitignore"]["candidate_matches"]
        for case in result["cases"]
    )
    skipped = sum(
        case["symlinked_gitignore"]["native_status"] == "skipped" for case in result["cases"]
    )
    vcs_names = "Sapling/Jujutsu" if "sapling" in result["clients"] else "Jujutsu"
    print(f"Captured {len(result['cases'])} {vcs_names} cases")
    print(f"All probe candidates matching: {matched}/{len(result['cases'])}")
    if skipped:
        print(f"Symlink probes explicitly skipped: {skipped}/{len(result['cases'])}")
    print(f"Capture: {arguments.output}")
    return 0 if matched + skipped == len(result["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
