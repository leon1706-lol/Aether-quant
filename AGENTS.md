# AGENTS.md: guidance for AI coding agents

**Aether Quant** is a self-adapting trading system on QuantConnect Lean and PyTorch, and a toolkit (`aether_quant`, `aq`) for building other algorithms. The shipped book is a long-only crypto trend sleeve, on paper, with no verified edge. A model stack, research cycle, kill switch, reconciliation and controlled retraining surround it. Read this before changing anything.

## Before touching anything

- **[`todo.md`](todo.md):** the owner's current objectives. Check it first. It gets rewritten, so if it's empty, ask, or read `development/Changelog.md`'s latest phase.
- **Sub-readmes:** every folder has one; read it before editing that folder.
- **`development/*.md`:** structure and problems context.
- **`Aether-quant-Obsidian-Vault/`:** a generated code graph for orientation. It can be stale, so verify against source.

## Commands

```powershell
pip install -e .          # register `aq` from source (pyproject.toml)
aq test                   # full suite, refreshes the badge and doc facts (aq test --risk etc. = one subsystem)
#                         # no --parallel on a low-memory machine: each xdist worker imports torch
aq evaluate               # offline evaluation
aq cycle status           # generations, shares, decay, what is due (RUNBOOK "Research cycle")
aq docs sync              # refresh numbers quoted in the docs
aq backtest               # real Lean backtest (Docker, ~1hr+): the owner runs this, never agents
ruff check .              # must be clean before commit
```

## Non-negotiables

