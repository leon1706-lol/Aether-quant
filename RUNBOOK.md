# Runbook — Operational Procedures

What to do when things go wrong. Each section: **Symptoms → Diagnosis → Resolution**.

## Everyday commands

Assumes the root README's [Getting Started](README.md#getting-started) setup
is done and the venv is active: `.\.venv\Scripts\Activate.ps1`.

```powershell
# Rebuild model artifacts
python train.py                 # full dataset build + train
python train.py --dataset-only  # dataset/scaler/manifest only

# Recommended pre-commit workflow
aq test                         # full suite (never bare pytest from the root, development/Problems.md #8)
aq backtest                     # runs `lean backtest .`, then every run-folder report and the README's Backtest Statistics
aq evaluate --lean-report --backtest-dir backtests/<run>   # the same report for a run made on the DinD Codespace
aq report <backtest-folder> <result-id>   # official Lean HTML report
git status

# Inspect a finished backtest
Get-ChildItem .\backtests\<backtest-folder>\*-summary.json

# Webui (two terminals) -> http://localhost:3002 (Overview) / /risk
uvicorn monitoring.api_server:app --port 8001 --reload
cd webui; npm run dev
```

## Train in the cloud (GitHub Codespaces)

Useful on a memory-constrained machine where a full retrain can take hours of
wall-clock time while barely using any CPU (see `development/Problems.md` #50/#52):

```powershell
gh codespace create --repo <owner>/Aether-quant --branch main --machine basicLinux32gb
gh codespace ssh -c <codespace-name>
# inside the Codespace:
cd Aether-quant && python train.py
# back on your local machine:
gh codespace ssh -c <codespace-name> -- "cd Aether-quant && tar czf /tmp/aether-quant-ml.tgz ml"
gh codespace cp -c <codespace-name> remote:/tmp/aether-quant-ml.tgz .\aether-quant-ml.tgz
tar -xzf .\aether-quant-ml.tgz
gh codespace stop -c <codespace-name>
```

Before training, first sync any local uncommitted source/data changes to the
Codespace; afterward verify the whole extracted `ml/` artifact tree (not just
JSON summaries) before stopping it. Model artifacts are gitignored and the
SSH copy keeps them out of the public repo. Lean backtests run on a *temporary*
Docker-in-Docker Codespace (`scripts/codespace_lean_run.ps1`; see
`development/infrastructure.md`'s "Lean on a DinD Codespace"), never on the training
Codespace and never on the dev PC, whose Docker Desktop does not start; delete the
DinD Codespace as soon as its runs are pulled (AGENTS.md rule 13).

Since V5.6.0 the sync is scripted (`gh codespace cp` upload is broken and `-r` drops files):

```powershell
.\scripts\codespace_sync.ps1 -Mode push       # full tree incl. gitignored data/ and ml/ (no datasets), hash-verified
# on the Codespace: nohup bash scripts/codespace_retrain_a.sh <tag> ; then ..._b.sh <tag> <winner>
.\scripts\codespace_sync.ps1 -Mode pull -Candidate <version ids>
.\scripts\codespace_sync.ps1 -Mode stop
```

The VM reboots about hourly: walk-forward resumes with `--resume-run-id`. See `development/infrastructure.md`.

## Deploy checklist (paper first, V6.0.0)

Run top to bottom; stop at the first red item. Evidence status at V5.8.0: the models carry a weak, unproven rank edge (`development/Problems.md` #169, #172, #174), so **paper trading only, no live capital**, until a paper period shows otherwise.

1. **Freeze:** `aq test` green, `ruff check .` clean, `aq secrets-check` passes, `python scripts/ml_manifest.py` equals the manifest the last Lean run used.
2. **Image:** build it on the deploy host (`aq docker build`, then `aq docker up`) and `GET /api/assets-status` returns 200. The image of record is the one `scripts/codespace_engine_check.sh` builds and health-checks on the DinD Codespace each phase; the dev PC's local image is not a requirement (Problems #214).
3. **Config:** `aq render-lean-config` from `.env.live` (secrets only in the gitignored `lean.live.json`); `phase_v2.runtime.mode` stays `observation` until step 4.
4. **Gate:** `aq paper-readiness` (needs the Postgres observation history and the paper broker config) before flipping the mode to `paper`.
5. **Dashboard (`/api/assets-status`, Operations page):** the forex sleeve shows OFF (V6.0.0, rule R-FX6: `forex_risk.enabled` false), bond momentum sleeve (gross 0.10), crypto graduates (0.5% per name, 2.5% class), RL range [0.9, 1.1] with its shadow guard, the venue listing guard, and every enabled `sleeve_guards.*` entry reading `sleeve_guard_ok`. **Crypto venue:** QuantConnect's Interactive Brokers brokerage does not support crypto (Problems.md #192), so with IB credentials crypto cannot fill live; `aq render-lean-config` warns about it. Crypto exits rest as limit orders (`limit_orders.exit_asset_classes`); check Lean's benchmark follows SPY (`runtime.benchmark_ticker`) in the first backtest's engine log.
6. **Kill switch fields to watch:** rolling Sharpe floor, drawdown velocity, slippage divergence (reference = submit price), the rolling-IC gate state and the spread floor.
7. **First week:** keep `diagnostics.book_history.include_feature_snapshot` on for a few symbols and run `aq evaluate --reconcile-features --symbol X` against a fresh dataset; the regime inputs must match (they are drawdown-free since V5.8.0).

## Paper period protocol (V6.4.0, lead L12, Problems #228)

The paper period is the only out-of-sample test left. Its success is **not** "make money": a fixed-config run is inside the
bands a reference Lean run spans. Pre-registered, before the first paper day:

1. **Freeze:** the shipped `config.json` sha256 (Changelog "Freeze"), the model manifest, `diagnostics.book_history.paper_enabled: true`
   (a bounded book-history record per rebalance; live never logs it), no live capital.
2. **Minimum:** 6 rebalances and 120 trading days; `aq paper-readiness` passed first.
3. **Checklist** (`aq evaluate --paper-check --backtest-dir <paper run folder> --reference-dir <pinned Lean run>`): veto rate, kill-switch
   lock share, strategy gross exposure, fills per rebalance, median / p90 adverse slippage, fee bps per turnover, strategy and T-bill
   P&L per day, daily hit ratio, annualised turnover.
4. **Bands:** the 5-95% range of every contiguous 6-rebalance window of the pinned final Lean run (frozen in Problems #228).
   Success = every metric inside its band. A metric outside is a finding to explain, not a failure to hide; run
   `aq evaluate --reconcile-features --symbol X` in week 1.
5. **Cadence:** weekly check; the verdict is written up (Problems.md + Changelog) before any capital decision.

---

## Incident procedures

---

## 1. Kill switch trips repeatedly (>5× per run)

**Symptoms:** `kill_switch_tripped` events in `aq audit-log`, book locked to `reduce_risk` for most decisions, Sharpe degrading.

```powershell
aq audit-log --verify
aq kill-switch --history
```

**Diagnosis:** check whether trips cluster in a known bad era (Apr–Sep 2019, Dec 2019–Mar 2020) or are spread uniformly. Uniform = threshold too sensitive; clustered = genuine regime loss.

**Resolution:**
- If clustered: no action needed — the system correctly disengaged. Review after run completes.
- If uniform: consider raising `phase_v2.risk.kill_switch.min_rolling_sharpe` (see `config.json` for the current value). Run `aq evaluate --replay-kill-switch` to test candidate thresholds offline first.

---

## 2. Reconciliation breaches

**Symptoms:** `reconciliation_breach` events; positions diverging from intended weights.

```powershell
aq evaluate --reconcile-book-history --replay-hysteresis
```

**Diagnosis:** compare overlap fraction against historical baseline (~50%). A sudden drop suggests a data or execution bug, not model degradation.

**Resolution:** if drift is small (<10%) and stable, it's within normal slippage tolerance. If large and growing, check for missing factor files (`data/reference/`) or stale scaler stats.

---

## 3. Data gaps / missing bars

**Symptoms:** symbols absent from universe snapshot; prediction provenance counter shows high multitask fallback rate.

**Diagnosis:** check `data/equity/*/daily/*.zip` files exist for affected tickers and cover the expected date range.

**Resolution:** re-fetch via `aq fetch <type> --ticker <ticker> --apply`. For crypto, verify the exchange actually listed the pair (BNBUSD/TRXUSD were never on Coinbase).

---

## 4. Sequence model OOM / silent fallback

**Symptoms:** `prediction-provenance: sequence_served=0 multitask_fallback=N` at shutdown.

**Diagnosis:** sequence model OOM'd during tensor construction or wasn't loaded. Check train.log for `_ArrayMemoryError`.

**Resolution:** close Docker Desktop before training (frees ~2GB RAM). On codespace, use CPU-only PyTorch index. The system degrades safely to multitask rank_20d — no action required unless quality degrades measurably.

---

## 5. System losing money for 5+ consecutive days

**Symptoms:** sustained negative daily returns; drawdown approaching total-drawdown limit.

**Diagnosis:**
1. Check kill-switch history: is it tripping? (If yes, it's working.)
2. Run `aq evaluate --rank-book` offline: does the current model still show positive net Sharpe?
3. Compare current IC vs training metrics: has rank_20d IC decayed below 0.02?

**Resolution:**
- Offline eval still positive → live-vs-offline gap widened; check reconciliation for new divergences.
- Offline eval also negative → model degraded; trigger a retrain via codespace.
- Both positive but live losing → execution-side issue; review fills, slippage, fees in order-events log.

---

## 6. A class sleeve is suspended by its loss guard

**Symptoms:** `sleeve_guards.<forex|bond|crypto_graduates>.active` is false and `reason` is not `sleeve_guard_ok`; the sleeve holds no positions.

**Diagnosis:** read `drawdown` and `suspended_until_bar` in `visualization/state.json` (`sleeve_guards`); compare with `phase_v2.sleeve_guards.<sleeve>.max_loss_fraction_nav` and the sleeve's P&L in `aq evaluate --audit-backtest` (P&L by class).

**Resolution:** nothing to do until `suspended_until_bar`; the guard is a hard limit by design. Two suspensions in a row mean the sleeve has no edge: cut its gross budget or disable it (`phase_v2.<sleeve>.enabled`), record the decision in the Changelog.
