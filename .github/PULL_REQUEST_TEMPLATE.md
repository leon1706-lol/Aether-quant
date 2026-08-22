<!-- Title style: `V<version> <short what-and-why>` for release-bound PRs,
     matching the repo's commit history; otherwise a plain descriptive title. -->

## What & why

<!-- One paragraph: what changed and the problem/round it belongs to.
     Reference development/Problems.md entries (#N) where applicable. -->

## Changes

-
-

## Behavior contract

<!-- This repo's hard rule: prove what changed and for whom. -->

- [ ] Default behavior is byte-identical when new flags/params are absent (`None`-default / default-off convention), **or** the behavior change is intentional and listed below:
  - <!-- intentional changes here -->
- New config keys: <!-- `phase_v2.*` keys + defaults, or "none" -->

## Verification

<!-- How was this confirmed? The suite must be green before review. -->

- [ ] `aq test` green (N passed): <!-- paste count -->
- New tests: <!-- files + what they pin down -->
- Manual checks: <!-- CLI dry-runs, real-data spot checks -->
- Real Lean backtest: <!-- not run in PRs by convention; note if one is required before merge -->

## Docs updated

- [ ] README / sub-package README
- [ ] `development/Changelog.md` (append-only entry)
- [ ] `development/Problems.md` (if a bug was found/fixed)
- [ ] `development/architecture.md` / `development/infrastructure.md` (if structure/services changed)
- [ ] Obsidian vault regenerated (`generate_code_graph.py` → `regenerate_vault.py --append-handoff`)
