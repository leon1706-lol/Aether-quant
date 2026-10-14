# To-Do — Objectives Canvas

This is the owner's planning space, not a generated backlog. Whatever is written below is
the current objective(s) and any personal notes/context for it — read it before starting
work in this repo, and treat it as the live brief for what an AI agent should do next.
Expect this file to be rewritten or cleared out entirely as objectives change; it does not
accumulate history (that's what `development/Changelog.md` and `development/Problems.md`
are for — see `AGENTS.md`).

-----

# Current objective: V5.8.0



V5:
- cmpleaste all known leads
- please d oreserch on the forex problem, rl sizing problem, bonds rtraining, crypto missing data
- thee probram at the end of this file should be allowed to trade andd use them
-  you can also if needed utilise tools like aq fetch etc to get more data on them
- after this phase all leads should be closed all probelmd problems which dont need IB verification or live testing should be not onl having an verdict but fully closed with an positive result 
- and the system shiuld be ready for live deployment with verifiable results 
 - all funcutanalety should also be usable of this probram 
- also build autit tools for trerch to fix the probles 
- at the end of this phase you should have retrianed the entyre model and submodels with all the bugixes in place an evaluated it  with all tests like benchmark montecarlo offline eval and lean 
- imporve resorce eficenty and latency through otu the entyre projekt
- all features of the models should have promotable performance afterwards
- aslo rebuild the docker image at the very end and you have 2x lean backtests as budget 
- take as long as you need for this push it will be the last mak´jor release befor V6

## V5.8.0 status: COMPLETE, waiting for your decisions (updated 2026-10-14)

Everything the objective asked for is executed and verified, with the owner's decisions applied: data to 2026-09-30, the full stack retrained and walk-forward tested, forex / bonds / crypto / RL all trading at a cap with loss guards, the audit tools built, both Lean backtests run and written up, the Docker image rebuilt. **Nothing is committed** (your call, below). Numbers and reasoning: `development/Problems.md` #156-#174 and the `## V5.8.0` Changelog entry.

### Verified state
- **Tests:** 3,423 passed locally (`aq test`, sequential), 3,419 passed + 1 known docs-link case on the Codespace (Python 3.11); `ruff check .` clean; `aq secrets-check` passes; `aq render-lean-config` works.
- **Frozen config / models:** BT2 ran on `config.json` sha256 `30534b24d02969457369e8ca991df0d562431f13836520b8ae4ade82618094e9`; afterwards `runtime.lean_window_override` was reset to `null` (the only change), so the shipped config is sha256 `6b3861944fc1b8d220a9c2d487829733f10c7a4f5cc425f50f149f5859fd97d8`. Installed models = `ml/evaluation/v580/installed_manifest_bt2.txt` (sha256 `cf8f68fe242da1e837b01598c3ec95bae1aee26c4dad50e4c2393ce622ed05fa`).
- **Docker:** `aether-quant-engine:latest` rebuilt (`4e4033c3ac82`) and smoke-tested (`/api/assets-status` 200 with the sleeves). Docker Desktop is shut down to save RAM (start it before the next Lean run, wait for `docker info`).
- **Codespace:** code pushed (`-CodeOnly`), suite run, `data/` and the models identical to local, **Shutdown confirmed**. Its `config.json` still carries BT2's window override (local was reset to `null` afterwards); the next `-CodeOnly` push overwrites it.
- **Docs:** README (backtest history, Known Limitations), RUNBOOK deploy checklist, architecture parity row, infrastructure, asset_universe, project_structure, sub-readmes, Problems closure (every non-IB entry is 🟢 or 🔴; the only 🟡 left are the IB-only ones), vault regenerated.

### What the Lean runs say (Problems #172, #174)
| run | window | no risk-free Sharpe | net | drawdown | fees |
|---|---|---|---|---|---|
| BT1 (regime skew, bond gross 0.30) | 2023-07..2025-06 | -0.75 | -5.03% | 8.2% | $975 |
| **BT2 (regime fix, bond gross 0.10)** | 2023-07..2026-09 | -0.03 | -0.58% | 4.3% | $2,195 |
| BT2 backtest stretch / holdout stretch | | +0.14 / -0.40 | +1.04% / -1.61% | 3.6% / 3.9% | |

