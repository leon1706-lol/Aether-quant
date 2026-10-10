# To-Do — Objectives Canvas

This is the owner's planning space, not a generated backlog. Whatever is written below is
the current objective(s) and any personal notes/context for it — read it before starting
work in this repo, and treat it as the live brief for what an AI agent should do next.
Expect this file to be rewritten or cleared out entirely as objectives change; it does not
accumulate history (that's what `development/Changelog.md` and `development/Problems.md`
are for — see `AGENTS.md`).

-----

# Current objective: V5.6.0 - phase complete and verified in Lean (updated 2026-10-10)

Plan: `C:\Users\Blackhead\.claude\plans\please-look-into-agent-mossy-meerkat.md`. Owner rules for this phase: no git commits/pushes (everything is
uncommitted), Codespace only while training, nothing deferred except IB-only items. All 4 budgeted backtests are used.
**Never run anything heavy during `aq backtest`** (Initialize has a 90 s limit) and never `aq test --parallel` (OOM).

## State
Everything is done and written up (Problems #135-#144, Changelog V5.6.0 incl. Round 3 and BT4). Lean Sharpe on the same window and engine:
-2.51 (08-27) -> -1.05 (10-07) -> -0.95 (BT2) -> -0.76 (BT3) -> **-0.042 (BT4, `backtests/2026-10-09_22-13-03`)**; without a risk-free rate +0.66;
net profit +4.73%, DD 2.8%, 534 orders, fees $897. 3218 tests green, ruff clean, Docker image `aether-quant-engine` rebuilt on the final tree (2026-10-09),
Codespace == local (stopped). Not committed.
Shipped config of the final run: forex trading off, `elevated_veto_applies_to_book_members=false`, equity spread cap 10 bps, `edge_bps_per_rank_unit` 574, slippage
trigger 80 bps, spread floor 0.1985, IC floor 0.05, probes off.

## Open findings (most valuable first)
1. **Kill switch is now the main throttle:** `min_rolling_sharpe=-1.0` over 60 bars turned 96 book-member decisions into `reduce_risk` in BT4 (36 in BT3). Replay it offline (`evaluation/kill_switch_replay.py`) and decide whether the floor/window fits a book that now trades 4x as often.
2. **Spread floor is stale for the forex-free pool:** spread-gate vetoes went 25 -> 85 of 281 rebalances (the 0.1985 floor was calibrated with forex in the pool). Run `aq evaluate --calibrate-book-spread` on the new pool and check the validation split before changing it; a lower floor engages more days.
3. **Rolling-IC gate is O(N^2) offline:** each new gate costs ~12 min (`make_rolling_ic_gate_fn`), so `--as-live` takes ~15 min and the lever script ~1 h. Cache the state per date independent of the floor / make it incremental.
4. **Simulator is ~2x optimistic on return** (as-live +11.9% vs Lean +4.7%), but it ranked every round-3 change correctly. The liquidity gate is live-only and still not modelled offline; model it in `evaluation/live_parity.py` for parity.
5. **Hold-on-veto unresolved:** off = +0.44 Sharpe on the backtest split but -0.01 on validation (not flipped). **HRP** and own-tick (+0.06) are not evaluable offline.
6. **Real execution cost unmeasured:** Almgren impact takes the as-live Sharpe 0.78 -> 0.53 (constants are generic); fill price vs dataset open differs by a median 5 bps (likely a data-source gap, not slippage) - compare Lean's zips with the dataset's yfinance opens, then measure paper/IB fills. 11 limit orders stayed open > 5 days in BT4 (6 in BT3).
7. **Crypto book pool is one name** (`trading_eligible_rate` 1/6; the other 5 are observation-only, #126) and crypto fees are 56 bps per fill: decide whether to graduate more crypto.
8. **Forex is off, not removed:** its bars still feed topology/peer/macro features; revisit if the $2 IB minimum becomes immaterial (~8 bps per fill at ~2% NAV).
9. **`book_history.jsonl` is cumulative (18 runs, ~65 MB):** audits pair a run with `--book-run-index`; consider rotating it per run.
10. **No out-of-window data** (ends 2021-03): levers were tuned on the window Lean tests; only the validation split is independent evidence.
11. Lean 17900's teardown timeout (#104) is environmental (every run: `Failed to shutdown python`).

## For the owner
Commit + push is yours to decide (CI fixes are only verified locally - the first real CI run is the unknown; Dependabot PRs untouched). For a paper/live deploy use the rebuilt `aether-quant-engine`.
`ml/_backup_pre_v560/` holds the pre-promotion models; `visualization/forex_order_sizing.jsonl` is a runtime log modified by backtests - leave it out of a commit.

## Deferred (IB-only, do not touch)
#35, #38, #58, #59, #60, #61, #67 and the IB part of #116 - need a live/paper IB connection.
