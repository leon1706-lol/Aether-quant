# Runbook

What to run day to day, and what to do when something goes wrong. Setup is in the README's [Getting Started](README.md#getting-started) section.

## Everyday commands

```powershell
aq test                                                  # the suite (never bare pytest from the root, #8)
aq evaluate --lean-report --backtest-dir backtests/<run> # every report for a finished run, and the README
aq report <backtest-folder> <result-id>                  # Lean's own HTML report
aq cycle status                                          # what is due today
aq api                                                   # API on :8001
aq webui                                                 # dashboard on :3002 (from webui/)
```

## Train in the cloud

Sync before training, verify after, and stop the Codespace right away. The `ml/` artifacts are gitignored, so the SSH copy keeps them out of the public repo.

```powershell
.\scripts\codespace_sync.ps1 -Mode push                       # full tree, hash-verified
# on the Codespace: nohup bash scripts/codespace_retrain_a.sh <tag>; then ..._b.sh <tag> <winner>
.\scripts\codespace_sync.ps1 -Mode pull -Candidate <version ids>
.\scripts\codespace_sync.ps1 -Mode stop
```

- The VM can reboot: resume a walk-forward with `aq train --walk-forward --resume-run-id <id>`.
- Lean runs on a temporary Docker-in-Docker Codespace (`scripts/codespace_lean_run.ps1`, [`development/infrastructure.md`](development/infrastructure.md)). Delete it once its runs are pulled.

## Deploy checklist (paper first)

Stop at the first red item. **No verified edge exists, so no live capital.**

