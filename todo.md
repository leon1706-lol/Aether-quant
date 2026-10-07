# To-Do — Objectives Canvas

This is the owner's planning space, not a generated backlog. Whatever is written below is
the current objective(s) and any personal notes/context for it — read it before starting
work in this repo, and treat it as the live brief for what an AI agent should do next.
Expect this file to be rewritten or cleared out entirely as objectives change; it does not
accumulate history (that's what `development/Changelog.md` and `development/Problems.md`
are for — see `AGENTS.md`).

-----

# Open for the next phase

**Where we are (2026-10-07):** the V5.5.0 execution fixes are backtest-verified (Problems #127–#134). Latest run
`backtests/2026-10-07_19-28-54`: Lean Sharpe −1.05 (+0.17 without a risk-free rate), +0.68% net, 403 orders,
$475 fees, mean hold 24 days, no trade under 2 days. Equity +$1,603, forex −$171, crypto −$403. What is left is
edge (model quality) and a few leads. Nothing is committed.

- **Decide the commits** (your earlier WIP is mixed with V5.5.0), push, watch the first CI run.
- **Model quality is the lever:** the book is vetoed on ~79% of rebalances and only 0.16 of the idealized 0.94 Sharpe is alpha after SPY and momentum. Retrain on the Codespace first (below), then re-judge.
- **Rolling-IC floor (0.05):** your call — `aq evaluate --replay-rolling-ic-gate` shows the trade-off.
- **Crypto:** 16 trades lost $403 (four LTCUSD longs −$421…−$991) and pay $0 fees (Lean's Coinbase model) — verify a percentage fee model against Lean, then review crypto sizing/stops.
- **Teardown hang (#104)** persists in the engine log — lead is native/.NET side, not Python.
- **Feature divergence (#135):** cross-asset features (`macro_*`, `peer_*`, `topology_correlation_strength`) differ live vs dataset on ~100% of dates — trace the alignment; re-run `aq evaluate --reconcile-features --symbol XOM` after the retrain (price-level gaps should vanish).
- **Book-history reconciliation** (`aq evaluate --reconcile-book-history --replay-hysteresis --hysteresis-survives-veto --reconcile-all-runs`, ~1.3 GB RAM — run alone) and `scripts/overlap_vs_sharpe_analysis.py` still not run.
- `topology_elevated_volatility_pressure` turned 92 equity selections into `reduce_risk` — review the threshold; `topology_payload` costs ~24% of runtime (332 ms/call).

## Handoff notes for the next agent

- **State:** V5.5.0 is complete and committed as one commit (see `git log -1`); suite green (3152), ruff clean, diagnostics probes off, config at the round-3 values (IC floor 0.05, `legacy_sleeve` 0.10/0.02, `hold_owned_positions_on_veto` true, `max_spread_proxy_by_type` crypto 0.001 / forex 0.0003, `fill_slippage.source` `per_side`, crypto volatility threshold 0.87). Reference Sharpes: offline idealized 1.00 · as-live 1.68 · Lean 08-27 −2.51 · 10-07 round 1 −4.55 · round 2 −1.46 · round 3 −1.05.
- **Judge a backtest with:** `aq evaluate --audit-backtest` (newest folder by mtime — `ls -dt backtests/*/`, not alphabetically), engine `backtests/<run>/log.txt` (not `<id>-log.txt`) for the `numerical precision` line (must list only `AAA`), `adjust to a later starting date` (must be absent) and `Shutdown(): ended`. The check that found #134: compare each symbol's FIRST trade with its RE-ENTRIES (`closedTrades` in `<id>.json`) — a first trade that holds while re-entries die after a day means stale per-symbol state.
- **Traps (all in AGENTS.md / Problems):** never `import time` in `main.py` (Lean's star import shadows it, #132); a sentinel-only factor file pushes data to 2050 — the 62 yfinance-backfilled tickers must have NO factor file (`python -m data_pipeline.factor_file_backfill --audit` → 0); daily orders fill on the NEXT bar, so any per-symbol state keyed on a same-bar invested↔flat transition is wrong (#128, #134); `bar_index` only advances on equity-session ticks.
- **Machine:** ~4 GB RAM — one heavy process at a time, `aq test` never `--parallel`, run reconciliations alone; the harness kills background jobs when memory is critical.
- **Not committed on purpose to review:** `visualization/forex_order_sizing.jsonl` is a runtime log that grew by ~1800 lines — exclude it from commits (`git restore visualization/forex_order_sizing.jsonl`).

## Blocked by environment

- **Codespace retrain** (never local): regenerate dataset + full retrain on the repaired factor files (#130/#135); RL sizing retrain (pick `asymmetric_penalty_weight` > 1.0 first); walk-forward relaunch (#107); flag-off control retrain (#95); `residual_rank_20d` (#112); topology overlay retrain (#56). Don't run `aq train --dataset-only` locally.
- **IB / option & future data:** #38, #58, #59, #60, #61, #67, #116, #35.
- **CI first-run unknowns:** `docker-checks`, `secret-scan`, `fast-guards`, `subsystem-matrix`, `wheel-smoke`, `python-compat` only simulated locally — fix what the first push shows.
- Run `aq test` sequentially (`--parallel` OOM-killed this PC).

## Owner decisions / future

- HRP flip; Almgren impact live on/off; slippage-divergence kill-switch trigger; quote zips for observation-only crypto (#126); delete unpromoted `codespace_v536_20260823` artifacts; legacy-sleeve caps; decide forex/crypto on their own tick.
- Docker image rebuild + verification before any paper/live deploy; a real Lean backtest of every later change (owner runs it).
