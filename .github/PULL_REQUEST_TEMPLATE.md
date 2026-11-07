<!-- Title: `V<version> <what and why>` for release-bound PRs, otherwise plain and descriptive. -->

## What and why

<!-- One paragraph. Reference development/Problems.md entries (#N) where they apply. -->

## Behaviour

- [ ] Unchanged when new flags are absent, **or** the change is intentional and listed here:
- New config keys and defaults: <!-- or "none" -->

## Verification

- [ ] `aq test` green (N passed)
- New tests: <!-- files, and what they pin -->
- Manual checks: <!-- dry runs, real-data spot checks -->

## Docs

- [ ] README or package README
- [ ] `development/Changelog.md`, and `development/Problems.md` if a bug was found
- [ ] `development/architecture.md` or `infrastructure.md` if structure or services changed
- [ ] `aq docs sync`, and the vault regenerated
