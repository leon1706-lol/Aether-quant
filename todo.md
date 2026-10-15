# To-Do — Objectives Canvas

This is the owner's planning space, not a generated backlog. Whatever is written below is
the current objective(s) and any personal notes/context for it — read it before starting
work in this repo, and treat it as the live brief for what an AI agent should do next.
Expect this file to be rewritten or cleared out entirely as objectives change; it does not
accumulate history (that's what `development/Changelog.md` and `development/Problems.md`
are for — see `AGENTS.md`).

-----

# Current objective: next phase (V7)

_(write the objective here)_

## What V6.0.0 decided (nothing was committed; see `development/Changelog.md` "V6.0.0")
- **Main book posture:** research then rule. The only single change that beat its costs on the ungated execution-calibrated book was a slower book (rebalance every 20 bars, hold up to 40: `config.json`); the gross cap stays 1.0 (R-POSTURE: members +$4.7k, Sharpe +0.55 in BT1). Live capital stays **zero, paper only** (README and RUNBOOK say so).
- **Forex sleeve:** dropped by rule R-FX6 (none of 48 variants was positive on the backtest split); `forex_risk.enabled` false, the sleeve settings stay in the file.
- **Crypto fees:** limit exits for crypto, route-aware fee, graduates capped at 0.5% per name / 2.5% class; the research's offset 0.0 was reverted after BT1 (Lean charges a limit at the last close as a taker). BT2: 63.9 bps per fill, fees $546 against $1,131.
- **Backups:** `aq clean ml --apply`, `ml/_backup_pre_v580/`, `data_backup_pre_v580/` and `data_holdout/` are deleted. Still there and **not** approved for deletion: `data_v580_staging/` (35 MB, gitignored) — ask before removing.

## Starting point
- Shipped config `config.json` sha256 `2e77b7cfea6a62141fa985b4a942ccd86ed316974ca37423dbd0335bcfa454f3` (`runtime.lean_window_override` is `null`, probes off); installed models unchanged since V5.8.0 (47 files, `ml/evaluation/v600/manifest_start.txt`). Lean numbers over 2023-07..2026-09: V5.8.0 BT2 -0.58%, V6 BT1 +6.72%, V6 BT2 +5.28% (README "Lean Backtest", Problems #185, #186).
- Docker Desktop is off (start it before a Lean run, wait for `docker info`, quit it again for heavy offline work); the Codespace is Shutdown; `ml/datasets/full_dataset.csv` and the split files are the V5.8.0 window with train / validation / backtest / holdout again (active scaler).
- Heavy offline jobs (the simulator over backtest + holdout, the research scripts) run on the Codespace: `scripts/codespace_*_v600.sh`; the 4 GB PC cannot hold them (Problems #176).

## Leads for the next objective
0. **Revert the slower book?** R-LEAN9's drawdown clause failed in both V6 runs (5.40%, 5.50% > 5%) because the book lost $3.0k on the 2023-07..2025-06 stretch it was selected on (+$1.5k for the old config) and won on the holdout stretch it was not selected on. Whole-span Lean says keep it; the stretch it was picked on says it is noise. A cap of 0.5 on `portfolio_book.neutrality.gross_exposure_cap` would roughly halve both. Owner call; no Lean run is left to test it (budget was 2).
1. **Alpha, still unproven out of sample:** the in-window rank IC (+0.05) pays for a slow book only on some paths; the gain over V5.8.0 is in the seen holdout. The honest test is a paper period. Cheaper ideas: more than one Lean path per config (the same book differed by $2k of main-book P&L between BT1 and BT2), a 60-day head that passes its promotion gate (it failed on all three seeds), class-neutral books through `per_asset_class_slots` (they lost offline).
2. **The legacy signal is the steadiest P&L component** (+$2,148 BT1, +$2,086 BT2; the unbudgeted probability signal on non-members, capped by `legacy_sleeve`); the simulator does not model it and no research has looked at it.
3. **Simulator vs Lean:** daily correlation with Lean's main book is 0.70 / 0.68 / 0.21 (BT1, BT2 backtest stretch, holdout stretch), decisions agree on 63 / 72 / 52% of rebalances, and it predicted -3.1% for BT1's span against Lean's main book +4.7% (right on day-to-day moves, wrong on the holdout stretch). R-CAL stays branch B until all three windows clear r 0.50 / return gap 2 pp / agreement 80%.
4. **Crypto live venue:** the book prices Coinbase fees (`CoinbaseFeeModel`); whether the configured live brokerage (IB) trades crypto at all is unchecked and belongs with the deferred IB items.
5. **Parity residuals that are left:** EURUSD / GBPJPY diverge on 15 of 170 dates (macd on 5-6%, the sensitivity betas on 3.5%; small deltas); forex is off, so it does not touch P&L.
6. **Latency left:** the BT1 probe is not comparable (the PC was busy); re-measure on an idle machine. Rejected for now: re-using own-tick predictions on the equity tick, an own-window indicator cache.
7. **#104 teardown timeout** is unchanged on `lean:17900` and on the newest tag (a 15-line algorithm hangs identically): environmental.

## Deferred (IB-only, do not touch)
#35, #38, #58, #59, #60, #61, #67 and the IB part of #116 need a live/paper IB connection; `aq paper-readiness` needs the deployed Postgres and the paper broker config, so it belongs here too.

## Resume checklist
- Never push to the Codespace without `-CodeOnly` after a retrain (a full push overwrites the remote `ml/`).
- Keep the PC light during a Lean run (`Initialize()` has a 90 s limit; ~250 MB free is what a run starts with). Quit Docker Desktop and run `wsl --shutdown` for any heavy offline job; a stuck `WslService` needs an elevated `taskkill /F /PID <its pid>`.
- Git Bash rewrites `/app/...` in `docker run -v`: set `MSYS_NO_PATHCONV=1` and use `pwd -W` paths.
- Inline `ssh` commands lose double quotes on Windows: use `grep -e a -e b`, never `grep -E "a|b"`, and never `pkill -f` through ssh.
