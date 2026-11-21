# Contributing to Aether Quant

How to get the project, report a problem and send a change. Agents should also read [`AGENTS.md`](AGENTS.md).

## Get it, give feedback, contribute

- **Get it:** `pip install aether-quant` for the library and `aq hello` (numpy and pandas only), or clone the repository and follow Setup below for the whole system. Releases and their signed files are on the [releases page](https://github.com/leon1706-lol/Aether-quant/releases).
- **Report a bug or ask for a feature:** open an [issue](https://github.com/leon1706-lol/Aether-quant/issues/new/choose). The bug-report template asks for the version, the steps and the output.
- **Report a security problem** privately instead, as [`SECURITY.md`](SECURITY.md) describes.
- **Contribute code or docs:**
  1. Fork the repository and branch from `main`.
  2. Make the change with its tests.
  3. Open a pull request. The [pull-request template](.github/PULL_REQUEST_TEMPLATE.md) lists what to check.
- **What a pull request needs:** `main` is protected, so green CI and a review from the maintainer. CI fails under 100% coverage, on a ruff finding, or on an unpinned install (see Tests and Code conventions below).

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
aq doctor                      # is this machine set up (Python, editable install, hook, git, gh, RAM)?
aq scaffold module risk/x.py   # a new module with its registered test file
aq test --impacted --watch     # the tests of what you changed, rerun on every save
aq check                       # the pre-commit hook's gates, without committing
aq commit -m "..."             # commit through the hook
aq test                        # the suite, and it refreshes the README badge
```

- **Never commit a red suite**, and keep `ruff check .` clean. `aq verify --quick` runs what fits a small machine; [`development/verification.md`](development/verification.md) lists every other check and when it is required.
- **Keep the library current:** a new public function or class goes in `aether_quant` or is listed with a reason in `tests/data/aether_quant_unexported.json`. `aq hooks install` installs the pre-commit hook that checks this, and CI's fast-guards repeat it.
- **Before handing over a commit:** `scripts/clean_checkout_test.ps1` (CI has no gitignored files), or `scripts/codespace_verify.ps1 -Start` on a low-memory PC.
- **Register every new test file** in `aq_cli.py`'s `_SUBSYSTEM_TEST_FILES`, or filtered runs skip it.
- **Run `aq test`, or `pytest` from the root** so `testpaths` applies; never `pytest .` (#8, `tests/README.md`).
- **Real Lean backtests** are run by the maintainer. Don't block a PR on one.
- **Docs site:** `python scripts/build_docs.py`, then `mkdocs build --strict` (`pip install -r requirements/requirements-docs.txt`).
- **Notebooks:** edit `notebooks/src/*.py` and rebuild with `python scripts/build_notebooks.py --execute`.
- **What CI runs:** the suite on Ubuntu and Windows with a 100% coverage gate over every tracked module (`aq test --coverage` checks it locally), plus ruff, the frontend tests, a CLI smoke battery, actionlint and guard jobs. A red job means don't merge, even if your local run was green.

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

Two licenses, by path: Apache-2.0 for the library and AGPL-3.0 for the trading system. [`LICENSING.md`](LICENSING.md) holds the map, [`REUSE.toml`](REUSE.toml) states it file by file, and [`LICENSE`](LICENSE) is the AGPL-3.0.

- **Inbound equals outbound:** a contribution is licensed under the license of the path it changes.
- **A new file** takes the license its path matches in `REUSE.toml`; `tests/test_licensing.py` checks the wheel.
