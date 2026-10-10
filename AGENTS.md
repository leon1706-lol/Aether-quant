# AGENTS.md — guidance for AI coding agents working in this repository

**Aether Quant**: self-adapting algorithmic trading system on QuantConnect Lean +
PyTorch. An ensemble predicts direction, return magnitude, volatility, and
cross-sectional rank per asset per day, driving a market-neutral long/short book with a
kill switch, position reconciliation, and controlled retraining in front of live
trading. Read this before changing anything.

## Before touching anything

- **[`todo.md`](todo.md)** (repo root) — owner's live planning canvas, current
  objective(s) in plain language. Check first. Not a permanent backlog — it gets
  rewritten/cleared as objectives change, so an empty file isn't "nothing to do": ask,
  or fall back to `development/Changelog.md`'s latest phase for context.
- **Sub-readmes** — every folder has one; read it before editing that folder.
- **`development/*.md`** — structure/plan/known-problems context, read all of them.
- **`Aether-quant-Obsidian-Vault/`** — generated dependency/function graph for
  orientation; can be stale, always verify against source.

## Commands

```powershell
pip install -e .          # register `aq` CLI from source (pyproject.toml)
aq test                   # full suite, refreshes badge   (aq test --risk etc. = subsystem only)
#                         # no --parallel on a low-memory machine: each xdist worker imports torch (OOM-killed a run)
aq evaluate               # offline rank evaluation
aq backtest               # real Lean backtest (Docker, ~1hr+) — owner runs this, never agents
ruff check .              # must be clean before commit
```

## Non-negotiables

1. **Pure, testable modules over `main.py` logic.** `main.py` only runs inside Lean:
   its order-path methods are driven against a minimal `AlgorithmImports` stub
   (`tests/test_main_wiring.py`), but `on_data()` itself is not covered — anything needing
   tests is a pure function importable by both `main.py` and `tests/`.
