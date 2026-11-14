# Contributing to Aether Quant

A self-adapting trading system on QuantConnect Lean and PyTorch, and a library for building other algorithms. Agents should also read [`AGENTS.md`](AGENTS.md).

## Setup

```powershell
pip install -r requirements/requirements-dev.txt
pip install -e .     # registers the `aq` command
```

To use only the library, `pip install -e .` pulls only numpy and pandas; `.[research]`, `.[notebooks]`, `.[docs]` and `.[full]` add the rest. `tests/test_lite_install.py` keeps the light install importable.

- **Python <!--fact:python.ci-->3.11<!--/fact-->** is what CI runs.
- **Docker** is only needed for real backtests. The first run downloads the Lean engine image (about 40 GB). Tests, `aq evaluate` and profiling run without it.
- **Optional:** Node.js for `webui/`; Docker Compose for Redis and Postgres.

## Tests

```powershell
aq test          # the suite, and it refreshes the README badge
```

- **Never commit a red suite**, and keep `ruff check .` clean. `aq verify --quick` runs what fits a small machine; [`development/verification.md`](development/verification.md) lists every other check and when it is required.
- **Keep the library current:** a new public function or class goes in `aether_quant` or is listed with a reason in `tests/data/aether_quant_unexported.json`. `python scripts/install_hooks.py` installs the pre-commit hook that checks this, and CI's fast-guards repeat it.
- **Before handing over a commit:** `scripts/clean_checkout_test.ps1` (CI has no gitignored files), or `scripts/codespace_verify.ps1 -Start` on a low-memory PC.
- **Register every new test file** in `aq_cli.py`'s `_SUBSYSTEM_TEST_FILES`, or filtered runs skip it.
- **Run `aq test`, or `pytest` from the root** so `testpaths` applies; never `pytest .` (#8, `tests/README.md`).
- **Real Lean backtests** are run by the maintainer. Don't block a PR on one.
- **Docs and notebooks:** `python scripts/build_docs.py` then `mkdocs build --strict` (`pip install -r requirements/requirements-docs.txt`); notebooks are edited in `notebooks/src/*.py` and rebuilt with `python scripts/build_notebooks.py --execute`.

CI runs the suite on Ubuntu and Windows with a 100% coverage gate over every tracked module (`aq test --coverage` checks it locally), plus ruff, the frontend tests, a CLI smoke battery, actionlint and guard jobs. A red job means don't merge, even if your local run was green.

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

Two licenses, mapped path by path in [`LICENSE`](LICENSE) and [`REUSE.toml`](REUSE.toml):

- **Apache-2.0:** the library, i.e. everything the wheel and the dashboard image ship, plus `webui/`, `notebooks/`, `docs/`, `examples/` and `formal/`.
- **PolyForm Noncommercial 1.0.0:** the trading system, including `main.py`, the trainers, `ml/`, `config.json`, `scripts/` and the research records.

Inbound equals outbound: a contribution is licensed under the license of the path it changes. A new file takes the license its path matches in `REUSE.toml`, and `tests/test_licensing.py` checks the wheel.
