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

## Forward check, no IB needed (V6.5.0)

V6.5.0 froze `data/` at 2026-11-02, so every session after it was unseen by every rule of that phase. It is the only test nothing has been
fitted on. Any time:

1. Append the data: `python scripts/data_append_refresh.py --apply`, then `python scripts/data_append_guard.py verify ...` (no stored row may change).
2. Extend the weights by the frozen rule, in a copy, since the pinned file ends at its last decision: `python scripts/extend_frozen_weights.py --definition <frozen> --source ml/target_weights.csv --out <copy> --end <new last session>`. Rerun the pinned config on a DinD Codespace with that copy's path and printed sha, its window ending at the new last session (`runtime.lean_window_override`).
3. `aq evaluate --alpha-proof --backtest-dir backtests/<rerun>` reports these sessions as `fresh`. `forward_judgeable` turns true at 60 equity sessions; before that, read nothing into it.

A new config restarts this clock. A rerun is not a paper run: it proves the signal on new prices, not IB's fills, margin or live data.

## Forward ledger (V6.6.0)

`.github/workflows/forward-ledger.yml` appends one hash-chained row a session to the orphan branch `forward-ledger`, at 22:30 UTC on weekdays, for each frozen rule in `ml/forward/candidates.json`. GitHub's commit dates and the chain together show a decision came before its return, which no later rerun can.

- **Read it:** `aq evaluate --forward-ledger` verifies the chain (exit 1 if broken) and reports each candidate's sessions, Sharpe and alpha t. Judge at 60 and 252 sessions; `minimum_detectable_alpha_sharpe_at_t2` says what the sample can show.
- **Check it's alive:** GitHub disables a schedule after 60 days without repo activity. The report warns once the last row is over 3 sessions old. Re-enable with `gh workflow enable forward-ledger.yml`, then `gh workflow run forward-ledger.yml`; a missed session can't be backfilled, and that is the point.
- **`no_data` rows:** a blocked price source or a candidate needing a model is recorded with its reason. A candidate with `needs` set writes `no_data` on the runner by design: run its row from the PC with `python scripts/forward_ledger.py --ledger <worktree of the branch>/forward/ledger.jsonl`.
- **Changing a rule starts a new record:** every row carries the rule's `definition_sha256`. Never edit a candidate in place.
- **What it publishes:** the frozen sleeves' daily weights, on a public branch.

## Research cycle (V6.6.1)

The project's loop: research a pre-registered round -> freeze one candidate -> read the holdouts once -> shadow on the forward ledger -> ramp on the paper book -> decay -> retire. Evidence moves a generation; nothing else does. `aq cycle status` says what is due today.

| Step | How | Where |
|---|---|---|
| Every session | `.github/workflows/research-cycle.yml` appends each generation's return and state and the capital they share to `forward/generations.jsonl` on branch `forward-ledger` | GitHub, free |
| A generation that needs fundamentals or a model | `aq cycle decide --generation G --weights <csv> --ledger-file <worktree>/forward/decisions.jsonl --session D`, then push the branch before the next open | a host with the data |
| Weekly | `aq cycle status` (writes `ml/generations/status.json`, read by `GET /api/generations` and the Operations page) | anywhere |
| A new idea | Write a round file, `aq cycle research rules --round <file> --draft <json>`, record it with `scripts/vault_record.py`, then `score`, `placebo`, `gate`, `pbo`, `report`. A survivor: `freeze`, `hold`, then R-LEAN21 and R-EDGE2 | the training Codespace, or a machine with the RAM |
| Retrain | `aq cycle retrain --host codespace --procedure k06`. A refit of a frozen procedure is a new vintage of its generation; a new procedure goes through a round | see below |
| Stage change | `aq cycle promote --generation G --to ramping`. It refuses anything R-ADMIT1 doesn't allow, and retiring is always allowed | anywhere |
| Blended file for a paper run | `python scripts/daily_target_weights.py --generations <worktree>/forward/generations.jsonl --out ml/generations/blended_weights.csv` before each open | the paper host |

**R-ADMIT1 (owner, 2026-11-06).** A full R-EDGE2 pass ramps at once. Selection plus one R-HOLD1 pass, or once the holdouts are spent selection plus 252 forward sessions, goes to shadow, and may hold up to 30% of the paper book after 60 ok forward sessions without losing to the incumbent. A zero-alpha candidate passes that test about half the time; only the cap bounds a false pass, so it lifts only on forward alpha t >= 2 at 252, 504 or 756 sessions. Anything less holds nothing. Real money is only ever the owner's manual action.

