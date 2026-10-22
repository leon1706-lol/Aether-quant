# evaluation

Offline, cost-aware evaluation of the cross-sectional rank book (V5.1
Phase 0, development/Problems.md — the phase focused on model prediction
performance). Answers the question nothing else in this codebase could:
`train.py::compute_strategy_metrics()` simulates a long-only 1-day-direction
strategy **gross of costs**, not the rank book, and not net of cost. This
package turns "how good is this rank prediction" into "what would this have
actually earned net of fees."

Pure numpy/pandas — **deliberately no torch import**, so `performance/` and
`retraining/` (and any future Postgres-fed monitoring job) can import it
without pulling in the training stack, the same torch-free-core convention
`train.py::_rank_ic_from_arrays()` established for its own metric.

- `rank_book_simulator.py::simulate_rank_book(...)` — reuses the **exact**
  selection/neutrality machinery `main.py`'s live decision path uses:
  `portfolio.book_construction.build_rank_based_book()` (including its
  hysteresis-aware sticky selection) and
  `portfolio.book_neutrality.apply_book_neutrality()`. Per date: rebalance
  on schedule, equal-weight each leg, neutralize, hold until the next
  rebalance, accrue gross return and cost (`cost_bps_per_side +
  commission_bps`, charged on turnover only at rebalance). Dates with fewer
  than `min_universe_size` eligible rows are **skipped**, not zero-filled.
- `rank_book_simulator.py::capacity_curve(...)` — sweeps `top_n` (breadth
  check: is the edge concentrated in a handful of names, or genuinely
  spread across the cross-section?) and estimates a rough capacity ceiling
  from the lowest-average-dollar-volume held name.
- `rank_book_simulator.py::stress_test_costs(...)` — re-runs the simulation
  at 1×/2×/3× the configured cost, answering "does the edge survive if
  real-world costs turn out higher than calibrated."