1. **Freeze:** `aq test` green, `ruff check .` clean, `aq secrets-check` passes, `python scripts/ml_manifest.py` equals the manifest of the last Lean run.
2. **Image:** `aq docker build` on the deploy host, then `aq docker up`; `GET /api/assets-status` returns 200.
3. **Config:** `aq render-lean-config` from `.env.live`. Secrets go only in the gitignored `lean.live.json`. `phase_v2.runtime.mode` stays `observation` until step 4.
4. **Gate:** `aq paper-readiness`, then set the mode to `paper`.
5. **Dashboard (Operations page):** check the target-weights sleeve, the venue listing guard and every enabled `sleeve_guards` entry reading `sleeve_guard_ok`.
6. **Crypto venue:** QuantConnect's IB brokerage doesn't support crypto (#192), so a Coinbase key is needed; `aq render-lean-config` warns about it. Crypto exits rest as limit orders (`phase_v2.limit_orders.exit_asset_classes`).
7. **Kill switch fields to watch:** rolling Sharpe floor, drawdown velocity, slippage divergence.

## When the keys arrive

Everything up to the broker is built and proved without an account. In order, each an owner decision:

1. Keys in `lean.json` on the host only, never in a repo file; `aq secrets-check`.
2. Check the Coinbase account offers the sleeve's USD pairs, and drop EOS (#311).
3. `aq docker build` on the deploy host.
4. In a paper config only: `phase_v2.target_weights.live_reload: true`, `weights_path: ml/generations/blended_weights.csv`, `weights_sha256: ""`. Set `enabled: true` in `ml/generations/policy.json`.
5. `aq paper-readiness`, then the paper run under the protocol below.
6. Live capital is a separate decision, after the forward ledger and the paper verdict.

## Paper period protocol

The paper period is the out-of-sample test no backtest can give. Success is **not** "make money": it means a fixed-config run stays inside the bands a reference Lean run spans (#228).

- **Freeze first:** the `config.json` sha256, the model manifest, `phase_v2.diagnostics.book_history.paper_enabled: true`, no live capital.
- **Minimum:** 6 rebalances and 120 trading days, after `aq paper-readiness` passes.
- **Check:** `aq evaluate --paper-check --backtest-dir <paper run> --reference-dir backtests/2026-11-04_18-10-49`. It compares veto rate, lock share, gross exposure, fills per rebalance, slippage, fee bps, P&L per day, hit ratio and turnover.
- **Bands:** the 5-95% range of every 6-rebalance window of the reference run (`ml/evaluation/v650/paper_bands.json`). A target-weights run counts fill days as rebalances and has no veto or lock metrics.
- **Daily:** a live run also runs `python scripts/daily_target_weights.py --candidate ml/target_weights_candidate.json --out ml/target_weights.csv` before each open, with `weights_sha256` empty.
- **Verdict:** every metric inside its band. A metric outside is a finding to explain, written up before any capital decision.

## Forward records

The only tests nothing has been fitted on.

**Forward ledger.** `forward-ledger.yml` appends one hash-chained row per session to the branch `forward-ledger` for each frozen rule in `ml/forward/candidates.json`. A missed session can't be backfilled, which is the point.

- **A late run still records its session:** a run records the newest session on or before today, so a schedule delayed past midnight UTC (it happened on 2026-11-06, #332) or a weekend dispatch writes the session it was for. It never fills an older gap. A run with no session to write exits non-zero, so GitHub emails you.

- **Read it:** `aq evaluate --forward-ledger` verifies the chain (exit 1 if broken). Judge at 60 and 252 sessions.
- **Keep it alive:** GitHub disables a schedule after 60 days without repo activity. `keepalive.yml` re-enables both ledger workflows monthly, but GitHub doesn't document that this resets the timer, so `aq cycle status` still warns. By hand: `gh workflow enable forward-ledger.yml`, then `gh workflow run forward-ledger.yml`.
- **`no_data` rows:** a blocked price source, or a candidate that needs a model. Run those from a PC: `python scripts/forward_ledger.py --ledger <worktree>/forward/ledger.jsonl`.
- **Changing a rule starts a new record:** every row carries its `definition_sha256`. Never edit a candidate in place.
- **Don't compare generations here:** this older file credits a crypto decision one bar it never earns (#313). Use `forward/generations.jsonl`.

**Forward check by rerun.** Sessions after the data freeze are unseen by every rule of that phase.

1. `python scripts/data_append_refresh.py --apply`, then `python scripts/data_append_guard.py verify ...` (no stored row may change).
2. Extend the weights in a copy: `python scripts/extend_frozen_weights.py --definition <frozen> --source ml/target_weights.csv --out <copy> --end <last session>`.
3. Rerun the pinned config on a DinD Codespace with that copy, its window ending at the new session (`runtime.lean_window_override`).
4. `aq evaluate --alpha-proof --backtest-dir backtests/<rerun>` reports them as `fresh`; `forward_judgeable` turns true at 60 equity sessions.

A rerun proves the signal on new prices, not a broker's fills.

## Research cycle

Research a pre-registered round, freeze one candidate, read the holdouts once, shadow on the forward ledger, ramp on the paper book, decay, retire. Evidence moves a generation; nothing else does.

| Step | How | Where |
|---|---|---|
| Every session | `research-cycle.yml` appends returns, states and shares to `forward/generations.jsonl` | GitHub, free |
| A generation needing fundamentals or a model | `aq cycle decide --generation G --weights <csv> --ledger-file <worktree>/forward/decisions.jsonl --session D`, then push the branch before that session's 22:45 UTC run (a decision pushed after it is missed, and is good for 25 sessions) | A host with the data |
| Weekly | `aq cycle status` (also feeds `GET /api/generations`) | Anywhere |
| A new idea | Write a round file, `aq cycle research rules --round <file> --draft <json>`, `scripts/vault_record.py`, then `score`, `placebo`, `gate`, `pbo`, `report`. A survivor: `freeze`, `hold`, R-LEAN21, R-EDGE2 | Training Codespace, or 14 GB of RAM |
| Retrain | `aq cycle retrain --host codespace --procedure k06` | See below |
| Stage change | `aq cycle promote --generation G --to ramping`. Refuses what R-ADMIT1 forbids; retiring is always allowed | Anywhere |
| Blended file for paper | `python scripts/daily_target_weights.py --generations <worktree>/forward/generations.jsonl --out ml/generations/blended_weights.csv` before each open | Paper host |

**R-ADMIT1 (owner, 2026-11-06)**

- A full R-EDGE2 pass ramps at once.
- Selection plus one R-HOLD1 pass (or, once holdouts are spent, selection plus 252 forward sessions) goes to shadow, and may hold up to 30% of the paper book after 60 ok forward sessions without losing to the incumbent.
- A zero-alpha candidate passes that about half the time, so only the cap bounds a false pass. It lifts only on forward alpha t >= 2 at 252, 504 or 756 sessions.
- Anything less holds nothing. Real money is only ever the owner's manual action.

**Moving capital** (`glide.mode` in `ml/generations/policy.json`, chosen by R-GLIDE2)

- **`ladder`:** a ramping generation enters at `entry_share` and gains at a fixed rate; one gains at a time.
- **`dynamic`:** each generation's score is its exponentially weighted Sharpe shrunk toward its admission claim, `(n x record + prior_sessions x claim) / (n + prior_sessions)`. Shares move part of the way to score-proportional targets each session, so nothing jumps. With a record and no positive score, the book glides into T-bills.

**Stages:** `ramping` (`active` after 252 ok sessions), `active`, `fading`, `winding_down`, `retired`. `aq cycle promote` moves one step at a time.

**In both modes:** a blended row is written on a decision day, every `blend_every` sessions, or on a guard trip. A guard trip (15% drawdown) or a `dead` state takes capital off at once. Capital no generation may hold sits in T-bills.

### Local retraining

1. `pip install -e .[train]`, then `aq cycle retrain --host local --smoke`: every stage on a synthetic panel, on any machine, in about a minute.
2. A real run needs 14 GB of RAM (`--dry-run` says what this machine has). If `data_wide/` is absent, set `AQ_SEC_CONTACT` to your own address; it is used for that process only and never stored.
3. `aq cycle retrain --host local --procedure k06`. Stages resume after a reboot.
4. `aq cycle schedule install` registers a weekly retrain-if-due job. `aq cycle schedule show` prints it first.

`--host codespace` drives the training Codespace from any machine and stops it however the run ends. It bills the owner's budget, so no schedule uses it unless asked.

## Incidents

### Kill switch trips repeatedly

**Symptoms:** `kill_switch_tripped` events in `aq audit-log`, or the book locked to `reduce_risk`.

- **Check:** `aq audit-log --verify`, `aq kill-switch --history`. Do trips cluster in a bad period, or spread evenly?
- **Clustered:** the system correctly disengaged; review after the run.
- **Even:** the threshold is too sensitive. Test `phase_v2.risk.kill_switch.min_rolling_sharpe` offline with `aq evaluate --replay-kill-switch` first.

### Reconciliation breaches

**Symptoms:** `reconciliation_breach` events, or positions drifting from intended weights.

- **Check:** `aq evaluate --reconcile-book-history --replay-hysteresis`. A sudden drop in overlap points to data or execution, not the model.
- **Small and stable (under 10%):** within normal slippage.
- **Large and growing:** check factor files in `data/` and scaler stats.

### Data gaps

**Symptoms:** symbols missing from the universe snapshot, or a high multitask fallback rate.

- **Check:** the `data/equity/*/daily/*.zip` files cover the expected dates.
- **Fix:** `aq fetch <type> --ticker <ticker> --apply`. For crypto, verify the exchange listed the pair.

### Sequence model fallback

**Symptoms:** `prediction-provenance: sequence_served=0 multitask_fallback=N` at shutdown.

- **Check:** `train.log` for `_ArrayMemoryError`.
- **Fix:** free RAM before training. The system degrades safely to multitask `rank_20d`.

### Losing money for 5+ days

1. Is the kill switch tripping? If yes, it's working.
2. `aq cycle status`: is the sleeve's state still ok?
3. Compare fills, slippage and fees with `aq evaluate --audit-backtest` and `--audit-fills`. Offline fine but live losing means the execution side.

### A sleeve is suspended by its loss guard

**Symptoms:** `sleeve_guards.<sleeve>.active` is false and the sleeve holds no positions.

- **Check:** `drawdown` and `suspended_until_bar` in `visualization/state.json`.
- **Fix:** nothing until `suspended_until_bar`; the guard is a hard limit. Two suspensions in a row mean no edge: cut the budget or disable the sleeve, and record it in the Changelog.
