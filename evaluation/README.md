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

## CLI

`aq evaluate` (see the root README's CLI Reference for full flag
descriptions):

- Simulation: `--rank-book`, `--capacity`, `--stress`, `--all` (bundles
  the three plus `--calibrate-edge`)
- Calibration: `--calibrate-edge`, `--calibrate-book-spread`,
  `--calibrate-confidence-threshold`
- Reconciliation: `--reconcile-book-history`, `--replay-hysteresis`,
  `--reconcile-features` (V5.3.5.3, requires `--symbol`)
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
