# Contributing to Aether Quant

Aether Quant is a dynamic, self-adapting algorithmic trading system built on
QuantConnect Lean and PyTorch: an ensemble of neural models predicts
direction, return magnitude, volatility, and cross-sectional rank for every
asset every day, driving a market-neutral long/short book validated
end-to-end inside Lean, with a kill switch, position reconciliation, and
controlled retraining in front of live trading.

## Dev setup

- **Python >= 3.10** (training pipeline, `main.py`'s Lean algorithm,
  FastAPI monitoring server, `aq` CLI).
- From a clone with a virtual environment active:

  ```powershell
  pip install -e .
  ```

  This registers the `aq` command from source (`pyproject.toml`).
- **Docker Desktop is only needed for real backtests** (`aq backtest`, which
  shells out to `lean backtest .`). The first run downloads the pinned Lean
  engine image (~40GB+); budget time and bandwidth for it. Everything else —
  the test suite, offline evaluation (`aq evaluate`), profiling, training —
  runs without Docker or Lean.
- Optional extras: Node.js for the `webui/` dashboard, Docker Compose for
  the Redis/Postgres infrastructure workers (see
  `development/infrastructure.md`).

## Running tests

```powershell
aq test
```

That is plain pytest excluding the `lean_backtest` marker (~2700 tests);
it also refreshes the pass-count badge at the top of `README.md`. Never
commit changes that break the full suite.

Two known traps:

1. **Register every new test file** in `aq_cli.py`'s
   `_SUBSYSTEM_TEST_FILES`. A file missing from its bucket is silently
   skipped by every filtered subsystem run (`aq test --risk`,
   `--portfolio`, ...). A coverage-completeness regression guard exists in
   `tests/test_aq_cli.py`, but register the file when you create it rather
   than relying on catching the failure late.
2. Run tests as `pytest tests/` (or via `aq test`), never bare `pytest`
   from the root — see `development/Problems.md` #8 and `tests/README.md`.

Real Lean backtests take over an hour and need Docker Desktop plus a local
data folder; they are run manually by the maintainer, not in CI or PRs.
Do not block a PR on one.

## Code conventions

- **Pure, testable modules over `main.py` logic.** `main.py` has zero unit
  test coverage by design — it only ever runs inside Lean. Anything that
  needs tests must be a pure function in a package module importable by
  both `main.py` and `tests/`.
- **Additive `None`-default parameters** when extending log/config surfaces:
  new parameters default to `None` and degrade to previous behavior when
  absent, so existing callers and configs reproduce pre-change behavior
  exactly.
- **Config flags default off until verified.** New behavior goes behind a
  `phase_v2.*` flag set to `false` until validated against real data or a
  real backtest; flipping it on is a separate, deliberate step.
- **Fail-open sentinel conventions**: missing values degrade to safe
  sentinels instead of raising. Follow the neighboring code in the module
  you are touching.

## Documentation discipline

Every functional change updates:

1. `README.md` and/or the relevant sub-package README — docs are part of
   the change here, not an afterthought.
2. `development/Changelog.md` — what shipped, when, and why. **Append-only**
   historical record: past entries describe what was true at the time and
   are never rewritten.
3. `development/Problems.md` — append-only audit log of bugs and issues,
   each with a severity rating and fixed/open status. Add an entry for
   every bug found.
4. `development/architecture.md` / `development/infrastructure.md` when the
   change touches system architecture or the Docker/service layout.
5. After code changes, regenerate the Obsidian vault mirror:
   run `Aether-quant-Obsidian-Vault/scripts/generate_code_graph.py`, then
   `regenerate_vault.py` with `--append-handoff`.

## Commit style

Match existing history: a version prefix plus a short description of what
shipped and why, e.g.

```text
V5.3.6 Fixing the forex order-sizing bug and closing the live-vs-offline gap
```

## Versioning (SemVer) and deprecation policy

Releases are tagged `vMAJOR.MINOR.PATCH` and follow [Semantic
Versioning](https://semver.org/) adapted to this project's reality:

- **MAJOR** — anything that can silently change results or break an
  existing setup: config schema removals/rename, CLI flag or output-format
  breaks (`aq` command surface, JSON artifact shapes), log record field
  changes in `book_history.jsonl`/audit streams, model artifact contract
  changes requiring retraining to keep working, Python version floor bumps.
- **MINOR** — new subsystems, modules, or features shipped backward-
  compatibly (the repo's established convention: additive `None`-default
  parameters, new `phase_v2.*` flags defaulting to `false`). A MINOR bump
  never changes behavior for an unmodified `config.json`.
- **PATCH** — bug fixes, diagnostics, docs, test-only changes. No behavior
  change beyond fixing what was broken.
- Fourth components (e.g. `v5.3.5.3`) are tolerated for follow-up patch
  rounds within the same MINOR; treat them as PATCH-level.

Historical note: pre-2026-08 versions were numbered loosely (`V5.2.x`
carried feature work). Semver applies strictly from now on.

**Deprecation policy:**

1. Nothing user-visible is removed silently. A deprecated config key, CLI
   flag, JSON artifact field, or log record field keeps working exactly as
   before and emits a warning (CLI stderr / `self.Debug()` inside Lean).
2. Deprecations are announced in the release notes AND get a
   `development/Problems.md`-referenced entry in `development/Changelog.md`
   stating what replaces them.
3. Deprecated surfaces are removed no earlier than the next MAJOR release,
   and only after at least one full MINOR cycle with the warning in place.
   Exceptions require an explicit maintainer decision documented in the
   changelog entry that removes it.
4. Internal functions/modules (anything under `tests/`, private helpers)
   may be refactored away in any release — this policy covers only
   surfaces a user or integrator can observe.

## Releases (GitHub Releases + changelog per tag)

Releasing is a manual, deliberate act: push a tag `vX.Y.Z` on `main`. The
existing `release.yml` workflow then publishes PyPI + GHCR Docker images
and additionally creates a **GitHub Release** for the tag whose notes link
the matching `development/Changelog.md` entry plus auto-generated commit
notes. To make a release:

1. Finish the round's `development/Changelog.md` entry with a header whose
   version matches the tag (e.g. tag `v5.3.6` ↔ header `## V5.3.6 ...`).
2. Tag and push: `git tag v5.3.6 && git push origin v5.3.6`.
3. The workflow builds everything; check the Actions run and the resulting
   GitHub Release page. If the Changelog section is missing, the release
   still publishes but its body says so — don't let that ship.

## License

The project is licensed under PolyForm Noncommercial 1.0.0. Contributions
are licensed under the same terms: by opening a PR you agree that your
contribution may be used non-commercially only.


## CI expectations

CI runs the full offline suite (both Ubuntu and Windows) with an 80%
coverage fail-under gate, `ruff check .`, the complete vitest frontend
suite, a CLI smoke battery, and actionlint. A red CI job means "do not
merge as-is" even when your local run was green - platform variance is
exactly what these extra runners exist to catch. Tag-push releases run one
extra NON-BLOCKING visibility job (`tag-tests`) so gaps show up next to the
release without failing it.
