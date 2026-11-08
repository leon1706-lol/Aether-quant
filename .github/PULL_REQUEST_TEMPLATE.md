<!-- Title: `V<version> <what and why>` for release-bound PRs, otherwise plain and descriptive. -->

## What and why

<!-- One paragraph. Reference development/Problems.md entries (#N) where they apply. -->

## Behaviour

- [ ] Unchanged when new flags are absent, **or** the change is intentional and listed here:
- New config keys and defaults: <!-- or "none" -->

## Verification

- [ ] `aq test` green (N passed), `ruff check .` clean, `aq verify --quick` green
- [ ] A new public function or class is in `aether_quant`, or listed with a reason (`scripts/library_gate.py`)
- [ ] A new invariant in a safety, admission or ledger path has a Lean spec, a differential test and a property test (`development/verification.md`)
- [ ] `scripts/clean_checkout_test.ps1`, or `scripts/codespace_verify.ps1 -Start` on a low-memory PC
- New tests: <!-- files, and what they pin -->
- Manual checks: <!-- dry runs, real-data spot checks -->

## Docs

- [ ] README or package README
- [ ] `development/Changelog.md`, and `development/Problems.md` if a bug was found
- [ ] `development/architecture.md` or `infrastructure.md` if structure or services changed
- [ ] `aq docs sync`, and the vault regenerated
