"""Portable compatibility and isolated comparisons with Git's actual evaluator."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

import pytest

from gitignore_walk import (
    GitIgnoreDecision,
    GitIgnoreError,
    GitIgnorePolicy,
    GitIgnoreSpec,
    GitIgnoreWalker,
    GitStandardPolicy,
    IgnorePolicy,
    is_gitignored,
    matches_gitignore,
    parse_gitignore,
)
from gitignore_walk.environment import EnvVar


class RepositoryCase:
    @pytest.fixture(autouse=True)
    def setup_repository(self, tmp_path: Path) -> Iterator[None]:
        self.base = tmp_path.resolve()
        self.root = self.base / "repo"
        self.root.mkdir()
        self.home = self.base / "home"
        self.home.mkdir()
        self.environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(EnvVar.GIT_PREFIX_FILTER)
        }
        self.environment.update(
            {
                EnvVar.HOME: str(self.home),
                EnvVar.USERPROFILE: str(self.home),
                EnvVar.XDG_CONFIG_HOME: str(self.home / "xdg"),
                EnvVar.GIT_CONFIG_NOSYSTEM: "1",
                EnvVar.GIT_CONFIG_GLOBAL: str(self.home / "config"),
                EnvVar.GIT_AUTHOR_NAME: "Test",
                EnvVar.GIT_AUTHOR_EMAIL: "test@example.invalid",
                EnvVar.GIT_COMMITTER_NAME: "Test",
                EnvVar.GIT_COMMITTER_EMAIL: "test@example.invalid",
                EnvVar.GIT_TERMINAL_PROMPT: "0",
            }
        )
        self.environment_patch = patch.dict(os.environ, self.environment, clear=True)
        self.environment_patch.start()
        try:
            yield
        finally:
            self.environment_patch.stop()

    def write(self, relative: str, text: str = "content\n") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def git(self, *arguments: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            env=self.environment,
            capture_output=True,
            check=True,
        )

    def init(self) -> None:
        if not shutil.which("git"):
            pytest.skip("Git is required for oracle comparisons")
        self.git("init", "--quiet")

    def native(self, **kwargs: object) -> GitStandardPolicy:
        return GitStandardPolicy(self.root, environment=self.environment, **kwargs)

    def symlink(self, target: Path, name: str) -> Path:
        path = self.root / name
        try:
            path.symlink_to(target, target_is_directory=target.is_dir())
        except OSError as error:
            pytest.skip(f"symlinks unavailable: {error}")
        return path


class TestPolicyContract(RepositoryCase):
    @pytest.mark.parametrize("native", [False, True])
    def test_batch_and_lazy_contract(self, native: bool) -> None:
        if native:
            self.init()
        self.write(".gitignore", "*.tmp\n")
        policy: IgnorePolicy = self.native() if native else GitIgnorePolicy(self.root)
        assert isinstance(policy, IgnorePolicy)
        if native:
            assert not isinstance(policy, GitIgnorePolicy)
        targets = ["a.tmp", "keep.txt", "b.tmp"]
        decisions = policy.explain_many(targets)
        assert isinstance(decisions, list)
        assert [item.ignored for item in decisions] == [True, False, True]
        decisions.pop()
        flags = policy.is_ignored_many(targets)
        assert flags == [True, False, True]
        flags.append(False)
        consumed: list[str] = []

        def source() -> Iterator[str]:
            for target in targets:
                consumed.append(target)
                yield target

        lazy = policy.iter_explain(source(), batch_size=2)
        assert consumed == []
        assert next(lazy).ignored
        assert len(consumed) == (2 if native else 1)
        assert [item.ignored for item in lazy] == [False, True]
        assert list(policy.iter_ignored(iter(targets), batch_size=2)) == [True, False, True]
        assert policy.explain_many([]) == []
        assert policy.is_ignored_many([]) == []
        with pytest.raises(ValueError, match="batch_size"):
            list(policy.iter_explain([], batch_size=0))

    def test_portable_lazy_iteration_shares_snapshot(self) -> None:
        ignore = self.write(".gitignore", "*.tmp\n")
        policy = GitIgnorePolicy(self.root)
        lazy = policy.iter_ignored(["a.tmp", "b.tmp"])
        assert next(lazy)
        ignore.write_text("", encoding="utf-8")
        assert list(lazy) == [True]
        assert not policy.is_ignored("b.tmp")


class TestPortable(RepositoryCase):
    def test_parser_preserves_source_lines_and_escaped_literals(self) -> None:
        spec = parse_gitignore(
            ["# ignored comment", "", r"\#literal", r"\!literal", "space\\ ", "*.tmp"],
            source="test",
        )
        assert isinstance(spec, GitIgnoreSpec)
        assert [pattern.source_line for pattern in spec.patterns] == [3, 4, 5, 6]
        assert matches_gitignore(spec, "#literal", is_directory=False)
        assert matches_gitignore(spec, "!literal", is_directory=False)
        assert matches_gitignore(spec, "space ", is_directory=False)
        assert matches_gitignore(spec, "nested/drop.tmp", is_directory=False)
        assert not (matches_gitignore(spec, "space", is_directory=False))

    def test_parser_handles_slash_scope_double_star_and_directory_inheritance(self) -> None:
        spec = parse_gitignore(
            ["/root-only", "docs/draft.md", "**/generated/*.json", "cache/", "a/**/b.txt"],
            source="test",
        )
        assert matches_gitignore(spec, "root-only", is_directory=False)
        assert not (matches_gitignore(spec, "nested/root-only", is_directory=False))
        assert matches_gitignore(spec, "docs/draft.md", is_directory=False)
        assert not (matches_gitignore(spec, "nested/docs/draft.md", is_directory=False))
        assert matches_gitignore(spec, "one/generated/data.json", is_directory=False)
        assert matches_gitignore(spec, "cache/nested/file", is_directory=False)
        assert not (matches_gitignore(spec, "cache", is_directory=False))
        assert matches_gitignore(spec, "a/x/y/b.txt", is_directory=False)
        assert matches_gitignore(spec, "a/b.txt", is_directory=False)

    def test_public_matcher_normalizes_pathlike_edges(self) -> None:
        spec = parse_gitignore(["nested/drop.tmp"], source="test")
        assert matches_gitignore(spec, Path("nested/drop.tmp"), is_directory=False)
        assert matches_gitignore(spec, PureWindowsPath(r"nested\drop.tmp"), is_directory=False)
        for path in (Path("../drop.tmp"), Path("/drop.tmp"), PureWindowsPath(r"C:\drop.tmp")):
            with pytest.raises(ValueError):
                matches_gitignore(spec, path, is_directory=False)

    def test_character_class_negation_and_escaped_closing_bracket(self) -> None:
        caret_negated = parse_gitignore(["[^a].txt"], source="test")
        assert not matches_gitignore(caret_negated, "a.txt", is_directory=False)
        assert matches_gitignore(caret_negated, "b.txt", is_directory=False)

        escaped_close = parse_gitignore([r"[a\]b].txt"], source="test")
        assert all(
            matches_gitignore(escaped_close, name, is_directory=False)
            for name in ("a.txt", "].txt", "b.txt")
        )
        assert not matches_gitignore(escaped_close, "c.txt", is_directory=False)

    def test_recursive_trailing_double_star_matches_newlines(self) -> None:
        spec = parse_gitignore(["a/**"], source="test")
        assert matches_gitignore(spec, "a/line\nbreak", is_directory=False)

    def test_global_excludes_fall_back_to_home_config(self) -> None:
        os.environ.pop(EnvVar.XDG_CONFIG_HOME)
        global_excludes = self.home / ".config" / "git" / "ignore"
        global_excludes.parent.mkdir(parents=True)
        global_excludes.write_text("*.user-global\n", encoding="utf-8")

        policy = GitIgnorePolicy(self.root)
        decision = policy.explain("generated.user-global")
        assert decision.ignored
        assert decision.source == f"user-global excludes {global_excludes}"

    def test_default_global_excludes_and_repository_precedence(self) -> None:
        global_excludes = self.home / "xdg" / "git" / "ignore"
        global_excludes.parent.mkdir(parents=True)
        global_excludes.write_text("*.tmp\n*.global\n", encoding="utf-8")
        self.write(".gitignore", "!keep.tmp\n")

        policy = GitIgnorePolicy(self.root)
        assert policy.is_ignored("drop.tmp")
        drop_decision = policy.explain("drop.tmp")
        assert drop_decision.source is not None
        assert str(global_excludes) in drop_decision.source
        assert not (policy.is_ignored("keep.tmp"))
        assert policy.is_ignored("file.global")

    def test_global_info_and_repository_ignore_precedence(self) -> None:
        global_excludes = self.home / "xdg" / "git" / "ignore"
        global_excludes.parent.mkdir(parents=True)
        global_excludes.write_text(
            "*.tmp\n!info.tmp\n/nested/global-root.tmp\n",
            encoding="utf-8",
        )
        self.write(".git/info/exclude", "info.tmp\n!repo.tmp\n")
        self.write(".gitignore", "repo.tmp\n")
        nested_root = self.root / "nested"
        nested_root.mkdir()
        self.write("nested/.gitignore", "!nested.tmp\n")

        policy = GitIgnorePolicy(nested_root)
        info_decision = policy.explain("info.tmp")
        repo_decision = policy.explain("repo.tmp")
        nested_decision = policy.explain("nested.tmp")
        anchored_global_decision = policy.explain("global-root.tmp")

        assert info_decision.ignored
        assert info_decision.source is not None
        assert "info/exclude" in info_decision.source
        assert repo_decision.ignored
        assert repo_decision.source is not None
        assert "repository .gitignore" in repo_decision.source
        assert not nested_decision.ignored
        assert anchored_global_decision.ignored
        assert anchored_global_decision.source is not None
        assert "user-global excludes" in anchored_global_decision.source

    def test_upward_discovery_reads_repository_and_info_excludes(self) -> None:
        self.write(".gitignore", "*.tmp\n!repo-keep.tmp\n")
        self.write(".git/info/exclude", "*.cache\n!keep.cache\n")
        nested_root = self.root / "packages" / "project"
        nested_root.mkdir(parents=True)
        self.write("packages/project/.gitignore", "!nested-keep.tmp\n")

        policy = GitIgnorePolicy(nested_root)
        assert policy.is_ignored("drop.tmp")
        assert not (policy.is_ignored("repo-keep.tmp"))
        assert not (policy.is_ignored("nested-keep.tmp"))
        assert policy.is_ignored("drop.cache")
        assert not (policy.is_ignored("keep.cache"))
        cache_decision = policy.explain("drop.cache")
        assert cache_decision.source is not None
        assert "info/exclude" in cache_decision.source

    def test_upward_discovery_reads_worktree_gitfile_common_excludes(self) -> None:
        git_dir = self.base / "worktrees" / "checkout"
        common_dir = self.base / "shared-git-dir"
        git_dir.mkdir(parents=True)
        (git_dir / "commondir").write_text(str(common_dir), encoding="utf-8")
        info = common_dir / "info"
        info.mkdir(parents=True)
        (info / "exclude").write_text("*.worktree\n", encoding="utf-8")
        self.write(".git", f"gitdir: {git_dir}\n")
        nested_root = self.root / "src" / "package"
        nested_root.mkdir(parents=True)

        policy = GitIgnorePolicy(nested_root)
        assert policy.is_ignored("ignored.worktree")
        worktree_decision = policy.explain("ignored.worktree")
        assert worktree_decision.source is not None
        assert "info/exclude" in worktree_decision.source

    def test_point_batch_and_helpers(self) -> None:
        self.write(".gitignore", "# comment\n*.tmp\n!keep.tmp\n")
        drop = self.write("drop.tmp")
        keep = self.write("keep.tmp")
        policy = GitIgnorePolicy(self.root)
        assert is_gitignored(self.root, "drop.tmp")
        assert policy.is_ignored_many([drop, keep, "missing.txt"]) == [True, False, False]
        decision = policy.explain(drop)
        assert (decision.path, decision.pattern, decision.line) == (drop, "*.tmp", 2)
        assert decision.source is not None
        assert str(self.root / ".gitignore") in decision.source
        assert policy.explain(keep) == GitIgnoreDecision(path=keep, ignored=False)
        spec = parse_gitignore(["cache/"], source="test")
        assert matches_gitignore(spec, "cache", is_directory=True)
        assert not (matches_gitignore(spec, "cache", is_directory=False))

    def test_baseline_is_authoritative(self) -> None:
        self.write(".gitignore", "!drop.tmp\n")
        policy = GitIgnorePolicy(self.root, initial_excludes=["*.tmp"])
        assert policy.is_ignored("drop.tmp")
        assert policy.explain("drop.tmp").source == "initial Git-ignore exclusions"

    def test_parent_exclusion_cannot_be_undone(self) -> None:
        self.write(".gitignore", "build/\n!build/keep.md\n")
        self.write("build/.gitignore", "!keep.md\n")
        assert GitIgnorePolicy(self.root).is_ignored("build/keep.md")

    def test_nested_override_after_parent_unignored(self) -> None:
        self.write(".gitignore", "*.tmp\n")
        self.write("docs/.gitignore", "!keep.tmp\n")
        policy = GitIgnorePolicy(self.root)
        assert not (policy.is_ignored("docs/keep.tmp"))
        assert policy.is_ignored("docs/drop.tmp")

    def test_missing_descendant_under_ignored_parent(self) -> None:
        self.write(".gitignore", "build/\n")
        (self.root / "build").mkdir()
        decision = GitIgnorePolicy(self.root).explain("build/not-created/sub/file.txt")
        assert decision.ignored
        assert decision.pattern == "build/"

    def test_fresh_batch_reads_changed_policy(self) -> None:
        ignore = self.write(".gitignore", "*.tmp\n")
        policy = GitIgnorePolicy(self.root)
        assert policy.is_ignored_many(["file.tmp"]) == [True]
        ignore.write_text("!*.tmp\n", encoding="utf-8")
        assert policy.is_ignored_many(["file.tmp"]) == [False]

    def test_invalid_encoding_raises(self) -> None:
        self.write("docs/.gitignore").write_bytes(b"\xff\n*.tmp\n")
        with pytest.raises(GitIgnoreError):
            GitIgnorePolicy(self.root).is_ignored("docs/drop.tmp")

    def test_outside_root_rejected(self) -> None:
        with pytest.raises(ValueError):
            GitIgnorePolicy(self.root).is_ignored("../outside")
        with pytest.raises(ValueError):
            GitIgnorePolicy(self.root / "missing")

    def test_symlink_escape_rejected(self) -> None:
        outside = self.base / "outside"
        outside.mkdir()
        self.symlink(outside, "escape")
        with pytest.raises(ValueError):
            GitIgnorePolicy(self.root).is_ignored("escape/file")

    def test_walk_default_filter_and_ignored_descendants(self) -> None:
        self.write(".gitignore", "*.tmp\nbuild/\n")
        self.write("docs/keep.md")
        self.write("docs/drop.tmp")
        self.write("build/output")
        walker = GitIgnoreWalker(self.root)
        all_files = {
            p.relative_to(self.root).as_posix() for p in walker.iter_files(selection="all")
        }
        selected = {p.relative_to(self.root).as_posix() for p in walker.iter_files()}
        ignored = {
            p.relative_to(self.root).as_posix() for p in walker.iter_files(selection="ignored")
        }
        assert selected == {".gitignore", "docs/keep.md"}
        assert ignored == {"docs/drop.tmp", "build/output"}
        assert all_files == selected | ignored
        with pytest.raises(ValueError):
            list(walker.walk(selection="invalid"))  # type: ignore[arg-type]

    def test_topdown_directory_pruning(self) -> None:
        self.write("docs/keep.md")
        self.write("build/output")
        walker = GitIgnoreWalker(self.root)
        rows = walker.walk(selection="all")
        _, directories, _ = next(rows)
        directories.remove("build")
        assert [directory.name for directory, _, _ in rows] == ["docs"]

    @pytest.mark.parametrize("native", [False, True])
    @pytest.mark.parametrize("topdown", [False, True])
    def test_git_metadata_follows_policy_selection(self, native: bool, topdown: bool) -> None:
        if native:
            self.init()
        metadata = self.write(".git/walker-probe")
        nested_marker = self.write("nested/.git", "gitdir: elsewhere\n")
        normal = self.write("normal.txt")
        policy = self.native() if native else GitIgnorePolicy(self.root)
        walker = GitIgnoreWalker(self.root, policy=policy)
        assert policy.is_ignored(metadata)
        selected = set(walker.iter_files(topdown=topdown))
        assert normal in selected
        assert metadata not in selected and nested_marker not in selected
        ignored = set(walker.iter_files(selection="ignored", topdown=topdown))
        assert {metadata, nested_marker} <= ignored
        all_files = set(walker.iter_files(selection="all", topdown=topdown))
        assert {metadata, nested_marker, normal} <= all_files
        assert list(walker.iter_files(self.root / ".git")) == []
        assert metadata in set(walker.iter_files(self.root / ".git", selection="all"))

    @pytest.mark.parametrize("native", [False, True])
    def test_bottom_up_prunes_ignored_directories_before_scanning(self, native: bool) -> None:
        if native:
            self.init()
        self.write(".git/walker-probe")
        self.write("nested/.git/config")
        self.write("nested/file.txt")
        self.write(".gitignore", "build/\n")
        self.write("build/output")
        scanned: list[Path] = []
        scandir = os.scandir

        def record_scandir(path: object) -> object:
            scanned.append(Path(os.fsdecode(path)))  # type: ignore[arg-type]
            return scandir(path)  # type: ignore[call-overload]

        policy = self.native() if native else GitIgnorePolicy(self.root)
        walker = GitIgnoreWalker(self.root, policy=policy)
        with patch("os.scandir", side_effect=record_scandir):
            list(walker.iter_files(topdown=False))
        assert not any(".git" in path.parts for path in scanned)
        assert not any("build" in path.parts for path in scanned)

        scanned.clear()
        with patch("os.scandir", side_effect=record_scandir):
            list(walker.iter_files(topdown=False, selection="all"))
        assert any(".git" in path.parts for path in scanned)
        assert any("build" in path.parts for path in scanned)

    @pytest.mark.parametrize("native", [False, True])
    def test_empty_initial_excludes_allows_git_metadata(self, native: bool) -> None:
        if native:
            self.init()
        metadata = self.write(".git/walker-probe")
        policy = (
            self.native(initial_excludes=())
            if native
            else GitIgnorePolicy(self.root, initial_excludes=())
        )
        assert metadata in set(GitIgnoreWalker(self.root, policy=policy).iter_files())

    def test_discovered_symlinks_and_special_files_omitted(self) -> None:
        file = self.write("real.txt")
        self.symlink(file, "link.txt")
        if hasattr(os, "mkfifo"):
            os.mkfifo(self.root / "fifo")
        assert list(GitIgnoreWalker(self.root).iter_files()) == [file]

    def test_supplied_policy_root_must_match(self) -> None:
        child = self.root / "child"
        child.mkdir()
        with pytest.raises(ValueError):
            GitIgnoreWalker(child, policy=GitIgnorePolicy(self.root))

    def test_supplied_policy_rejects_walker_excludes(self) -> None:
        policy = GitIgnorePolicy(self.root)
        with pytest.raises(ValueError, match="initial_excludes"):
            GitIgnoreWalker(self.root, policy=policy, initial_excludes=())

    def test_bottom_up_prunes_ignored_rows(self) -> None:
        self.write(".gitignore", "build/\n")
        self.write("build/ignored")
        rows = list(GitIgnoreWalker(self.root).walk(topdown=False))
        assert all(directory != self.root / "build" for directory, _, _ in rows)

    def test_explicit_internal_symlink_top_legacy_behavior(self) -> None:
        file = self.write("docs/keep.md")
        link = self.symlink(file.parent, "docs-link")
        assert list(GitIgnoreWalker(self.root).iter_files(link)) == [file]

    def test_read_failure_not_silenced(self) -> None:
        self.write(".gitignore", "*.tmp\n")
        with (
            patch.object(Path, "read_text", side_effect=PermissionError("denied")),
            pytest.raises(GitIgnoreError),
        ):
            GitIgnorePolicy(self.root).is_ignored("drop.tmp")


class TestNative(RepositoryCase):
    @pytest.fixture(autouse=True)
    def setup_native_repository(self, setup_repository: None) -> None:
        self.init()

    def global_excludes(self, text: str, filename: str = "global ignore") -> Path:
        path = self.home / filename
        path.write_text(text, encoding="utf-8")
        self.git("config", "--global", "core.excludesFile", str(path))
        return path

    def test_global_and_repository_precedence_with_provenance(self) -> None:
        source = self.global_excludes("*.tmp\n")
        self.write(".gitignore", "!keep.tmp\n")
        policy = self.native()
        drop, keep, unmatched = policy.explain_many(["drop.tmp", "keep.tmp", "plain.txt"])
        assert drop.ignored
        assert (Path(drop.source or ""), drop.line, drop.pattern) == (source, 1, "*.tmp")
        assert not keep.ignored
        assert (keep.source, keep.line, keep.pattern) == (".gitignore", 1, "!keep.tmp")
        assert unmatched == GitIgnoreDecision(self.root / "plain.txt", False)
        assert not (GitIgnorePolicy(self.root).is_ignored("drop.tmp"))

    def test_info_exclude_and_root_override(self) -> None:
        self.write(".git/info/exclude", "*.cache\n")
        self.write(".gitignore", "!keep.cache\n")
        policy = self.native()
        assert policy.is_ignored_many(["drop.cache", "keep.cache"]) == [True, False]
        assert policy.explain("drop.cache").source == ".git/info/exclude"

    def test_quoted_config_value_spaces(self) -> None:
        path = self.home / "quoted ignore file"
        path.write_text("*.tmp\n", encoding="utf-8")
        (self.home / "config").write_text(
            f'[core]\n excludesFile = "{path.as_posix()}"\n', encoding="utf-8"
        )
        assert self.native().is_ignored("drop.tmp")

    def test_config_include(self) -> None:
        source = self.home / "patterns"
        source.write_text("*.tmp\n", encoding="utf-8")
        (self.home / "included").write_text(
            f'[core]\n excludesFile = "{source.as_posix()}"\n', encoding="utf-8"
        )
        (self.home / "config").write_text("[include]\n path = included\n", encoding="utf-8")
        assert self.native().is_ignored("drop.tmp")

    def test_conditional_include(self) -> None:
        source = self.home / "patterns"
        source.write_text("*.tmp\n", encoding="utf-8")
        (self.home / "included").write_text(
            f'[core]\n excludesFile = "{source.as_posix()}"\n', encoding="utf-8"
        )
        gitdir = (self.root / ".git").as_posix()
        (self.home / "config").write_text(
            f'[includeIf "gitdir:{gitdir}"]\n path = included\n', encoding="utf-8"
        )
        assert self.native().is_ignored("drop.tmp")

    def test_last_value_wins_and_unrelated_section_is_ignored(self) -> None:
        first = self.home / "first"
        second = self.home / "second"
        first.write_text("*.first\n", encoding="utf-8")
        second.write_text("*.second\n", encoding="utf-8")
        (self.home / "config").write_text(
            f'[core]\n excludesFile = "{first.as_posix()}"\n'
            f' excludesFile = "{second.as_posix()}"\n'
            f'[unrelated]\n excludesFile = "{first.as_posix()}"\n',
            encoding="utf-8",
        )
        assert self.native().is_ignored_many(["x.first", "x.second"]) == [False, True]

    def test_local_configuration_overrides_global(self) -> None:
        self.global_excludes("*.global\n")
        source = self.home / "local"
        source.write_text("*.local\n", encoding="utf-8")
        self.git("config", "--local", "core.excludesFile", str(source))
        assert self.native().is_ignored_many(["x.global", "x.local"]) == [False, True]

    def test_git_config_global_override(self) -> None:
        source = self.home / "patterns"
        source.write_text("*.tmp\n", encoding="utf-8")
        custom = self.home / "custom-config"
        custom.write_text(f'[core]\n excludesFile = "{source.as_posix()}"\n', encoding="utf-8")
        self.environment[EnvVar.GIT_CONFIG_GLOBAL] = str(custom)
        assert self.native().is_ignored("drop.tmp")

    def test_xdg_fallback(self) -> None:
        xdg = self.home / "xdg" / "git"
        xdg.mkdir(parents=True)
        (xdg / "ignore").write_text("*.tmp\n", encoding="utf-8")
        assert self.native().is_ignored("drop.tmp")

    def test_default_home_config_location(self) -> None:
        self.environment.pop(EnvVar.GIT_CONFIG_GLOBAL)
        source = self.home / "patterns"
        source.write_text("*.tmp\n", encoding="utf-8")
        (self.home / ".gitconfig").write_text(
            f'[core]\n excludesFile = "{source.as_posix()}"\n', encoding="utf-8"
        )
        assert self.native().is_ignored("drop.tmp")

    def test_missing_configured_excludes_does_not_fall_back(self) -> None:
        xdg = self.home / "xdg" / "git"
        xdg.mkdir(parents=True)
        (xdg / "ignore").write_text("*.tmp\n", encoding="utf-8")
        self.git("config", "--global", "core.excludesFile", str(self.home / "missing"))
        assert not (self.native().is_ignored("drop.tmp"))

    def test_tilde_excludes_file(self) -> None:
        (self.home / "patterns").write_text("*.tmp\n", encoding="utf-8")
        self.git("config", "--global", "core.excludesFile", "~/patterns")
        assert self.native().is_ignored("drop.tmp")

    def test_system_config_and_environment_count_override(self) -> None:
        source = self.home / "patterns"
        source.write_text("*.tmp\n", encoding="utf-8")
        system = self.home / "system-config"
        system.write_text(f'[core]\n excludesFile = "{source.as_posix()}"\n', encoding="utf-8")
        self.environment.pop(EnvVar.GIT_CONFIG_NOSYSTEM)
        self.environment[EnvVar.GIT_CONFIG_SYSTEM] = str(system)
        assert self.native().is_ignored("drop.tmp")
        self.environment.update(
            **{
                EnvVar.GIT_CONFIG_COUNT: "1",
                EnvVar.GIT_CONFIG_KEY_0: "core.excludesFile",
                EnvVar.GIT_CONFIG_VALUE_0: str(self.home / "missing"),
            },
        )
        assert not (self.native().is_ignored("drop.tmp"))

    def test_global_anchoring_uses_root_not_process_cwd(self) -> None:
        self.global_excludes("/drop.tmp\n")
        self.write("nested/drop.tmp")
        assert self.native().is_ignored_many(["drop.tmp", "nested/drop.tmp"]) == [True, False]

    def test_invalid_encoding_preserves_following_rules(self) -> None:
        self.write("nested/.gitignore").write_bytes(b"\xff\n*.tmp\n")
        decision = self.native().explain("nested/drop.tmp")
        assert (decision.ignored, decision.line, decision.pattern) == (True, 2, "*.tmp")

    def test_null_safe_paths_duplicates_and_empty_batch(self) -> None:
        self.write(".gitignore", "*.tmp\n")
        policy = self.native()
        names = ["space name.tmp", "unicodé.tmp", "tab\tname.tmp", "line\nname.tmp"]
        assert policy.is_ignored_many(names + names) == [True] * 8
        assert policy.explain_many([]) == []

    def test_lazy_git_queries_use_bounded_batches(self) -> None:
        self.write(".gitignore", "*.tmp\n")
        policy = self.native()
        with patch.object(policy, "_run", wraps=policy._run) as run:
            decisions = policy.iter_explain(["a.tmp", "b.tmp", "c.tmp"], batch_size=2)
            assert run.call_count == 0
            assert next(decisions).ignored
            assert run.call_count == 1
            assert [item.ignored for item in decisions] == [True, True]
            assert run.call_count == 2

    def test_baseline_paths_are_not_sent_to_git(self) -> None:
        self.write(".gitignore", "*.tmp\n")
        policy = self.native()
        with patch.object(policy, "_run", wraps=policy._run) as run:
            decisions = policy.explain_many([".git/config", "file.tmp", ".git/config"])
            assert [decision.ignored for decision in decisions] == [True, True, True]
            assert decisions[0].source == decisions[2].source == "initial Git-ignore exclusions"
            assert run.call_count == 1
            assert run.call_args.kwargs["data"] == b"file.tmp\0"
            run.reset_mock()
            assert policy.is_ignored_many([".git/config"]) == [True]
            run.assert_not_called()

    def test_tracked_paths_are_evaluated_without_index(self) -> None:
        self.write("tracked.tmp")
        self.git("add", "tracked.tmp")
        self.write(".gitignore", "*.tmp\n")
        assert self.native().is_ignored("tracked.tmp")
        result = subprocess.run(
            ["git", "-C", str(self.root), "check-ignore", "tracked.tmp"],
            env=self.environment,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 1

    def test_hard_baseline_and_batched_walker(self) -> None:
        self.global_excludes("*.tmp\n")
        self.write(".gitignore", "!keep.tmp\n")
        keep = self.write("docs/keep.md")
        self.write("docs/drop.tmp")
        self.write("keep.tmp")
        policy = self.native(initial_excludes=[".git/", "keep.tmp"])
        assert policy.is_ignored("keep.tmp")
        with patch.object(policy, "_run", wraps=policy._run) as run:
            files = set(GitIgnoreWalker(self.root, policy=policy).iter_files())
        assert files == {self.root / ".gitignore", keep}
        assert run.call_count == 2

    def test_fresh_queries_see_changes(self) -> None:
        source = self.global_excludes("*.tmp\n")
        policy = self.native()
        assert policy.is_ignored("file.tmp")
        source.write_text("*.log\n", encoding="utf-8")
        assert not (policy.is_ignored("file.tmp"))

    def test_worktree_uses_common_info_exclude(self) -> None:
        self.write("tracked")
        self.git("add", "tracked")
        self.git("commit", "--quiet", "-m", "fixture")
        worktree = self.base / "linked"
        self.git("worktree", "add", "--quiet", "--detach", str(worktree))
        self.write(".git/info/exclude", "*.tmp\n")
        assert GitStandardPolicy(worktree, environment=self.environment).is_ignored("x.tmp")

    def test_repository_selection_env_cannot_redirect_root(self) -> None:
        self.global_excludes("*.tmp\n")
        self.environment.update(GIT_DIR=str(self.base / "missing"), GIT_WORK_TREE=str(self.base))
        assert self.native().is_ignored("file.tmp")

    def test_outside_root_and_subdirectory_root_rejected(self) -> None:
        policy = self.native()
        with pytest.raises(ValueError):
            policy.is_ignored("../outside")
        child = self.root / "nested"
        child.mkdir()
        with pytest.raises(ValueError):
            GitStandardPolicy(child, environment=self.environment)

    def test_git_failure_and_timeout_raise(self) -> None:
        policy = self.native()
        with (
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 1)),
            pytest.raises(GitIgnoreError),
        ):
            policy.is_ignored("x")
        with pytest.raises(GitIgnoreError):
            self.native(git_executable=str(self.base / "missing-git"))
        with pytest.raises(ValueError):
            self.native(timeout=0)

    def test_nonzero_or_warning_never_returns_partial_result(self) -> None:
        policy = self.native()
        for result in [
            subprocess.CompletedProcess([], 128, b"", b"fatal: failure"),
            subprocess.CompletedProcess([], 0, b"", b"warning: could not read rules"),
            subprocess.CompletedProcess([], 0, b"partial", b""),
            subprocess.CompletedProcess([], 0, b".gitignore\x00x\x00*.tmp\x00x.tmp\x00", b""),
            subprocess.CompletedProcess([], 0, b".gitignore\x001\x00*.tmp\x00wrong\x00", b""),
        ]:
            with (
                patch("subprocess.run", return_value=result),
                pytest.raises(GitIgnoreError),
            ):
                policy.is_ignored("x.tmp")

    def test_final_symlink_matches_its_own_git_path(self) -> None:
        actual = self.write("actual")
        link = self.symlink(actual, "alias")
        self.write(".gitignore", "alias\n")
        decision = self.native().explain(link)
        assert decision.ignored
        assert decision.path == link
        assert not (self.native().is_ignored(actual))

    def test_directory_only_baseline_does_not_follow_final_symlink(self) -> None:
        actual = self.root / "actual-directory"
        actual.mkdir()
        link = self.symlink(actual, "alias")
        self.write(".gitignore", "alias/\n")
        policy = self.native(initial_excludes=["alias/"])
        assert not (policy.is_ignored(link))

    def test_broken_and_outside_final_symlinks_use_link_identity(self) -> None:
        outside = self.base / "outside-directory"
        outside.mkdir()
        outside_link = self.symlink(outside, "outside-link")
        broken = self.symlink(self.base / "absent", "broken-link")
        self.write(".gitignore", "*-link\n")
        decisions = self.native().explain_many([outside_link, broken])
        assert tuple(item.path for item in decisions) == (outside_link, broken)
        assert tuple(item.ignored for item in decisions) == (True, True)
        (self.root / ".gitignore").write_text("", encoding="utf-8")
        policy = self.native(initial_excludes=["outside-link/", "broken-link/"])
        assert policy.is_ignored_many([outside_link, broken]) == [False, False]

    def test_intermediate_symlink_and_symlink_walk_top_rejected(self) -> None:
        actual = self.write("docs/file")
        link = self.symlink(actual.parent, "alias")
        policy = self.native()
        with pytest.raises(ValueError):
            policy.is_ignored(link / "file")
        with pytest.raises(ValueError):
            list(GitIgnoreWalker(self.root, policy=policy).iter_files(link))

    @pytest.mark.skipif(
        os.name == "nt", reason="Windows disallows trailing CR/LF in directory names"
    )
    @pytest.mark.parametrize("suffix", ["\n", "\r"])
    def test_root_with_trailing_newline_or_carriage_return(self, suffix: str) -> None:
        self.root = self.base / ("repo" + suffix)
        self.root.mkdir()
        self.init()
        self.write(".gitignore", "*.tmp\n")
        assert self.native().is_ignored("drop.tmp")

    def test_worktree_specific_configuration(self) -> None:
        self.write("tracked")
        self.git("add", "tracked")
        self.git("commit", "--quiet", "-m", "fixture")
        worktree = self.base / "linked"
        self.git("worktree", "add", "--quiet", "--detach", str(worktree))
        self.git("config", "extensions.worktreeConfig", "true")
        patterns = self.home / "worktree-patterns"
        patterns.write_text("*.tmp\n", encoding="utf-8")
        subprocess.run(
            [
                "git",
                "-C",
                str(worktree),
                "config",
                "--worktree",
                "core.excludesFile",
                str(patterns),
            ],
            env=self.environment,
            capture_output=True,
            check=True,
        )
        assert not (self.native().is_ignored("x.tmp"))
        policy = GitStandardPolicy(worktree, environment=self.environment)
        assert policy.is_ignored("x.tmp")

    def test_separate_git_directory(self) -> None:
        metadata = self.base / "git-metadata"
        self.git("init", "--quiet", f"--separate-git-dir={metadata}")
        assert (self.root / ".git").is_file()
        (metadata / "info" / "exclude").write_text("*.tmp\n", encoding="utf-8")
        assert self.native().is_ignored("drop.tmp")

    def test_relative_excludes_file_resolves_with_git_cwd(self) -> None:
        self.write("local-ignore", "*.tmp\n")
        self.git("config", "--local", "core.excludesFile", "local-ignore")
        assert self.native().is_ignored("drop.tmp")

    @pytest.mark.parametrize("timeout", [float("nan"), float("inf"), -float("inf")])
    def test_nonfinite_timeout_rejected(self, timeout: float) -> None:
        with pytest.raises(ValueError):
            self.native(timeout=timeout)

    def test_undecodable_git_provenance_is_preserved(self) -> None:
        policy = self.native()
        result = subprocess.CompletedProcess([], 0, b".gitignore\x001\x00\xff\x00file\x00", b"")
        with patch("subprocess.run", return_value=result):
            decision = policy.explain("file")
        assert decision.pattern == "\udcff"
        assert decision.ignored

    def test_malformed_git_config_raises(self) -> None:
        (self.home / "config").write_text("[invalid\n", encoding="utf-8")
        with pytest.raises(GitIgnoreError):
            self.native()


class TestDifferential(RepositoryCase):
    def test_trailing_space_paths_follow_platform_semantics(self) -> None:
        self.init()
        self.write(".gitignore", "trailing   \nspace\\ \n")
        targets = ["trailing", "trailing   ", "space ", "space"]
        # Win32 cannot represent the trailing-space names as distinct ordinary
        # files. Git for Windows normalizes them; the portable legacy API does not.
        portable = [True, False, True, False]
        native = [True, True, False, False] if os.name == "nt" else portable
        assert GitIgnorePolicy(self.root).is_ignored_many(targets) == portable
        assert self.native().is_ignored_many(targets) == native

    @pytest.mark.parametrize(
        ("patterns", "targets"),
        [
            ("*.tmp\n!keep.tmp\n", ["drop.tmp", "keep.tmp", "docs/drop.tmp", "plain"]),
            ("/root.tmp\n", ["root.tmp", "docs/root.tmp"]),
            ("docs/**/draft.md\n", ["docs/draft.md", "docs/a/b/draft.md", "draft.md"]),
            ("**/generated/*.md\n", ["generated/a.md", "a/generated/b.md", "generated/a.txt"]),
            ("a/**/b.txt\n", ["a/b.txt", "a/x/b.txt", "a/x/y/b.txt", "x/a/b.txt"]),
            ("abc/**\n", ["abc", "abc/x", "abc/x/y", "x/abc/y"]),
            ("/build/\n", ["build", "a/build", "build/sub/file"]),
            ("foo\n!nested/foo\n", ["foo", "a/foo", "nested/foo", "nested/a/foo"]),
            ("dir/**\n!dir/keep\n", ["dir", "dir/keep", "dir/drop", "dir/sub/file"]),
            ("dir/\n!dir/keep\n", ["dir", "dir/keep", "dir/drop"]),
            ("\\#literal\n\\!literal\n", ["#literal", "!literal", "other"]),
            ("[ab]?.tmp\n", ["a1.tmp", "b2.tmp", "c1.tmp", "a.tmp"]),
            ("[]a].txt\n", ["].txt", "a.txt", "b.txt"]),
            ("file[!0-4].txt\n", ["file5.txt", "file0.txt", "nested/file9.txt"]),
            ("[^a].txt\n", ["a.txt", "b.txt", "nested/c.txt"]),
        ],
    )
    def test_portable_pattern_corpus_against_git(self, patterns: str, targets: list[str]) -> None:
        self.init()
        (self.root / "dir").mkdir()
        self.write(".gitignore", patterns)
        expected = self.native().is_ignored_many(targets)
        assert GitIgnorePolicy(self.root).is_ignored_many(targets) == expected

    def test_escaped_closing_bracket_class_matches_git(self) -> None:
        self.init()
        self.write(".gitignore", "[a\\]b].txt\n")
        targets = ["a.txt", "].txt", "b.txt", "c.txt"]
        expected = self.native().is_ignored_many(targets)
        assert expected == [True, True, True, False]
        assert GitIgnorePolicy(self.root).is_ignored_many(targets) == expected


class TestPolicySelection(RepositoryCase):
    def select(self, **kwargs):
        from gitignore_walk import select_policy

        return select_policy(self.root, environment=self.environment, **kwargs)

    def test_missing_git_fallback_is_explicit_and_quiet(self, capsys):
        missing = str(self.base / "missing-git")
        selection = self.select(mode="prefer-git", git_executable=missing)
        assert selection.backend == "portable"
        assert selection.fallback_reason == "git-executable-missing"
        assert isinstance(selection.policy, GitIgnorePolicy)
        assert capsys.readouterr() == ("", "")
        with pytest.raises(GitIgnoreError):
            self.select(mode="git", git_executable=missing)
        with pytest.raises(GitIgnoreError):
            GitStandardPolicy(self.root, git_executable=missing)

    @pytest.mark.parametrize(
        "error",
        [PermissionError("denied"), subprocess.TimeoutExpired("git", 1), OSError("failed")],
    )
    def test_nonmissing_process_errors_propagate(self, error):
        with patch("subprocess.run", side_effect=error), pytest.raises(GitIgnoreError):
            self.select(mode="prefer-git")

    def test_existing_executable_with_missing_interpreter_is_not_absence(self):
        executable = self.base / "git-script"
        executable.write_text("#!/nonexistent/interpreter\n", encoding="utf-8")
        executable.chmod(0o755)
        with (
            patch("subprocess.run", side_effect=FileNotFoundError("loader missing")),
            pytest.raises(GitIgnoreError),
        ):
            self.select(mode="prefer-git", git_executable=str(executable))

    def test_bad_repo_and_config_do_not_fall_back(self):
        if not shutil.which("git"):
            pytest.skip("Git is required")
        with pytest.raises(GitIgnoreError):
            self.select(mode="prefer-git")
        self.init()
        (self.home / "config").write_text("[broken\n", encoding="utf-8")
        with pytest.raises(GitIgnoreError):
            self.select(mode="prefer-git")

    def test_selection_is_eager_and_never_changes_midstream(self):
        self.init()
        selection = self.select(mode="prefer-git")
        assert selection.backend == "git"
        assert selection.fallback_reason is None
        decisions = selection.policy.iter_explain(["first", "second"], batch_size=1)
        assert next(decisions).path.name == "first"
        with (
            patch("subprocess.run", side_effect=FileNotFoundError("removed")),
            pytest.raises(GitIgnoreError),
        ):
            next(decisions)
        assert selection.backend == "git"

    def test_fallback_sources_and_complete_environment(self):
        self.write(".git/info/exclude", "*.local\n")
        self.write(".gitignore", "*.log\n")
        self.write("nested/.gitignore", "!keep.log\n")
        global_ignore = self.home / "xdg/git/ignore"
        global_ignore.parent.mkdir(parents=True)
        global_ignore.write_text("*.global\n", encoding="utf-8")
        with patch.dict(os.environ, {EnvVar.XDG_CONFIG_HOME: str(self.base / "wrong")}):
            selection = self.select(mode="prefer-git", git_executable=str(self.base / "absent"))
        assert selection.policy.is_ignored_many(
            ["nested/a.log", "nested/keep.log", "a.local", "a.global", "plain"]
        ) == [True, False, True, True, False]

    def test_supplied_home_is_used_without_ambient_xdg(self):
        from gitignore_walk import select_policy

        ignore = self.home / ".config/git/ignore"
        ignore.parent.mkdir(parents=True)
        ignore.write_text("*.home\n", encoding="utf-8")
        selection = select_policy(
            self.root,
            mode="prefer-git",
            git_executable=str(self.base / "absent"),
            environment={EnvVar.HOME: str(self.home), EnvVar.USERPROFILE: str(self.home)},
        )
        assert selection.policy.is_ignored("a.home")
        assert not select_policy(self.root, environment={}).policy.is_ignored("a.home")

    def test_custom_config_difference_is_preserved(self):
        self.init()
        custom = self.home / "custom-ignore"
        custom.write_text("*.custom\n", encoding="utf-8")
        self.git("config", "core.excludesFile", str(custom))
        native = self.select(mode="prefer-git")
        fallback = self.select(mode="prefer-git", git_executable=str(self.base / "absent"))
        assert native.policy.is_ignored("a.custom")
        assert not fallback.policy.is_ignored("a.custom")

    def test_portable_default_does_not_launch_git(self):
        with patch("subprocess.run", side_effect=AssertionError("must not execute")):
            selection = self.select()
        assert selection.backend == "portable"
        assert selection.fallback_reason is None

    def test_invalid_selection_and_timeout(self):
        with pytest.raises(ValueError):
            self.select(mode="unknown")
        with pytest.raises(ValueError):
            self.select(mode="prefer-git", timeout=0)

    def test_missing_name_uses_supplied_search_path(self):
        from gitignore_walk import select_policy

        empty_path = self.base / "empty-bin"
        empty_path.mkdir()
        selection = select_policy(
            self.root,
            mode="prefer-git",
            git_executable="gitignore-walk-missing-test-program",
            environment={"PATH": str(empty_path)},
        )
        assert selection.fallback_reason == "git-executable-missing"

    def test_fallback_never_retries_git_and_keeps_baseline(self):
        selection = self.select(
            mode="prefer-git",
            git_executable=str(self.base / "absent"),
            initial_excludes=(".git", "private"),
        )
        with patch("subprocess.run", side_effect=AssertionError("must not retry")):
            assert selection.policy.is_ignored("private")
            assert not selection.policy.is_ignored("public")

    def test_ancestor_rules_with_subdirectory_fallback(self):
        from gitignore_walk import select_policy

        self.write(".git/info/exclude", "*.local\n")
        self.write(".gitignore", "*.log\n")
        nested = self.write("nested/.gitignore", "!keep.log\n").parent
        selection = select_policy(
            nested, mode="prefer-git", git_executable=str(self.base / "absent"), environment={}
        )
        assert selection.policy.is_ignored_many(["a.log", "keep.log", "a.local"]) == [
            True,
            False,
            True,
        ]

    @pytest.mark.parametrize("returncode, stderr", [(128, b"bad config"), (0, b"warning")])
    def test_native_diagnostics_do_not_fall_back(self, returncode, stderr):
        result = subprocess.CompletedProcess([], returncode, b"", stderr)
        with patch("subprocess.run", return_value=result), pytest.raises(GitIgnoreError):
            self.select(mode="prefer-git")

    def test_explicit_home_precedes_windows_userprofile(self):
        from types import SimpleNamespace

        from gitignore_walk import _portable

        profile = self.base / "different-profile"
        with patch.object(_portable, "os", SimpleNamespace(name="nt")):
            path = _portable._default_global_excludes_path(
                {EnvVar.HOME: str(self.home), EnvVar.USERPROFILE: str(profile)}
            )
        assert path == self.home / ".config/git/ignore"

    def test_omitted_environment_preserves_ambient_home_discovery(self):
        from gitignore_walk import select_policy

        ignore = self.home / ".config/git/ignore"
        ignore.parent.mkdir(parents=True)
        ignore.write_text("*.home\n", encoding="utf-8")
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(Path, "home", return_value=self.home),
        ):
            assert GitIgnorePolicy(self.root).is_ignored("a.home")
            assert select_policy(self.root).policy.is_ignored("a.home")
            assert select_policy(
                self.root, mode="prefer-git", git_executable=str(self.base / "absent")
            ).policy.is_ignored("a.home")
            assert not select_policy(self.root, environment={}).policy.is_ignored("a.home")