- `rank_book_simulator.py::summarize_metric_stability(...)` — cross-window
  sign-flip-fraction + bootstrap-CI summary (used by Phase 4's walk-forward
  evaluation and Phase 5's ablation harness). Duplicates the ~12-line
  bootstrap from `train.py::bootstrap_ic_confidence_interval()` rather than
  importing it, for the same torch-free reason above.
- `live_parity.py` (V5.5.0, Problems.md #128) — turns config + dataset into the
  keyword arguments that make `simulate_rank_book()` mirror `main.py`:
  `build_as_live_kwargs()`, `lag_predictions_for_tickers()` (forex/crypto bars
  land after the equity tick), `make_rolling_ic_gate_fn()` (lazy, cached,
  no-lookahead gate per date), `build_candidate_metadata()`. The simulator's
  matching switches (all default to the idealized behavior): `normalize_to_percentile`,
  `min_rank_confidence_spread`, `rolling_ic_gate_fn`, `live_weighting`,
  `hold_positions_on_veto`, `retry_rebalance_after_veto`, `max_holding_dates`,
  `candidate_metadata_by_ticker`; the result gains `num_vetoed_rebalances`/`veto_reasons`.
  Exposed as `aq evaluate --rank-book --as-live`.
- `lean_attribution.py` (V6.0.0, `aq evaluate --attribute-lean`) — a Lean run's daily P&L per ticker and component from its order events and the data zips, reconciled with the equity curve; fee per fill by route.
- `lean_statistics.py` (V6.2.0, `aq evaluate --lean-stats`) — Lean's Sharpe / Sortino / PSR reproduced exactly from a result JSON (compounded mean daily return, sample variance x days a year, the risk-free file averaged over every equity sample), on any rate file and day count, plus counterfactual daily returns (`with_extra_daily_returns`).
- `tranche_book.py` (V6.2.0, rule R-STAGGER) — the staggered tranche book offline: the sum of K phase-shifted runs of `simulate_rank_book`, each tranche's kill switch fed the others' returns; `simulate_rank_book(cash_sweep=)` models the T-bill sweep as its own component outside the kill switch.
- `backtest_audit.py` (V5.5.0, #127) — order-level audit of one finished Lean
  run (`aq evaluate --audit-backtest`): exposure per asset class, book-member vs
  non-member entries (`classify_entries`, against the run's own
  `book_history.jsonl` segment), overlapping/long-open limit orders, holding
  histogram, P&L and fee bps per class, Sharpe with and without a risk-free
  rate, gate vetoes, engine-log teardown, and (V5.6.0) `pnl_by_entry_bucket` (book vs
  legacy-sleeve P&L net of fees; `--book-run-index` pairs an older run with its own book segment). Pure functions over the run folder;
  stdlib + `rank_signal_calibration.segment_logged_records_by_run`.
- `volatility_threshold_calibration.py` (V5.5.0, #129) — per-asset-class
  percentile of the topology's own 24-return annualized volatility, with a
  suggested `phase_v2.topology.elevated_volatility_threshold`.
- `factor_neutralization_check.py` — `compute_factor_exposure()` plus (V5.5.0)
  `compute_book_factor_exposure()` (SPY + long-short momentum factors from the
  dataset's own close pivot, forward-dated like the simulator); alpha now
  includes the regression intercept (it was always 0.0 before).
- `model_predictions.py` — runs every dataset row through
  `inference/exported_model.py` (the **same** torch-free interpreter
  `main.py`'s live decision path uses) to produce a predicted-`<head>`
  column, so every number this package reports is the offline mirror of
  live behavior, not a separately re-derived approximation. Includes a
  torch-free port of `train.py::build_sequence_tensor_dataset()`
  (`build_sequence_windows()`), cross-validated against the original in
  `tests/test_model_predictions.py`.
- `ablation.py::run_ablation(...)` — isolates the contribution of
  neutrality/hysteresis/cost-model by re-running the simulation with each
  turned off in turn. Runtime-only mechanisms with no offline equivalent
  (gating, topology sizing) report an honest `not_offline_measurable`
  sentinel instead of a fabricated number.
- `rank_signal_calibration.py` — `calibrate_book_confidence_spread()`
  (derives `min_rank_confidence_spread` from real per-date score
  dispersion); `reconcile_book_history_date()`/
  `replay_book_history_reconciliation()`/
  `summarize_book_history_reconciliation()` (compares a real Lean
  backtest's logged book selections against a fresh offline
  re-derivation — independent or hysteresis-replayed); `summarize_book_member_diversion()`
  (aggregates each book member's final action/reasons, V5.2.6).
- `confidence_threshold_calibration.py` — derives `min_confidence_to_trade`
  from the real confidence-vs-forward-return relationship, same
  percentile-of-a-real-distribution discipline as the book-spread
  calibration above.
- `kill_switch_replay.py::replay_kill_switch_over_dataset(...)`/
  `summarize_kill_switch_replay(...)` (V5.2.8) — a day-by-day offline
  replay of the kill-switch + sticky trade-lock state machine against the
  rank book's own return series. Explicitly approximate (see its own
  module docstring): no bypass flags, no `net_edge`/book-selection
  modeling, only the two dataset-derivable `evaluate_kill_switch()`
  inputs plus the drawdown-lock breach.
- `limit_fill_simulator.py::simulate_limit_fills(...)`/
  `sweep_limit_fill_offsets(...)` (V5.3.1) — an offline counterfactual
  estimate of how often a real limit order would fill vs. time out,
  reusing `execution/order_gate.py::resolve_limit_price()` against the
  dataset's own high/low bars. Answers a different question than the real
  order-events evidence (development/Problems.md #34/#96): "would this
  signal have filled," not "did the real book's actual orders fill."
- `feature_reconciliation.py::reconcile_feature_snapshot(...)`/
  `summarize_feature_reconciliation(...)` (V5.3.5.3, Problems.md #91/#100)
  — diffs ONE symbol's logged live feature values (book_history.jsonl's
  allowlist-bounded `feature_snapshot` field) against full_dataset.csv's
  same (ticker, date) rows: per-feature deltas, tolerance-gated
  (abs AND rel), NaN-degrading, worst offenders aggregated first. Pure
  diff core only — the CLI (`aq evaluate --reconcile-features --symbol
  XOM`) owns all I/O and joins.
- `readme_research.py` (V5.8.0) — also `build_lean_vs_offline_markdown`: the audited Lean run's sub-periods (`--audit-backtest --period`) next to the offline books and the S&P 500 / 60-40 over the same dates, in the README's Lean section (`AQ:LEANCMP`); README markdown for the as-live book per split
  and the research/audit block (sleeve and RL verdicts, class IC, gate audit,
  head audit, holdout). Pure JSON-to-markdown; `generate_evaluation_report.py`
  calls it, and every audit flag and research script refreshes the README on exit.
- `monte_carlo.py::run_monte_carlo(...)` (V5.3.8) — stationary-block (or
  i.i.d.) bootstrap of the offline rank book's daily NET returns into N
  alternative equity histories: per-run curves, red average curve,
  return/Sharpe/maxDD percentile distributions, loss probability.
  Deterministic given seed; pure numpy core — the CLI
  (`aq evaluate --rank-book --monte-carlo`) owns inference + persistence +
  README chart/section refresh.
- `benchmark_comparison.py` (V5.4.3) — naive strategy baselines
  (momentum top-N / mean-reversion / random-entry) on the same dataset
  and window as the rank book, so the model's edge is stated relative to
  simple benchmarks rather than in isolation. V5.4.4 added
  `close_pivot_from_frame()` (long-format dataset frame → the
  (dates × tickers) close pivot every baseline consumes) and
  `run_all_baselines()` (all five baselines into one report dict), plus a
  real return accrual for the mean-reversion baseline (it previously
  accrued a hardcoded placeholder, so its Sharpe was structurally 0.0).
- `public_benchmarks.py` (V5.4.4) — well-known PUBLIC benchmark
  baselines computed from the universe's own index/bond proxy columns:
  `compute_sp500_baseline()` (buy-and-hold SPY) and
  `compute_60_40_baseline()` (60% SPY / 40% TLT, daily rebalanced).
  Same `close_pivot` input, same Sharpe formula, and same output shape
  as the strategy baselines above (plus a `status` field — a universe
  without SPY/TLT degrades to `SKIPPED`, never a crash). Zero new data
  dependencies.

Both modules are surfaced end-to-end by `aq evaluate --benchmarks`
(included in `--all`): the CLI writes
`ml/evaluation/benchmark_comparison.json`, the README's Benchmark
Comparison section auto-refreshes from it, and the webui's Evaluation tab
renders it via `/api/evaluation`'s `benchmarks` key (BenchmarkPanel).

## V5.6.0 additions

- `model_predictions.predict_heads()` — every requested head from ONE interpreter pass per row
  (`predict_head()` re-ran the whole model per head); both accept `row_mask` (predict only those
  rows, windows built only for them) — the reconciliation tools run in ~150 MB instead of ~1.3 GB.
- `simulate_rank_book(commission_bps_by_ticker=..., entry_veto_column=...)` — a per-ticker exchange fee
  that replaces the generic commission (crypto), and the analyzer's Priority-3 elevated-topology veto
  as an entry filter (`build_as_live_kwargs(topology_config=...)` turns it on unless
  `phase_v2.topology.elevated_veto_applies_to_book_members` is `false`).
- `feature_parity.py` macro / cs-rank replicas follow the live tick order (bars visible strictly
  before the row's own tick); see `features/README.md`.

## V5.7.0 additions (the as-live simulator models what Pass 2 actually does)

- `rolling_ic_series.py::make_rolling_ic_state_fn` — the rolling-IC state of every date computed once
  (per-origin IC versions as tickers resolve), equal to `compute_rolling_ic_state` on every date incl. mixed
  equity/crypto/forex calendars and live's bounded buffer; one state serves every floor
  (`live_parity.make_rolling_ic_gate_fn(state_fn=...)`). Replaces the per-date full-history recompute (~15 min per gate).
- `simulate_rank_book(kill_switch_config=, kill_switch_sticky=, member_weight_fn=, raw_weights_fn=, impact_inputs_fn=,
  min_commission_usd_by_ticker=, hysteresis_anchor_on_formed_book=)` — all default off. The kill switch runs
  `risk.kill_switch.evaluate_kill_switch` on the simulated returns; a locked rebalance freezes members (exits pass).
  `live_parity.build_live_member_weight_fn` is the live per-member chain (dynamic sizing, liquidity gate, reduce_size,
  net-edge gate + cost multiplier, book weight floor, analyzer verdicts) built from `main.py`'s own pure functions;
  `build_live_mechanisms(config, frame)` assembles all of it. Almgren impact is now a rate on each name's traded notional.
- `fill_price_audit.py` / `aq evaluate --audit-fills` — fills vs the dataset open and vs the Lean zip's own open.
- `backtest_audit` — limit-order age in weekday sessions (`--max-open-sessions`), `load_book_history` reads the per-run
  files, runs are selected by `run_id`. `rank_ic_core.newey_west_t_stat` — HAC t for daily IC series.
- `rank_signal_calibration.calibrate_book_confidence_spread(candidate_metadata_by_ticker=, session_asset_class=)` — the
  floor is calibrated on the pool live selects from.
- Lever / gate research (scripts): `scripts/as_live_levers.py` (`AsLiveHarness`, cached scoring) and `scripts/gate_research.py`
  (R-GATE on both splits).

## CLI

`aq evaluate` (see the root README's CLI Reference for full flag
descriptions):

- Simulation: `--rank-book`, `--capacity`, `--stress`, `--all` (bundles
  the three plus `--calibrate-edge` and `--benchmarks`)
- Benchmarks (V5.4.4): `--benchmarks` (strategy + public baselines,
  README section + webui panel refresh)
- Calibration: `--calibrate-edge`, `--calibrate-book-spread`,
  `--calibrate-confidence-threshold`
- Reconciliation: `--reconcile-book-history`, `--replay-hysteresis`,
  `--reconcile-features` (V5.3.5.3, requires `--symbol`)
- Monte Carlo (V5.3.8): `--rank-book --monte-carlo`
  (`--mc-runs/--mc-block-size/--mc-seed/--mc-method`)
- Diagnostics/investigation (not in `--all`): `--ablation`,
  `--replay-kill-switch` (V5.2.8), `--simulate-limit-fills` (V5.3.1,
  `--limit-fill-offset-sweep`), `--walk-forward-summary`

Writes `ml/evaluation/*.json`, consumed by `monitoring/evaluation_state.py`
for the webui's Evaluation tab (`/api/evaluation`).

## Config

`phase1.target.ranking.net_performance` (book/cost parameters) and
`phase_v2.costs` (the entry-decision net-edge gate, `execution/cost_model.py`
— off by default until calibrated via `aq evaluate --calibrate-edge`).

## Known finding (development/Problems.md)

Running `aq evaluate --rank-book` against the live-trained artifacts during
development surfaced, in real predictions, the compression this repo's own
Problems.md documents: `rank_20d` predictions clustered in roughly
`[0.5, 0.7]` instead of spanning `[0, 1]` — direct evidence of the rank
heads' sigmoid-at-inference/raw-at-training mismatch. `IC` is invariant
under any monotone transform, which is exactly why no rank-IC-based gate
ever caught it; this package's net-Sharpe simulation is sensitive to the
compressed dispersion in a way IC is not.

## V5.8.0 additions (Problems.md #156-#174)

- `class_ic_audit.py` (`aq evaluate --ic-by-class`) — pooled vs within-class vs between-class rank IC with HAC t, so a pooled edge can be told apart from a class-timing bet.
- `gate_audit.py` (`--audit-gates`) — the rolling-IC gate's own reading next to the realised IC: veto share by reason, false-veto share, the gate's lag; it self-checks on synthetic constant-IC data.
- `head_audit.py` (`--audit-heads`) — the R-HEAD table: every head and submodel, its own gate verdict, and whether the live path reads it.
- `feature_quality_audit.py` (`--audit-features`) — per-feature IC per class, constant-per-class share and ticker-ID / leak suspects.
- `audit_runners.py` — loads the inputs the way the live path sees them for the four flags above (heavy imports stay lazy).
- `ml_cleanup.py` (`aq clean ml`) — a dry-run disk plan for `ml/versions` and `ml/_backup_*`; nothing is deleted without `--apply`, and the installed models are always protected.
- `backtest_audit.py` — `class_by_ticker` splits P&L by the config's asset class (bond ETFs are Lean equities), `period_summary` backs `--audit-backtest --period START..END` (BT2 spans the backtest split and the holdout).
- `live_parity.py` — `topology_inputs_fn` feeds the learned-topology sizing multiplier into the as-live run; `late_bar_offline_row` / `LATE_BAR_SAME_ROW_FEATURE_PREFIXES` say which dataset row a crypto or forex snapshot belongs to (own-price block = previous row, cross-asset block = the tick's row).

## V6.1.0 additions

- `rank_book_simulator.py` — new options, all off by default and replicas of `main.py` mechanisms (rule R-CAL2): `mid_cycle_member_updates` (the daily member pass between rebalances), `accrue_skipped_dates` (weekend crypto), `kill_switch_extra_returns` (P&L outside the simulation that live's whole-portfolio kill switch reads), `legacy_component` (the legacy probability signal on non-members, per-component returns in `per_date_component_returns`) and `max_active_positions`; exit costs of an age / stop / guard exit are now charged on a rebalance date too.
- `live_parity.py` — `build_live_member_weight_fn(use_live_analyzer=True)` ends in `analyzer.market_analyzer.build_market_analysis_decision` itself and can size a legacy-signal entry; the risk-off override reads `phase_v2.regime_detection` (a key that did not exist was read before).
- `lean_attribution.py` — a position belongs to the component that **opened** it (`opener_members_by_date`); the per-day view stays as `components_by_membership`.
- `model_predictions.py` — `predict_heads_ensemble`: the seed-ensemble mean of each head (NaN where any member is NaN).
- `readme_research.py` — reads the V6 decisions and the shipped config (no settings typed here) and renders the R-CAL2 and rule-chain results.

## V6.3.0 additions

- `backtest_statistics.py` (`aq evaluate --backtest-stats`) — the README's Backtest Statistics for one Lean run (López de Prado, AFML ch. 14): general characteristics (AUM, leverage, bets, holding period, turnover, SPY correlation), performance (PnL by side, hit ratio, time-weighted return), runs (HHI of returns and of bet timing, 95th-percentile drawdown and time under water), implementation shortfall (fees and slippage per turnover, return on execution costs), efficiency (PSR, deflated Sharpe over the trial registry), classification scores and risk / return per asset class. Each row has a portfolio value and a strategy value (the run without its T-bill sweep); an uncomputable metric carries a `reason`, never a number.
- `readme_statistics.py` — renders those sections from `ml/evaluation/backtest_statistics.json`; `LEAN_STAT_SECTION` gives every Lean statistic its section.
- `lean_report.py` (`aq evaluate --lean-report`, run by `aq backtest`) — the order of the run-folder tools; `aq_cli._run_lean_report` runs each step best-effort.
- `backtest_audit.py` — `class_by_ticker_from_config` files the cash-sweep ticker as its own class `cash_sweep` (it was ~0.8 of NAV inside "equity").
- `fill_price_audit.py` — `zip_opens_for_fills` (shared with the slippage metric); fills carry their quantity.
- `rank_book_simulator.py` / `kill_switch_replay.py` — carry the kill switch's `release_rolling_sharpe` band state bar to bar, as `main.py` does (rule R-KILL).
- `readme_research.py` — R-CAL3 replaces R-CAL2's table once `v630/calibration.json` exists; the V6.3.0 rule chain table.

## V6.4.0 additions

- `classification_parity.py` (`aq evaluate --classification-parity`, step of `--lean-report`) — a Lean run's logged book-call probabilities against the same `direction_20d` head scored offline on the same (date, ticker) calls (late-bar names on the previous row, as live decides them); rule R-L11's tolerance: |accuracy delta|, |neg log-loss delta| <= 0.01, median |probability gap| <= 0.005.
- `paper_protocol.py` (`aq evaluate --paper-check`) — the paper-period checklist of a run folder (veto rate, lock share, exposure, fills, slippage, fee bps, strategy and sweep P&L per day, hit ratio, turnover) and the 5-95% bands of every contiguous 6-rebalance window of a reference run; success = every metric inside its band, >= 6 rebalances, >= 120 days.
- `probability_calibration.py` — reliability curve, ECE, Brier, log-loss, temperature scaling, isotonic regression (pool adjacent violators), per-class thresholds and cross-fitted log-loss for the direction heads (lead L2).
- `engaged_day_skill.py` — rank IC, top/bottom spread and as-live Sharpe on the dates the rolling-IC gate engages against all dates, and the owner's bar (+0.02 IC, +0.15 Sharpe on both splits; lead L1).
- `trade_bootstrap.py` — bootstrap of a sleeve's round-trip P&L, top-k share and leave-one-name-out (lead L9).
- `backtest_statistics.py` — `lean_book_calls` + `_classification_section`: the Lean row of Classification Scores gets a log-loss when the book history logged `member_probabilities`.
- `rank_book_simulator.py` — `sector_relative_rank`, `partial_adjust_fraction` and `rank_overlay_fn` (default off, each calling the function live uses); the kill switch carries `trip_confirm_bars`' counter. `kill_switch_replay.py` — `forward_window_returns` / `false_lock_share` (a lock before the unlocked book's top-third 20-day return).