2. **Nothing is done until verified.** Run `aq test` after every code change (never bare
   `pytest` from root — `development/Problems.md` #8, `tests/README.md`); ruff clean.
   Never commit with a red suite. Debug manually where unit tests don't reach.
3. **Fail safe, degrade gracefully.** Never assume Redis / Postgres / IB is available
   (the suite runs without them). Never let NaN / inf / None pass silently through
   feature pipelines — use `json_safety` helpers and explicit guards.
4. **No secrets** in commits. No `aq backtest` in any automated gate or agent session.
5. **New top-level `.py` module** → add to `pyproject.toml` `py-modules`, then
   `pip install -e .`. A stale editable install breaks `aq` with
   `ModuleNotFoundError` — reinstall after pulling new modules.
6. **Offline/live parity.** Any change to the live trading path (`main.py` signal,
   book, sizing, gates, orders) must reuse the same pure function the offline
   simulator (`evaluation/rank_book_simulator.py`) calls, or ship a parity test proving
   both agree. Live-only logic needs a one-line justification in
   `development/architecture.md`'s Offline/Live Parity Contract.
7. **Evidence comes from the engine log.** Lean teardown/exit claims are checked in
   `backtests/<run>/log.txt` (engine), never only `<id>-log.txt` (algorithm) — #104 was
   wrongly marked clean from the algorithm log.
8. **Every owner-run backtest gets written up** (Problems.md + Changelog.md entry and an
   `aq evaluate --audit-backtest` report) before further work builds on it.
9. **New `config.json` keys default to current behaviour.** Behaviour flips are owner
   decisions, recorded in the Changelog.
10. **`main.py` lives behind Lean's `from AlgorithmImports import *`**, which exports names like `time`
    (`datetime.time`) over any stdlib module of the same name: never `import time` there (use
    `from time import perf_counter as _perf_counter` after the star import). `tests/test_main_ensure_ready_smoke.py`
    runs the real first-bar setup - run it after touching `main.py`'s imports or config reads. And read the
    **engine** log of any backtest, even a crashed one, before calling the failure understood (#132).
11. **Latency-aware.** Hot-path code (`main.py` per-bar, `inference/`) allocates nothing
    new per bar without need, does no per-bar disk I/O, and keeps optional diagnostics
    behind default-off flags. Heavy imports (torch) stay out of Lean startup (#16).
12. **Data parity is checked against live, not against code.** A dataset row sees the bars live would have at that tick
    (`features/cross_asset_timing.py` is the one definition; forex carries Lean's fill-forward calendar), and local `data/` and
    the Codespace's must be file-for-file identical (a push overlays, never deletes — three FRED files once existed only on the
    Codespace). After any feature/dataset change, compare a backtest's `feature_snapshot` with `aq evaluate --reconcile-features`.
    Never run a heavy process (evaluation, tests) during `aq backtest`: `Initialize()` has a hard 90-second limit (#16) and CPU
    contention trips it. CI runs Python 3.11, the dev PC 3.14 (lazy annotations): test with the stub guards, not by intuition.

## Where things live

| Path | What lives here |
|---|---|
| `main.py` | Lean algorithm entry point (order paths stub-tested, `on_data()` not) |
| `risk/` · `portfolio/` · `execution/` | Sizing, kill switch · book construction, HRP, options · order gate, cost model, reconciliation |
| `features/` · `inference/` · `moe/` | Pure feature functions · model loading/batch inference · gating/routing |
| `train.py` · `train_*.py` | Core training loop · specialized trainers |
| `evaluation/` · `retraining/` | Offline eval, Monte Carlo · candidate promotion gates, artifact versioning |
| `experience/` · `audit/` · `monitoring/` · `notifications/` | Redis/Postgres pipeline · hash-chained audit log · FastAPI + dashboards · Telegram |
| `data_pipeline/` · `regime/` · `topology/` | Backfills, bar synthesis · regime detection · topology overlay |
| `json_safety.py` · `performance_probe.py` · `aq_cli.py` | Finite-safe JSON helpers · opt-in timing/teardown probes (stdlib-only) · CLI entry point + subsystem test routing |
| `tests/` · `development/` · `webui/` | pytest suite · docs/Changelog/Problems · React dashboard |

## Conventions

- **One test file per source module.** Cross-module regressions go in round files
  (`test_v543_new_features.py`, `test_rl_sizing_v541.py`, …), committed together with
  their fix — never separately.
- **Register every new test file** in `aq_cli.py`'s `_SUBSYSTEM_TEST_FILES` immediately,
  or subsystem-filtered runs (`aq test --risk`, `--portfolio`, …) silently skip it.
- **Docs move with code:** README + sub-readmes, `development/` (Changelog.md,
  Problems.md, architecture.md, infrastructure.md), `aq --help` for new/changed flags.
- **Problems.md and Changelog.md entries: condensed, not narrated.** Problems: title +
  severity/status marker + **Problem**/**Fix**/**Verification**, each ~1–3 sentences.
  Changelog: `## Phase N — Title` + bold-led bullets, one per unique task/fix, ~2
  sentences each — what changed and why it matters, not file lists or investigation
  narrative. Condense at write time; don't write long and trim later.
- **Problems.md status markers** — update when closing an entry:
  🟢 `fixed` (code changed + verified, nothing pending) ·
  🟡 `partial` (shipped, verification pending: backtest / live deploy / user confirmation) ·
  🔴 `closed` (no code fix: declined / won't-fix / moot / superseded).
- **Comments: short and precise.** Keep a comment only if it tells the reader something
  the code can't — a non-obvious *why*, an invariant, a real gotcha. Delete ones that
  restate the code or narrate process ("found live", "see Problems.md #N"); that history
  belongs in git log / Changelog / Problems.

## Model training

Always train on the Codespace `aq-Training-Ground-Fixed` via the CLI, never locally.
Sync the full local project first (including gitignored files); keep the codespace OFF
when idle; afterwards bring model, data, and extra files back locally for testing.

## CI

`.github/workflows/ci.yml` (Python 3.11): `python-tests` (ubuntu + windows, 80% coverage
gate), `python-lint` (ruff, `py_compile main.py`), `dependency-audit` (pip-audit),
`webui-tests`, `cli-smoke`, `workflows-lint` (actionlint), plus the V5.5.0 guard jobs
(fast-guards, subsystem-matrix, wheel-smoke, python-compat, docker-checks, docs-links,
secret-scan, parity-smoke). `tests/test_ci_workflows.py` pins the shape — update it with
any workflow change. No Lean backtest in CI; the badge is refreshed locally by `aq test`.
Docker rebuild is required before any paper/live deploy once material code changes land.

## Wrap-up checklist

After every code change: tests added → `aq test` + ruff green → docs updated (see
Conventions) → vault regenerated:

```powershell
cd Aether-quant-Obsidian-Vault
python scripts/generate_code_graph.py --repo-root .. --vault .
python scripts/regenerate_vault.py --repo-root .. --vault . --append-handoff \
  --agent ox-alpha --action completed --summary "..." --files file1.py file2.py
```

Then **ask, don't act:** tell the user whether the Docker image needs rebuilding, whether
a git commit should be saved, and whether an `aq backtest` is needed — do none of these
unprompted.
