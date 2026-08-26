# Aether Quant — Agent Instructions

## What this project is

Aether Quant is a dynamic, self-adapting algorithmic trading system built on
QuantConnect Lean and PyTorch. An ensemble of neural models predicts direction,
return magnitude, volatility, and cross-sectional rank for every asset every
day, driving a market-neutral long/short book validated end-to-end inside Lean,
with a kill switch, position reconciliation, and controlled retraining in front
of live trading.

## Essential commands

```powershell
pip install -e .          # register `aq` CLI from source (pyproject.toml)
aq test                   # full pytest suite (~2929 tests), refreshes badge
aq test --risk            # risk subsystem only (subsystem filtered)
aq evaluate               # offline rank evaluation
aq backtest               # real Lean backtest (requires Docker, ~1hr+)
ruff check .              # linter (must pass before commit)
```

## File layout

| Path | What lives here |
|---|---|
| `main.py` | Lean algorithm entry point — **zero unit test coverage by design**, only runs inside Lean |
| `risk/` | Position sizing, portfolio slicing, kill switch, correlation |
| `portfolio/` | Book construction, book neutrality, HRP, risk parity, options strategies |
| `execution/` | Order gate, cost model, reconciliation |
| `features/` | Pure feature functions (technical, macro, alt data, options greeks) |
| `inference/` | Model loading, exported model reader, batch inference |
| `moe/` | Mixture-of-experts gating and routing |
| `train.py` | Core training loop (dataset, ranking losses, walk-forward, export) |
| `train_*.py` | Specialized trainers (multitask, sequence, gating, topology, strategy selector) |
| `evaluation/` | Offline evaluation: rank book simulator, Monte Carlo, calibration tools |
| `retraining/` | Candidate promotion: validation gate, backtest gate, artifact versioning |
| `experience/` | Experience pipeline: Redis queue, Postgres worker, session summaries |
| `audit/` | Tamper-evident audit log (hash-chained) |
| `monitoring/` | FastAPI server, neural network state, evaluation state, Grafana dashboards |
| `notifications/` | Telegram alerts (pure/format/worker split) |
| `data_pipeline/` | Yahoo backfill, FRED backfill, bar synthesis, fetching |
| `regime/` | Market regime detection |
| `topology/` | Market topology overlay |
| `json_safety.py` | Shared JSON-safety helpers (finite-safe, atomic writes) |
| `aq_cli.py` | CLI entry point: all `aq` subcommands, subsystem test routing |
| `tests/` | pytest suite — one file per module, round files for cross-module regressions |
| `development/` | Architecture docs, Changelog, Problems.md, backups |
| `webui/` | React dashboard (TypeScript) |

## Code conventions

- **Pure, testable modules over `main.py` logic.** Anything needing tests must
  be a pure function importable by both `main.py` and `tests/`.
- **One test file per source module.** Cross-module regressions go in round
  files: `test_v543_new_features.py`, `test_rl_sizing_v541.py`, etc.
- **Register every new test file** in `aq_cli.py`'s `_SUBSYSTEM_TEST_FILES`
  dict immediately when you create it — otherwise it is silently skipped by
  subsystem-filtered runs (`aq test --risk`, `--portfolio`, etc.).
- **Never commit changes that break the full test suite.** Run `aq test` after
  every code change; ruff must also be clean.
- **Round files at the same commit as their fixes.** Test + fix together, never
  separately.
- **`aq test` only, never bare `pytest` from root** — see `development/Problems.md`
  #8 and `tests/README.md`.

## Code context

- **README + sub-readmes:** every folder has a short sub-readme for introduction
  and overview. Always read the relevant sub-readme before editing a module.
- **`development/` folder:** read every `.md` file — they hold important context
  for project structure, plan, and known problems.
- **Obsidian vault** (`Aether-quant-Obsidian-Vault`): generated graph of all
  dependencies and functions. Use for general overview, but always verify
  against source — it can be outdated.

## Verification tasks

After every code change, complete ALL of the following:

1. **Add tests** for everything you added/changed.
2. **Run them** (`aq test` — no Lean backtest in the test suite) and debug if
   needed. Also do manual debugging where unit tests don't cover.
3. **Update documentation:**
   - README.md + sub-readmes (if module docs changed)
   - Test suite badge (`aq test` auto-refreshes)
   - `development/` folder: Problems.md, Changelog.md, architecture.md,
     infrastructure.md
   - `aq --help` surfaces if new/changed flags
4. **AQ Vault:** run `generate_code_graph.py` + `regenerate_vault.py
   --append-handoff` (see Vault section below).
5. **Report to user:** say whether Docker image should be updated and/or git
   commit saved. Say if `aq backtest` is needed — user runs backtests
   themselves, never run them in the agent session.

## Model training

- **Always train models on the Codespace**, not locally. Use the CLI.
- **Sync codespace with local project** including all gitignored and normal
  files before training.
- **Training codespace:** `aq-Training-Ground-Fixed` — keep it OFF when not in
  active use to reduce costs.
- **After training finishes:** bring the entire model, data, and any extra files
  back to the local machine for testing.

## Problems.md status markers

Every entry in `development/Problems.md` uses the established color scheme:

| Marker | Meaning |
|--------|---------|
| 🟢 `fixed` | Code changed + verified, nothing pending |
| 🟡 `partial` | Fix shipped but verification incomplete (needs backtest, live deploy, or user confirmation) |
| 🔴 `closed` | No code fix: declined/won't-fix/moot/superseded |

Always update the status marker when closing a problem entry.

## CI (`.github/workflows/ci.yml`)

Single job: checkout → setup-python 3.10 → install → ruff → `aq test` → badge refresh.
No Docker/Lean backtests in CI. Docker rebuild is required before any paper/live
deploy whenever material code changes land.

## Vault (Aether-quant-Obsidian-Vault)

The Obsidian vault tracks code graphs and agent handoffs:

```powershell
cd Aether-quant-Obsidian-Vault
python scripts/generate_code_graph.py --repo-root .. --vault .
python scripts/regenerate_vault.py --repo-root .. --vault . --append-handoff \
  --agent ox-alpha --action completed --summary "..." --files file1.py file2.py
```

## Don'ts

- Never commit secrets, API keys, or credentials
- Never run `aq backtest` as part of an automated PR gate
- Never add new top-level `.py` modules without updating `pyproject.toml`
  `py-modules` and re-installing with `pip install -e .`
- Never let NaN / inf / None silently pass through feature pipelines — use
  `json_safety` helpers and explicit guards
- Never assume a Redis / Postgres / IB connection is available — always
  degrade gracefully (the test suite runs without any of them)
