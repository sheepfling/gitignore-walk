"""Portable compatibility and isolated comparisons with Git's actual evaluator."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gitignore_walk import (
    GitIgnoreDecision,
    GitIgnoreError,
    GitIgnorePolicy,
    GitIgnoreWalker,
    GitStandardPolicy,
    is_gitignored,
    matches_gitignore,
    parse_gitignore,
)


class RepositoryCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "repo"
        self.root.mkdir()
        self.home = self.base / "home"
        self.home.mkdir()
        self.environment = {
            key: value for key, value in os.environ.items() if not key.startswith("GIT_")
        }
        self.environment.update(
            HOME=str(self.home),
            USERPROFILE=str(self.home),
            XDG_CONFIG_HOME=str(self.home / "xdg"),
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=str(self.home / "config"),
            GIT_AUTHOR_NAME="Test",
            GIT_AUTHOR_EMAIL="test@example.invalid",
            GIT_COMMITTER_NAME="Test",
            GIT_COMMITTER_EMAIL="test@example.invalid",
            GIT_TERMINAL_PROMPT="0",
        )

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
            self.skipTest("Git is required for oracle comparisons")
        self.git("init", "--quiet")

    def native(self, **kwargs: object) -> GitStandardPolicy:
        return GitStandardPolicy(self.root, environment=self.environment, **kwargs)

    def symlink(self, target: Path, name: str) -> Path:
        path = self.root / name
        try:
            path.symlink_to(target, target_is_directory=target.is_dir())
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        return path


class PortableTests(RepositoryCase):
    def test_point_batch_and_helpers(self) -> None:
        self.write(".gitignore", "# comment\n*.tmp\n!keep.tmp\n")
        drop = self.write("drop.tmp")
        keep = self.write("keep.tmp")
        policy = GitIgnorePolicy(self.root)
        self.assertTrue(is_gitignored(self.root, "drop.tmp"))
        self.assertEqual(policy.is_ignored_many([drop, keep, "missing.txt"]), (True, False, False))
        decision = policy.explain(drop)
        self.assertEqual((decision.path, decision.pattern, decision.line), (drop, "*.tmp", 2))
        self.assertIn(str(self.root / ".gitignore"), decision.source or "")
        self.assertEqual(policy.explain(keep), GitIgnoreDecision(path=keep, ignored=False))
        spec = parse_gitignore(["cache/"], source="test")
        self.assertTrue(matches_gitignore(spec, "cache", is_directory=True))
        self.assertFalse(matches_gitignore(spec, "cache", is_directory=False))

    def test_baseline_is_authoritative(self) -> None:
        self.write(".gitignore", "!drop.tmp\n")
        policy = GitIgnorePolicy(self.root, initial_excludes=["*.tmp"])
        self.assertTrue(policy.is_ignored("drop.tmp"))
        self.assertEqual(policy.explain("drop.tmp").source, "initial Git-ignore exclusions")

    def test_parent_exclusion_cannot_be_undone(self) -> None:
        self.write(".gitignore", "build/\n!build/keep.md\n")
        self.write("build/.gitignore", "!keep.md\n")
        self.assertTrue(GitIgnorePolicy(self.root).is_ignored("build/keep.md"))

    def test_nested_override_after_parent_unignored(self) -> None:
        self.write(".gitignore", "*.tmp\n")
        self.write("docs/.gitignore", "!keep.tmp\n")
        policy = GitIgnorePolicy(self.root)
        self.assertFalse(policy.is_ignored("docs/keep.tmp"))
        self.assertTrue(policy.is_ignored("docs/drop.tmp"))

    def test_missing_descendant_under_ignored_parent(self) -> None:
        self.write(".gitignore", "build/\n")
        (self.root / "build").mkdir()
        decision = GitIgnorePolicy(self.root).explain("build/not-created/sub/file.txt")
        self.assertTrue(decision.ignored)
        self.assertEqual(decision.pattern, "build/")

    def test_fresh_batch_reads_changed_policy(self) -> None:
        ignore = self.write(".gitignore", "*.tmp\n")
        policy = GitIgnorePolicy(self.root)
        self.assertEqual(policy.is_ignored_many(["file.tmp"]), (True,))
        ignore.write_text("!*.tmp\n", encoding="utf-8")
        self.assertEqual(policy.is_ignored_many(["file.tmp"]), (False,))

    def test_invalid_encoding_raises(self) -> None:
        self.write("docs/.gitignore").write_bytes(b"\xff\n*.tmp\n")
        with self.assertRaises(GitIgnoreError):
            GitIgnorePolicy(self.root).is_ignored("docs/drop.tmp")

    def test_outside_root_rejected(self) -> None:
        with self.assertRaises(ValueError):
            GitIgnorePolicy(self.root).is_ignored("../outside")
        with self.assertRaises(ValueError):
            GitIgnorePolicy(self.root / "missing")

    def test_symlink_escape_rejected(self) -> None:
        outside = self.base / "outside"
        outside.mkdir()
        self.symlink(outside, "escape")
        with self.assertRaises(ValueError):
            GitIgnorePolicy(self.root).is_ignored("escape/file")

    def test_walk_default_filter_and_ignored_descendants(self) -> None:
        self.write(".gitignore", "*.tmp\nbuild/\n")
        self.write("docs/keep.md")
        self.write("docs/drop.tmp")
        self.write("build/output")
        walker = GitIgnoreWalker(self.root)
        all_files = {p.relative_to(self.root).as_posix() for p in walker.iter_files()}
        selected = {p.relative_to(self.root).as_posix() for p in walker.iter_files(ignored=False)}
        ignored = {p.relative_to(self.root).as_posix() for p in walker.iter_files(ignored=True)}
        self.assertEqual(selected, {".gitignore", "docs/keep.md"})
        self.assertEqual(ignored, {"docs/drop.tmp", "build/output"})
        self.assertEqual(all_files, selected | ignored)
        with self.assertRaises(ValueError):
            list(walker.walk(follow_links=True))

    def test_topdown_directory_pruning(self) -> None:
        self.write("docs/keep.md")
        self.write("build/output")
        walker = GitIgnoreWalker(self.root)
        rows = walker.walk()
        _, directories, _ = next(rows)
        directories.remove("build")
        self.assertEqual([directory.name for directory, _, _ in rows], ["docs"])

    def test_discovered_symlinks_and_special_files_omitted(self) -> None:
        file = self.write("real.txt")
        self.symlink(file, "link.txt")
        if hasattr(os, "mkfifo"):
            os.mkfifo(self.root / "fifo")
        self.assertEqual(list(GitIgnoreWalker(self.root).iter_files()), [file])

    def test_supplied_policy_root_must_match(self) -> None:
        child = self.root / "child"
        child.mkdir()
        with self.assertRaises(ValueError):
            GitIgnoreWalker(child, policy=GitIgnorePolicy(self.root))

    def test_bottom_up_legacy_rows_are_documented(self) -> None:
        self.write(".gitignore", "build/\n")
        self.write("build/ignored")
        rows = list(GitIgnoreWalker(self.root).walk(ignored=False, topdown=False))
        self.assertIn((self.root / "build", [], []), rows)

    def test_explicit_internal_symlink_top_legacy_behavior(self) -> None:
        file = self.write("docs/keep.md")
        link = self.symlink(file.parent, "docs-link")
        self.assertEqual(list(GitIgnoreWalker(self.root).iter_files(link)), [file])

    def test_read_failure_not_silenced(self) -> None:
        self.write(".gitignore", "*.tmp\n")
        with (
            patch.object(Path, "read_text", side_effect=PermissionError("denied")),
            self.assertRaises(GitIgnoreError),
        ):
            GitIgnorePolicy(self.root).is_ignored("drop.tmp")


class NativeTests(RepositoryCase):
    def setUp(self) -> None:
        super().setUp()
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
        self.assertTrue(drop.ignored)
        self.assertEqual((Path(drop.source or ""), drop.line, drop.pattern), (source, 1, "*.tmp"))
        self.assertFalse(keep.ignored)
        self.assertEqual((keep.source, keep.line, keep.pattern), (".gitignore", 1, "!keep.tmp"))
        self.assertEqual(unmatched, GitIgnoreDecision(self.root / "plain.txt", False))
        self.assertFalse(GitIgnorePolicy(self.root).is_ignored("drop.tmp"))

    def test_info_exclude_and_root_override(self) -> None:
        self.write(".git/info/exclude", "*.cache\n")
        self.write(".gitignore", "!keep.cache\n")
        policy = self.native()
        self.assertEqual(policy.is_ignored_many(["drop.cache", "keep.cache"]), (True, False))
        self.assertEqual(policy.explain("drop.cache").source, ".git/info/exclude")

    def test_quoted_config_value_spaces(self) -> None:
        path = self.home / "quoted ignore file"
        path.write_text("*.tmp\n", encoding="utf-8")
        (self.home / "config").write_text(
            f'[core]\n excludesFile = "{path.as_posix()}"\n', encoding="utf-8"
        )
        self.assertTrue(self.native().is_ignored("drop.tmp"))

    def test_config_include(self) -> None:
        source = self.home / "patterns"
        source.write_text("*.tmp\n", encoding="utf-8")
        (self.home / "included").write_text(
            f'[core]\n excludesFile = "{source.as_posix()}"\n', encoding="utf-8"
        )
        (self.home / "config").write_text("[include]\n path = included\n", encoding="utf-8")
        self.assertTrue(self.native().is_ignored("drop.tmp"))

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
        self.assertTrue(self.native().is_ignored("drop.tmp"))

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
        self.assertEqual(self.native().is_ignored_many(["x.first", "x.second"]), (False, True))

    def test_local_configuration_overrides_global(self) -> None:
        self.global_excludes("*.global\n")
        source = self.home / "local"
        source.write_text("*.local\n", encoding="utf-8")
        self.git("config", "--local", "core.excludesFile", str(source))
        self.assertEqual(self.native().is_ignored_many(["x.global", "x.local"]), (False, True))

    def test_git_config_global_override(self) -> None:
        source = self.home / "patterns"
        source.write_text("*.tmp\n", encoding="utf-8")
        custom = self.home / "custom-config"
        custom.write_text(f'[core]\n excludesFile = "{source.as_posix()}"\n', encoding="utf-8")
        self.environment["GIT_CONFIG_GLOBAL"] = str(custom)
        self.assertTrue(self.native().is_ignored("drop.tmp"))

    def test_xdg_fallback(self) -> None:
        xdg = self.home / "xdg" / "git"
        xdg.mkdir(parents=True)
        (xdg / "ignore").write_text("*.tmp\n", encoding="utf-8")
        self.assertTrue(self.native().is_ignored("drop.tmp"))

    def test_default_home_config_location(self) -> None:
        self.environment.pop("GIT_CONFIG_GLOBAL")
        source = self.home / "patterns"
        source.write_text("*.tmp\n", encoding="utf-8")
        (self.home / ".gitconfig").write_text(
            f'[core]\n excludesFile = "{source.as_posix()}"\n', encoding="utf-8"
        )
        self.assertTrue(self.native().is_ignored("drop.tmp"))

    def test_missing_configured_excludes_does_not_fall_back(self) -> None:
        xdg = self.home / "xdg" / "git"
        xdg.mkdir(parents=True)
        (xdg / "ignore").write_text("*.tmp\n", encoding="utf-8")
        self.git("config", "--global", "core.excludesFile", str(self.home / "missing"))
        self.assertFalse(self.native().is_ignored("drop.tmp"))

    def test_tilde_excludes_file(self) -> None:
        (self.home / "patterns").write_text("*.tmp\n", encoding="utf-8")
        self.git("config", "--global", "core.excludesFile", "~/patterns")
        self.assertTrue(self.native().is_ignored("drop.tmp"))

    def test_system_config_and_environment_count_override(self) -> None:
        source = self.home / "patterns"
        source.write_text("*.tmp\n", encoding="utf-8")
        system = self.home / "system-config"
        system.write_text(f'[core]\n excludesFile = "{source.as_posix()}"\n', encoding="utf-8")
        self.environment.pop("GIT_CONFIG_NOSYSTEM")
        self.environment["GIT_CONFIG_SYSTEM"] = str(system)
        self.assertTrue(self.native().is_ignored("drop.tmp"))
        self.environment.update(
            GIT_CONFIG_COUNT="1",
            GIT_CONFIG_KEY_0="core.excludesFile",
            GIT_CONFIG_VALUE_0=str(self.home / "missing"),
        )
        self.assertFalse(self.native().is_ignored("drop.tmp"))

    def test_global_anchoring_uses_root_not_process_cwd(self) -> None:
        self.global_excludes("/drop.tmp\n")
        self.write("nested/drop.tmp")
        self.assertEqual(
            self.native().is_ignored_many(["drop.tmp", "nested/drop.tmp"]), (True, False)
        )

    def test_invalid_encoding_preserves_following_rules(self) -> None:
        self.write("nested/.gitignore").write_bytes(b"\xff\n*.tmp\n")
        decision = self.native().explain("nested/drop.tmp")
        self.assertEqual((decision.ignored, decision.line, decision.pattern), (True, 2, "*.tmp"))

    def test_null_safe_paths_duplicates_and_empty_batch(self) -> None:
        self.write(".gitignore", "*.tmp\n")
        policy = self.native()
        names = ["space name.tmp", "unicodé.tmp", "tab\tname.tmp", "line\nname.tmp"]
        self.assertEqual(policy.is_ignored_many(names + names), (True,) * 8)
        self.assertEqual(policy.explain_many([]), ())

    def test_tracked_paths_are_evaluated_without_index(self) -> None:
        self.write("tracked.tmp")
        self.git("add", "tracked.tmp")
        self.write(".gitignore", "*.tmp\n")
        self.assertTrue(self.native().is_ignored("tracked.tmp"))
        result = subprocess.run(
            ["git", "-C", str(self.root), "check-ignore", "tracked.tmp"],
            env=self.environment,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)

    def test_hard_baseline_and_batched_walker(self) -> None:
        self.global_excludes("*.tmp\n")
        self.write(".gitignore", "!keep.tmp\n")
        keep = self.write("docs/keep.md")
        self.write("docs/drop.tmp")
        self.write("keep.tmp")
        policy = self.native(initial_excludes=[".git/", "keep.tmp"])
        self.assertTrue(policy.is_ignored("keep.tmp"))
        with patch.object(policy, "_run", wraps=policy._run) as run:
            files = set(GitIgnoreWalker(self.root, policy=policy).iter_files(ignored=False))
        self.assertEqual(files, {self.root / ".gitignore", keep})
        self.assertEqual(run.call_count, 2)

    def test_fresh_queries_see_changes(self) -> None:
        source = self.global_excludes("*.tmp\n")
        policy = self.native()
        self.assertTrue(policy.is_ignored("file.tmp"))
        source.write_text("*.log\n", encoding="utf-8")
        self.assertFalse(policy.is_ignored("file.tmp"))

    def test_worktree_uses_common_info_exclude(self) -> None:
        self.write("tracked")
        self.git("add", "tracked")
        self.git("commit", "--quiet", "-m", "fixture")
        worktree = self.base / "linked"
        self.git("worktree", "add", "--quiet", "--detach", str(worktree))
        self.write(".git/info/exclude", "*.tmp\n")
        self.assertTrue(
            GitStandardPolicy(worktree, environment=self.environment).is_ignored("x.tmp")
        )

    def test_repository_selection_env_cannot_redirect_root(self) -> None:
        self.global_excludes("*.tmp\n")
        self.environment.update(GIT_DIR=str(self.base / "missing"), GIT_WORK_TREE=str(self.base))
        self.assertTrue(self.native().is_ignored("file.tmp"))

    def test_outside_root_and_subdirectory_root_rejected(self) -> None:
        policy = self.native()
        with self.assertRaises(ValueError):
            policy.is_ignored("../outside")
        child = self.root / "nested"
        child.mkdir()
        with self.assertRaises(ValueError):
            GitStandardPolicy(child, environment=self.environment)

    def test_git_failure_and_timeout_raise(self) -> None:
        policy = self.native()
        with (
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 1)),
            self.assertRaises(GitIgnoreError),
        ):
            policy.is_ignored("x")
        with self.assertRaises(GitIgnoreError):
            self.native(git_executable=str(self.base / "missing-git"))
        with self.assertRaises(ValueError):
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
                self.subTest(result=result),
                patch("subprocess.run", return_value=result),
                self.assertRaises(GitIgnoreError),
            ):
                policy.is_ignored("x.tmp")

    def test_final_symlink_matches_its_own_git_path(self) -> None:
        actual = self.write("actual")
        link = self.symlink(actual, "alias")
        self.write(".gitignore", "alias\n")
        decision = self.native().explain(link)
        self.assertTrue(decision.ignored)
        self.assertEqual(decision.path, link)
        self.assertFalse(self.native().is_ignored(actual))

    def test_directory_only_baseline_does_not_follow_final_symlink(self) -> None:
        actual = self.root / "actual-directory"
        actual.mkdir()
        link = self.symlink(actual, "alias")
        self.write(".gitignore", "alias/\n")
        policy = self.native(initial_excludes=["alias/"])
        self.assertFalse(policy.is_ignored(link))

    def test_broken_and_outside_final_symlinks_use_link_identity(self) -> None:
        outside = self.base / "outside-directory"
        outside.mkdir()
        outside_link = self.symlink(outside, "outside-link")
        broken = self.symlink(self.base / "absent", "broken-link")
        self.write(".gitignore", "*-link\n")
        decisions = self.native().explain_many([outside_link, broken])
        self.assertEqual(tuple(item.path for item in decisions), (outside_link, broken))
        self.assertEqual(tuple(item.ignored for item in decisions), (True, True))
        (self.root / ".gitignore").write_text("", encoding="utf-8")
        policy = self.native(initial_excludes=["outside-link/", "broken-link/"])
        self.assertEqual(policy.is_ignored_many([outside_link, broken]), (False, False))

    def test_intermediate_symlink_and_symlink_walk_top_rejected(self) -> None:
        actual = self.write("docs/file")
        link = self.symlink(actual.parent, "alias")
        policy = self.native()
        with self.assertRaises(ValueError):
            policy.is_ignored(link / "file")
        with self.assertRaises(ValueError):
            list(GitIgnoreWalker(self.root, policy=policy).iter_files(link))

    @unittest.skipIf(os.name == "nt", "Windows disallows trailing CR/LF in directory names")
    def test_root_with_trailing_newline_or_carriage_return(self) -> None:
        for suffix in ["\n", "\r"]:
            with self.subTest(suffix=suffix):
                self.root = self.base / ("repo" + suffix)
                self.root.mkdir()
                self.init()
                self.write(".gitignore", "*.tmp\n")
                self.assertTrue(self.native().is_ignored("drop.tmp"))

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
        self.assertFalse(self.native().is_ignored("x.tmp"))
        policy = GitStandardPolicy(worktree, environment=self.environment)
        self.assertTrue(policy.is_ignored("x.tmp"))

    def test_separate_git_directory(self) -> None:
        metadata = self.base / "git-metadata"
        self.git("init", "--quiet", f"--separate-git-dir={metadata}")
        self.assertTrue((self.root / ".git").is_file())
        (metadata / "info" / "exclude").write_text("*.tmp\n", encoding="utf-8")
        self.assertTrue(self.native().is_ignored("drop.tmp"))

    def test_relative_excludes_file_resolves_with_git_cwd(self) -> None:
        self.write("local-ignore", "*.tmp\n")
        self.git("config", "--local", "core.excludesFile", "local-ignore")
        self.assertTrue(self.native().is_ignored("drop.tmp"))

    def test_nonfinite_timeout_rejected(self) -> None:
        for timeout in [float("nan"), float("inf"), -float("inf")]:
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                self.native(timeout=timeout)

    def test_undecodable_git_provenance_is_preserved(self) -> None:
        policy = self.native()
        result = subprocess.CompletedProcess([], 0, b".gitignore\x001\x00\xff\x00file\x00", b"")
        with patch("subprocess.run", return_value=result):
            decision = policy.explain("file")
        self.assertEqual(decision.pattern, "\udcff")
        self.assertTrue(decision.ignored)

    def test_malformed_git_config_raises(self) -> None:
        (self.home / "config").write_text("[invalid\n", encoding="utf-8")
        with self.assertRaises(GitIgnoreError):
            self.native()


class DifferentialTests(RepositoryCase):
    def test_portable_pattern_corpus_against_git(self) -> None:
        self.init()
        fixtures = [
            ("*.tmp\n!keep.tmp\n", ["drop.tmp", "keep.tmp", "docs/drop.tmp", "plain"]),
            ("/root.tmp\n", ["root.tmp", "docs/root.tmp"]),
            ("docs/**/draft.md\n", ["docs/draft.md", "docs/a/b/draft.md", "draft.md"]),
            ("**/generated/*.md\n", ["generated/a.md", "a/generated/b.md", "generated/a.txt"]),
            ("dir/**\n!dir/keep\n", ["dir", "dir/keep", "dir/drop", "dir/sub/file"]),
            ("dir/\n!dir/keep\n", ["dir", "dir/keep", "dir/drop"]),
            ("\\#literal\n\\!literal\n", ["#literal", "!literal", "other"]),
            ("trailing   \nspace\\ \n", ["trailing", "trailing   ", "space ", "space"]),
            ("[ab]?.tmp\n", ["a1.tmp", "b2.tmp", "c1.tmp", "a.tmp"]),
        ]
        (self.root / "dir").mkdir()
        for patterns, targets in fixtures:
            with self.subTest(patterns=patterns):
                self.write(".gitignore", patterns)
                expected = self.native().is_ignored_many(targets)
                self.assertEqual(GitIgnorePolicy(self.root).is_ignored_many(targets), expected)


if __name__ == "__main__":
    unittest.main()
