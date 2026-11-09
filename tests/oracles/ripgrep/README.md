# ripgrep scanner research

`research_cases.json` imports the 16 scanner cases from the implementation research handoff. It
classifies source precedence, repository discovery, hidden-file selection, parent pruning, and scan
root boundaries. Every case is explicitly scoped to ripgrep's scanner behavior; these rules are not
part of Git-ignore policy or the VCS selection API.

The pinned native capture is `results/rg-14.1.1-linux-x86_64.json`: ripgrep 14.1.1 on Linux x86_64,
with all 16 assertions passing. `tests/test_ripgrep_research.py` checks that the imported inventory
matches the captured expected and observed paths. It does not claim that this package implements
ripgrep's scanning policy.

A scanner policy remains a separate, opt-in product feature. The current project only records this
research evidence; no scanner API, command-line behavior, or Git policy fallback is added here.