1. **Pure, testable modules over `main.py` logic.** `main.py` only runs inside Lean: its order paths are stub-tested (`tests/test_main_wiring.py`), but `on_data()` isn't. Anything needing tests is a pure function both `main.py` and `tests/` can import.
2. **Nothing is done until verified.** Run `aq test` after every code change (never bare `pytest` from the root, #8), with ruff clean. Never commit a red suite.
3. **Fail safe, degrade gracefully.** Never assume Redis, Postgres or IB is available. Never let NaN, inf or None pass silently through feature pipelines: use `json_safety` helpers and explicit guards.
4. **No secrets in commits. No `aq backtest` in any automated gate or agent session.**
5. **New top-level `.py` module:** add it to `pyproject.toml` `py-modules` (or, if `aq` never imports it, to `INTENTIONALLY_NOT_SHIPPED` in `tests/test_packaging_modules.py`), then `pip install -e .`. A stale editable install breaks `aq` with `ModuleNotFoundError`.
6. **Offline/live parity.** Any change to the live path (`main.py` signal, book, sizing, gates, orders) reuses the pure function the offline simulator calls, or ships a parity test. Live-only logic needs a one-line justification in `development/architecture.md`'s Offline/Live Parity Contract.
7. **Evidence comes from the engine log.** Lean teardown claims are checked in `backtests/<run>/log.txt`, never only `<id>-log.txt` (#104).
8. **Every owner-run backtest gets written up** (Problems.md, Changelog.md, `aq evaluate --lean-report`) before further work builds on it.
9. **New `config.json` keys default to current behaviour.** Behaviour flips are owner decisions, recorded in the Changelog.
10. **`main.py` lives behind Lean's `from AlgorithmImports import *`,** which exports `time` (`datetime.time`) and `Exception` (.NET's, which no Python error matches, #276). Never `import time` there (use `from time import perf_counter as _perf_counter` after the star import), and keep `from builtins import Exception`. Run `tests/test_main_ensure_ready_smoke.py` after touching its imports or config reads. Read the **engine** log of any backtest before calling a failure understood (#132).
11. **Latency-aware.** Hot-path code (`main.py` per-bar, `inference/`) allocates nothing new per bar without need, does no per-bar disk I/O, and keeps diagnostics behind default-off flags. Heavy imports stay out of Lean startup (#16).
12. **Data parity is checked against live, not against code.** A dataset row sees the bars live would have at that tick (`features/cross_asset_timing.py`), and local `data/` and the Codespace's must be file-for-file identical (a push overlays, never deletes). After any feature or dataset change, compare a backtest's `feature_snapshot` with `aq evaluate --reconcile-features`. Don't run a heavy process during `aq backtest` on the PC: `import main` runs under `algorithm-creation-timeout`. CI runs Python 3.11, the dev PC 3.14, the Codespaces pandas 3: test with the stub guards, not by intuition.
13. **Codespaces bill the owner's budget: on only while a job runs.**
    - Run `gh codespace list` at the start and end of every session, and stop anything idle.
    - Anything that fits on the dev PC runs locally. Create every Codespace with `--idle-timeout 30m`.
    - The training Codespace is started for one job and stopped once results are pulled.
    - A Lean DinD Codespace bundles every Lean run of a phase into one lifetime, then `gh codespace delete` in the same session (its ~20 GB image is billed storage).
    - Record on and off times in the phase's Changelog "Hosts" bullet.

## Where things live

| Path | What lives here |
|---|---|
| `main.py` | Lean algorithm entry point |
| `risk/` · `portfolio/` · `execution/` | Sizing, kill switch · target weights, book construction, HRP, options · order gate, cost model, reconciliation |
| `features/` · `inference/` · `moe/` | Pure features · model loading and batch inference · gating |
| `train.py` · `train_*.py` | Training loop · specialized trainers |
| `evaluation/` · `retraining/` | Offline eval, research rounds, generations' registry and ledger · candidate gates, versioning |
| `ml/generations/` | Generations, glide policy, lifecycle log, the once-only holdout ledger (tracked; nothing in Lean reads it) |
| `aether_quant/` | The library, pinned by `tests/data/aether_quant_api.json` |
| `experience/` · `audit/` · `monitoring/` · `notifications/` | Redis and Postgres pipeline · hash-chained audit log · FastAPI · Telegram |
| `data_pipeline/` · `regime/` · `topology/` | Backfills · regime detection · topology overlay |
| `docs_facts.py` · `json_safety.py` · `performance_probe.py` · `aq_cli.py` | Doc facts · finite-safe JSON · opt-in probes · the CLI |
| `tests/` · `development/` · `webui/` | The suite · docs and logs · React dashboard |

## Conventions

- **One test file per source module.** Cross-module regressions go in round files (`test_v660_fixes.py`), committed with their fix.
- **Register every new test file** in `aq_cli.py`'s `_SUBSYSTEM_TEST_FILES`, or subsystem runs silently skip it.
- **Docs move with code:** README and sub-readmes, `development/`, `aq --help` for new flags.
- **Numbers in docs are facts, not text.** A count, window or version goes through `<!--fact:key-->` (`docs_facts.py`) or a generated `AQ:*` block. `tests/test_docs_facts.py` also fails on a path, `phase_v2` key, `aq` command or problem number that no longer exists in a living doc.
- **The README's Backtest Statistics shows the shipped book only.** The retired book's blocks live in `development/research_results.md`.
- **Problems.md and Changelog.md entries are condensed.**
  - Problems: `### N. Title`, then a status and severity line, then **Problem:** / **Fix:** / **Verification:**, each 1-3 sentences.
  - Changelog: `## Phase N — Title`, then one bold-led bullet per fix, about 2 sentences: what changed and why.
  - A condensing pass snapshots to `development/backups/` first.
- **Problems.md status markers:** 🟢 `fixed` (changed and verified) · 🟡 `partial` (shipped, verification pending) · 🔴 `closed` (no code fix: declined, moot, superseded).
- **Comments: short and precise.** Keep one only if it says what the code can't: a non-obvious why, an invariant, a gotcha. Process history belongs in git log, Changelog and Problems.

## Model training

Train on the Codespace `aq-Training-Ground-Fixed` through the CLI, or locally only on a host that passes `aq cycle retrain`'s RAM preflight (14 GB; `--smoke` proves the plumbing anywhere). Sync the full local project first, including gitignored files; bring model, data and extra files back afterwards.

Lean backtests run on a temporary DinD Codespace (`scripts/codespace_lean_run.ps1`, `development/infrastructure.md`). Delete it when its runs are pulled.

## CI

`forward-ledger.yml` and `research-cycle.yml` run each session on free runners and write only to branch `forward-ledger`.

`.github/workflows/ci.yml` (Python 3.11): `python-tests` (ubuntu and windows, 80% coverage gate), `python-lint`, `dependency-audit`, `webui-tests`, `cli-smoke`, `workflows-lint`, and the guard jobs: fast-guards, subsystem-matrix, wheel-smoke, python-compat, docker-checks, secret-scan, parity-smoke, test-count-drift. `tests/test_ci_workflows.py` pins the shape: update it with any workflow change. No Lean backtest in CI. A Docker rebuild is required before any paper or live deploy once material code lands.

## Wrap-up checklist

After every code change: tests added, `aq test` and ruff green, docs updated, `aq docs sync`, vault regenerated. Before handing over a commit, also run `scripts/clean_checkout_test.ps1` (CI has no gitignored files), or on the 4 GB dev PC `scripts/codespace_verify.ps1 -Start`, which runs every CI job on a Codespace.

```powershell
cd Aether-quant-Obsidian-Vault
python scripts/generate_code_graph.py --repo-root .. --vault .
python scripts/regenerate_vault.py --repo-root .. --vault . --append-handoff --agent ox-alpha --action completed --summary "..." --files file1.py file2.py
```

Then **ask, don't act:** tell the user whether the Docker image needs rebuilding, whether a commit should be saved, and whether an `aq backtest` is needed. Do none of these unprompted.
