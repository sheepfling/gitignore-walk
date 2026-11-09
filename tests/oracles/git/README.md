# Git research oracle

`research_cases.json` imports the 79 Git cases from the implementation research handoff. Each
case keeps its candidate expectation and source note, and adds an evidence label, target area, test
target, and current coverage status. The seven smaller checkpoint probes remain separate in
`checkpoint_cases.json` because they specifically test parent barriers, contents-only exceptions,
and tracked-file behavior.

Run the library comparisons with:

```sh
python -m pytest tests/test_git_checkpoint.py tests/test_git_research.py -q
```

The imported pinned native capture is `results/git-2.47.3-linux-x86_64-research.json`: Git 2.47.3
and ripgrep 14.1.1 on Linux x86_64, with 94 assertions passed and one observation-only malformed
input. This capture is native-client research evidence; it is not a test result for this package.

The portable-policy suite currently compares 72 cases. Five Git-config, worktree, and tracked-file
cases also have native-policy checks. `GitStandardPolicy` deliberately uses `--no-index`, so its
tracked-path result describes rule matching; it does not predict index-aware `git check-ignore`
output. The non-UTF-8 filename case runs on Linux and skips on macOS. The NUL-in-rule probe remains
observation-only and is not emulated as a required behavior. Ripgrep's 16 scanner cases belong to a
separate optional-policy suite and are not imported into Git matching.

The original research runner also captured Git 2.54.0 on macOS, but macOS could not create the
non-UTF-8 filename fixture. That local attempt is intentionally not presented as a complete native
profile. The Linux handoff capture is the pinned complete native baseline.
