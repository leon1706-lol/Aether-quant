# Contributing to Aether Quant

A self-adapting trading system on QuantConnect Lean and PyTorch, and a library for building other algorithms. Agents should also read [`AGENTS.md`](AGENTS.md).

## Setup

```powershell
pip install -r requirements/requirements-dev.txt
pip install -e .     # registers the `aq` command
```

- **Python <!--fact:python.ci-->3.11<!--/fact-->** is what CI runs.
- **Docker** is only needed for real backtests. The first run downloads the Lean engine image (about 40 GB). Tests, `aq evaluate` and profiling run without it.
- **Optional:** Node.js for `webui/`; Docker Compose for Redis and Postgres.

## Tests

```powershell
aq test          # the suite, and it refreshes the README badge
```

- **Never commit a red suite**, and keep `ruff check .` clean.
- **Register every new test file** in `aq_cli.py`'s `_SUBSYSTEM_TEST_FILES`, or filtered runs skip it.
- **Don't run bare `pytest` from the root** (#8, `tests/README.md`).
- **Real Lean backtests** are run by the maintainer. Don't block a PR on one.

CI runs the suite on Ubuntu and Windows with an 80% coverage gate, plus ruff, the frontend tests, a CLI smoke battery, actionlint and guard jobs. A red job means don't merge, even if your local run was green.

## Code conventions

- **Pure, testable modules over `main.py` logic.** `main.py` only runs inside Lean, so anything that needs tests is a pure function both it and `tests/` can import.
- **New config keys default to current behaviour.** New behaviour goes behind a `phase_v2.*` flag, and flipping it is a separate decision.
- **New parameters default to `None`** and fall back to the previous behaviour.
- **Fail safe.** Missing values degrade to safe sentinels. Never assume Redis, Postgres or a broker is available.

## Documentation

Docs move with code:

- Update `README.md` and the package README.
- Add `development/Changelog.md` and `development/Problems.md` entries: condensed, and past entries aren't rewritten to match later changes.
- Update `development/architecture.md` or `infrastructure.md` when the design or services change.
- Quote numbers through `<!--fact:key-->` markers (`docs_facts.py`, `aq docs sync`), so they can't go stale.
- Regenerate the Obsidian vault, per AGENTS.md's wrap-up checklist.

## Commits

A version prefix and what shipped: `V6.6.2 Condense the docs and recapture the statistics`.

## Versioning

Tags are `vMAJOR.MINOR.PATCH`:

- **MAJOR:** anything that can silently change results or break a setup, such as config removals, CLI or JSON output breaks, or a model contract needing a retrain.
- **MINOR:** new features, backward compatible. Never changes behaviour for an unmodified `config.json`.
- **PATCH:** fixes, diagnostics, docs and tests.

**Deprecation:** nothing user-visible disappears silently. A deprecated key, flag or field keeps working, warns, is announced in the Changelog, and goes no earlier than the next MAJOR. Internal helpers can change in any release.

## Releases

Push a tag `vX.Y.Z` on `main` after writing its Changelog entry. `release.yml` tests, then publishes to PyPI, GHCR and GitHub Releases. See the README's [Release Process](README.md#release-process).

## License

PolyForm Noncommercial 1.0.0. By opening a PR you agree your contribution may be used under the same terms.