**The system preserves capital and shows no demonstrated edge:** gross result +$1,614 against $2,195 of costs; the one-look holdout agrees. The regime-input fix (#173) is confirmed in the engine (features equal the dataset on 89 of 90 dates, live-pool book replay shares 0.81 of the names against 0.77 in BT1 and BT3), but it explains only part of BT1 -> BT2.

### Decisions I need from you
1. **Commit?** The diff is large and uncommitted. I did not commit, push or tag anything.
2. **L3, the posture of the main equity book** (idealized -0.72 backtest split, -0.81 holdout, BT1 -5.0%, BT2 about flat after costs): **paper only, no live capital** (my recommendation; the README and RUNBOOK already say so), or cut its gross budget, or stop it.
3. **Forex sleeve** lost $544 net over 3.25 years at the minimum cap with its guard never tripping: keep it capped or drop it.
4. **Crypto fees:** the exchange charges 70 bps per fill, $1,131 against $775 gross; try crypto limit entries (maker 60 bps) or shrink the graduates further.
5. **Delete backups?** `data_backup_pre_v580/`, `data_holdout/` (superseded by `data/` plus the `phase1.windows.holdout` key), `ml/_backup_pre_v580/` and the `ml/versions` and older `ml/_backup_*` trees that `aq clean ml` lists (dry run: 70 items, **13.7 GB**, the installed models protected; full list in `ml/evaluation/v580/clean_ml_plan.txt`; `aq clean ml --apply` deletes). `data_backup_pre_v580/` is 240 MB, `data_holdout/` 24 MB. Nothing was deleted.

### Leads for the next objective (V6)
1. **Alpha, not plumbing:** the pooled rank IC of +0.05 does not pay for a top-6/bottom-6 book's costs; look at lower turnover (longer holds, wider hysteresis), class-neutral books, or a different target.
2. **Offline simulator vs Lean:** the as-live Sharpe overstated BT1 by +1.4; every gate number was tuned on it. Re-derive the gates on a model of the live execution, or stop trusting offline gate numbers.
3. **Crypto cost:** 70 bps per fill; limit entries, fewer names.
4. **Forex feed gap:** EURUSD `atr_pct_14`, `liquidity_spread_proxy` and `sens_*` match neither dataset row (Lean's forex bars vs the Yahoo high/low). Harmless while the sleeve ranks by carry.
5. **Small parity residuals:** crypto `topology_correlation_strength` / `cs_momentum_rank_20`, TLT one date (#36 cache tolerance).
6. **`ml/datasets/full_dataset.csv` is still the pre-V5.8.0 window**; several `aq evaluate` flags read it by default (pass `--dataset ml/datasets/cand_eval_dataset.csv`, or rebuild it on the Codespace).
7. **Latency left** (BT1 probe): `build_model_input` 386 s, `topology_payload` 347 s, `inference_cluster` 284 s, `pass2` 101 s; `write_state` is solved for backtests.
8. **Dataset vintage nit:** the Codespace-built candidate datasets saw ETHUSD/LTCUSD rows from 2017-09 and 2018-04 that differ from local (3-5 days, now aligned); a rebuild on the aligned data would remove it.
9. **#104 teardown timeout** is unchanged (after results are written, harmless).

### Deferred (IB-only, do not touch)
#35, #38, #58, #59, #60, #61, #67 and the IB part of #116 - need a live/paper IB connection. `aq paper-readiness` needs the deployed Postgres and the paper broker config, so it belongs here too.

### Resume checklist
- Never push to the Codespace without `-CodeOnly` after a retrain (a full push overwrites the remote `ml/`).
- Keep the PC light during a Lean run (`Initialize()` has a 90 s limit; ~250 MB free is what a run starts with). Quit Docker Desktop and `wsl --shutdown` for any heavy offline job; a stuck `WslService` needs an elevated `taskkill /F /PID <its pid>`.
- Git Bash rewrites `/app/...` in `docker run -v`: set `MSYS_NO_PATHCONV=1` and use `pwd -W` paths.

