# To-Do — Objectives Canvas

This is the owner's planning space, not a generated backlog. Whatever is written below is
the current objective(s) and any personal notes/context for it — read it before starting
work in this repo, and treat it as the live brief for what an AI agent should do next.
Expect this file to be rewritten or cleared out entirely as objectives change; it does not
accumulate history (that's what `development/Changelog.md` and `development/Problems.md`
are for — see `AGENTS.md`).

-----

# Current objective: V5.7.0 is complete - owner decisions pending
## State (2026-10-11)
Every step of the V5.7.0 plan was executed and written up (Problems #145-#154, Changelog "V5.7.0"). Lean on the same window and engine:
-0.76 (BT3) -> -0.042 (BT4) -> +0.068 (BT5) -> +0.128 (BT6) -> **+0.474 (BT7, `backtests/2026-10-11_14-23-30`)**; without a risk-free rate +0.663 -> +0.711 -> +0.768 -> **+1.151**;
net profit +4.73% -> **+8.64%**, drawdown **2.8%**, 641 orders, fees $822. All three allowed backtests are used. 3306 tests green, ruff clean, vault regenerated.
Shipped config: V5.6.0 models, rolling-IC gate window 80 / floor 0.0, `min_rank_confidence_spread` 0.184, legacy sleeve cap 0.05, per-run book history, slippage tracker = adverse
market fills only, forex trading off, RL sizing off. Local `ml/` == the V5.6.0 push snapshot (SHA-256); Codespace key files + `ml/expert_models` == local, `data_holdout/` == local,
`data/` differs by ONE Codespace-only file (`data/readme.md`, 2914 B, Jul 20; deleting it was blocked by the permission classifier). Codespace stop was issued (verify `Shutdown` with `gh codespace list`).

## Decisions for the owner (nothing below was done unprompted)
1. **Docker image rebuild** (`aether-quant-engine`) is required before any paper/live deploy - the tree changed materially.
2. Optional: delete the stray `data/readme.md` in the Codespace so `codespace_sync.ps1 -Mode status` is fully green.
3. The shipped numbers are IN-SAMPLE for the gates (tuned on the window Lean tests). Honest out-of-window evidence: the 2021-04..2025-06 holdout has real rank IC (+0.055 at 5 d) but the gated book loses there (Sharpe -0.21). Any further backtest is your call.

## Leads for the next objective (most valuable first)
1. **Holdout book loss:** on 2021-25 the rolling-IC gate vetoes 513 of 630 rebalances and the kill switch locks 315 dates while the IC is positive - study the gates on the holdout split (report-only so far; deciding anything from it turns it into a tuning set, so carve a fresh out-of-window slice first).
2. **Next retrain recipe** (flips reverted so config == shipped models): `phase1.windows.purge_label_horizon_days: 20`, `fx_carry_3m` in `phase1.features.input_set`, `phase1.target.ranking.separate_rank_groups: {"forex": ["forex"]}` + `separate_rank_group_min_size: 8`; the honest walk-forward `rank_20d` IC with the purge was 0.049 (the old 0.101 was leaky), so a new model must be judged against that bar. The overfitting variants (wd x4, dropout, small net) all stayed inside the seed spread.
3. **Residual slippage trigger:** 35 member decisions are still labelled `kill_switch_slippage_divergence_above_cap` in BT7 (a non-limit path, e.g. a cancelled limit re-sent as market); write the divergence value into the book-history record to localise it (needs a backtest to observe).
4. **Crypto is a cost centre** (48 bps per fill; BT7 book members +$476 net on 12 trades) - kept because removing BTC/LTC loses on both splits (#149).
5. **Forex has no within-pool rank edge** (IC -0.07 with or without carry); revisit only with a different signal source. **RL sizing** failed a fifth time (#150); the book-level reward code ships default-off.

## Deferred (IB-only, do not touch)
#35, #38, #58, #59, #60, #61, #67 and the IB part of #116 - need a live/paper IB connection.