**Two ways to move capital** (`glide.mode` in `ml/generations/policy.json`; which one is set is R-GLIDE2's result, `ml/generations/glide2_policy.json`).

- **`ladder`:** a ramping generation enters at `entry_share` and gains capital at a fixed rate; older ones give it up in proportion to what they hold: 70/30, 64/36, ... 0/100. One gains at a time.
- **`dynamic`:** each generation's share comes from its own record, and up to `max_generations` hold capital at once. Its score is its exponentially weighted Sharpe shrunk toward its claim at admission, `(n x record + prior_sessions x claim) / (n + prior_sessions)`; its target is proportional to its score above `score_floor`; shares move a fixed fraction of the way to their targets each session (`half_life_sessions`), so nothing jumps, not even a new generation's entry. A short record barely moves the claim, an old generation still earning keeps a share, and one that stops fades out. With no positive score and no record yet, shares hold; with a record and no positive score, the book glides into T-bills.

**Stages on the book:** `ramping` (gaining; `active` after 252 ok sessions), `active`, `fading` (short of its claim, or its score has fallen to nothing, while it keeps whatever share its score earns), `winding_down` (aims for no share, comes back if the record recovers), `retired`. `aq cycle promote` moves one step at a time, by rule.

**In both modes:** a blended row is written on a generation's decision day, every `blend_every` sessions, or on a guard trip, never daily, since a row retargets every name. A guard trip (15% drawdown) or a `dead` state takes capital off at once. Capital no generation may hold sits in T-bills.

**Don't read a generation's Sharpe from `forward/ledger.jsonl`:** that older file credits a crypto decision one bar it never earns (Problems #313). Compare generations in `forward/generations.jsonl` only.

### Local retraining

Anyone can retrain. A fresh checkout builds its own data, from public sources and your own SEC contact.

1. `pip install -e .[train]`, then `aq cycle retrain --host local --smoke`: every stage on a tiny synthetic panel, on any machine, in about a minute.
2. A real run needs 14 GB of RAM (`aq cycle retrain --host local --procedure k06 --dry-run` says what this machine has). Set `AQ_SEC_CONTACT` to your own address if `data_wide/` is absent: it is used for that process only and never stored.
3. `aq cycle retrain --host local --procedure k06`. Stages resume after a reboot (`ml/cycle/retrain_<id>/state.json`).
4. `aq cycle schedule install` registers a weekly retrain-if-due job (Task Scheduler or cron) on a machine that passes the RAM check. `aq cycle schedule show` prints it first. It refuses a smaller machine.

`--host codespace` drives the training Codespace from any machine, and stops it however the run ends. It bills the owner's budget, so no schedule uses it unless asked: `aq cycle schedule install --host codespace` is a deliberate choice.

### When the keys arrive

Everything up to the broker is built and proved without an account. Once the owner has the IB and Coinbase API keys, in order, each step an owner decision:

1. Keys in `lean.json` on the host only, never in a repo file; `aq secrets-check`.
2. Check the Coinbase account really offers the sleeve's USD pairs (`todo.md`); drop EOS (#311).
3. `aq docker build` on the deploy host.
4. In a paper config only: `phase_v2.target_weights.live_reload: true`, `weights_path: ml/generations/blended_weights.csv`, `weights_sha256: ""`. Set `enabled: true` in `ml/generations/policy.json`.
5. `aq paper-readiness`, then the paper run under the protocol below: `aq evaluate --paper-check --backtest-dir <paper run> --reference-dir backtests/2026-11-04_18-10-49`.
6. Live capital is a separate decision, after the forward ledger and the paper verdict.

## Paper period protocol (V6.4.0, lead L12, Problems #228)

The paper period is the only out-of-sample test left. Its success is **not** "make money": a fixed-config run is inside the
bands a reference Lean run spans. Pre-registered, before the first paper day:

1. **Freeze:** the shipped `config.json` sha256 (Changelog "Freeze"), the model manifest, `diagnostics.book_history.paper_enabled: true`
   (a bounded book-history record per rebalance; live never logs it), no live capital.
2. **Minimum:** 6 rebalances and 120 trading days; `aq paper-readiness` passed first.
3. **Checklist** (`aq evaluate --paper-check --backtest-dir <paper run folder> --reference-dir <pinned Lean run>`): veto rate, kill-switch
   lock share, strategy gross exposure, fills per rebalance, median / p90 adverse slippage, fee bps per turnover, strategy and T-bill
   P&L per day, daily hit ratio, annualised turnover.
4. **Bands:** the 5-95% range of every contiguous 6-rebalance window of the pinned final Lean run: since V6.5.0
   `backtests/2026-11-04_18-10-49` (frozen in `ml/evaluation/v650/paper_bands.json`; a target-weights run counts its fill days as
   rebalances and has no veto or lock metrics; the BT11 and BT5 bands are kept as `ml/evaluation/v644/paper_bands.json` and
   `ml/evaluation/v640/paper_bands_bt5.json`). A live run of this path also runs `python scripts/daily_target_weights.py --candidate ml/target_weights_candidate.json --out ml/target_weights.csv` before each open and leaves `weights_sha256` empty.
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
