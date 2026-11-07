# Maturity and mdrepo migration gates

Do not change mdrepo as part of this extraction. Its main source at `78476e0` and draft Python 3.10
PR #11 are separate workstreams. This package is an unreleased review candidate.

## Before a first package release

- Confirm the final distribution name. The private repository exists; PyPI search absence is not
  a package-name reservation.
- Run the proposed OS/Python matrix on the exact commit. Exercise an installed wheel outside the
  source tree, and verify `py.typed` and license/package metadata in both wheel and sdist.
- Extend differential fixtures for case sensitivity, Windows separators/encoding, worktree config,
  symlink boundaries, Git diagnostics, missing paths, permission failures and Unicode edge cases.
- Decide whether to retain or deliberately change the documented legacy portable symlink and
  bottom-up-walk behaviors. Do not describe them as fixed while preserving them.
- Benchmark realistic repositories: native point queries start one process; batches start one
  process, and filtered walks start one per visited directory. There is no parallel/persistent
  subprocess implementation in this alpha.
- Keep the portable parser dependency-free and expand the Git differential corpus whenever matcher
  semantics change.
- Review external API/error stability, cancellation/timeout behavior and source provenance.

## Later mdrepo migration

1. First replace only the internal portable implementation behind mdrepo's existing public
   `mdrepo.gitignore` imports. Keep mdrepo-specific durability models in mdrepo. Retain current
   defaults, exception types, callers' hard exclusions, walk filtering and diagnostics.
2. Run mdrepo's full existing suite and installed-consumer checks against that adapter. A package
   unit-test pass does not prove mdrepo integration. Preserve Python 3.10 compatibility.
3. Introduce a separately reviewed, explicit setting for Git-aware/global policy where Rick wants
   it. Machine-local rules can alter documentation discovery and graph eligibility; durability
   diagnostics and discovery may need different scopes. Do not switch all consumers silently.
4. Specify absent-Git and non-repository behavior. This alpha errors in native mode; silently
   falling back would lose global policy and must not become the integration default.
5. Keep an adapter-level rollback path during adoption. Do not merge, release or publish until
   separately authorized and exact-head CI has passed.

## Why not use ignore-python as a drop-in?

The investigated 0.4.2 binding supports useful Rust traversal, but not the point/explain/batch,
ignored-only traversal or mutable-pruning contracts required here. The investigation reproduced
silent partial parsing of invalid-UTF-8 nested ignores, and config resolution differences for
quoted paths, includes, repeated keys, unrelated sections, explicit global override, local config
and process-cwd anchoring. A fast traversal backend would still need an adapter and differential
acceptance suite; adding it now would not remove this policy work.
