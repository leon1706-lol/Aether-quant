# evaluation

Offline evaluation, audits and the research cycle. Pure numpy and pandas, with no torch, so `performance/`, `retraining/` and the library can import it. CLI: the README's [`aq evaluate`](../README.md#aq-evaluate).

## Reading a finished Lean run

Each reads only the run folder and its data; `aq evaluate --lean-report` runs them in order.

| Module | Answers |
|---|---|
| `backtest_statistics.py` | The README's Backtest Statistics, per portfolio and per strategy |
| `lean_benchmarks.py` | The run against SPY, 60/40, Bitcoin and its own coins, on one calendar |
| `alpha_proof.py` | Is it alpha? Per period: Sharpe interval, alpha with a Newey-West t, deflated Sharpe (R-ALPHA1) |
| `lean_statistics.py` | Lean's Sharpe, Sortino and PSR, replicated exactly |
| `monte_carlo.py` | A block bootstrap into N alternative histories |
| `backtest_audit.py` | Orders: exposure per class, overlaps, holding periods, P&L, vetoes, engine-log teardown |
| `lean_attribution.py` | Daily P&L per ticker and component |
| `fill_price_audit.py` | Fills against the bar's open: cost or price gap? |
| `classification_parity.py` | Logged probabilities against the offline head |
| `lean_verdict.py` | Is a confirming run of an adopted change kept? (R-LEAN rules) |
| `paper_protocol.py` | A paper run against a reference run's bands |
| `lean_report.py` | The plan behind `--lean-report` |
| `readme_statistics.py`, `readme_research.py` | README and research-archive blocks, pure JSON to markdown |

## Simulators

- **`target_weights_engine.py`:** the shipped path's orders, in seconds. Tracks Lean above 0.99 daily correlation.
- **`rank_book_simulator.py`:** the model book, reusing `build_rank_based_book()` and `apply_book_neutrality()`. Also `capacity_curve`, `stress_test_costs`, `summarize_metric_stability`.
- **`live_parity.py`:** the keyword arguments that make it mirror `main.py`: blended head, gates, kill switch, per-member sizing, lag (`--as-live`).
- **Supporting:** `model_predictions.py` (rows through the same interpreter as live), `rolling_ic_series.py`, `impact_model.py` (Almgren), `tranche_book.py`, `trend_sleeve_backtest.py`, `premia_research.py`, `limit_fill_simulator.py`, `kill_switch_replay.py`, `rolling_ic_gate_replay.py`, `ablation.py`.
- **Against Lean:** `sim_lean_calibration.py` and `gate_replica_audit.py` show where the rank-book simulator parts from the engine, which is why its numbers are estimates.

## Research and proof

| Module | What |
|---|---|
| `research_harness.py` | `evaluate_signal()`: one report for any signal (`aq research`) |
| `research_round.py` | A pre-registered round from a rule file (`aq cycle research`) |
| `round_builders.py` | The closed set of table builders a round may name, and the gates applied to them; a round cannot import by string |
| `research_cells.py`, `wide_context.py` | Which data a step may read, enforced in code. Held-out cells refuse without a freeze digest |
| `trial_ledger.py`, `trial_registry.py` | Every scored trial, for the deflated Sharpe's N |
| `pbo.py` | Probability of backtest overfitting (CSCV) |
| `verification_matrix.py` | Every way the project is verified, as data (`aq verify`, `development/verification.md`) |
| `factor_spanning.py`, `factor_neutralization_check.py` | What a signal adds over plain factors; market exposure |
| `power_analysis.py` | What a t-test on an alpha can show, given the history |
| `research_probes.py`, `walk_forward_linear.py` | Small models fitted to measure what the data supports |
| `trade_bootstrap.py` | A repeatable effect, or a few lucky fills? |

## Generations and forward records

- **`generation_registry.py`:** which generations exist, what each may hold, and R-ADMIT1.
- **`generation_ledger.py`:** each generation's forward record and the capital they share.
- **`alpha_decay.py`:** a one-sided CUSUM of net returns against what it was expected to earn.
- **`glide_calibration.py`:** which handover policy loses least to an oracle.
- **`forward_ledger.py`:** a hash-chained record that can't be backfilled.
- **`research_cycle.py`:** what is due, whether a host may train, and scheduling.

## Audits

| Module | Flag |
|---|---|
| `class_ic_audit.py` | `--ic-by-class`: within- and between-class IC |
| `gate_audit.py`, `engaged_day_skill.py` | `--audit-gates`: the rolling-IC gate's vetoes, and skill on engaged days |
| `head_audit.py` | `--audit-heads`: each head against its own gate |
| `feature_quality_audit.py`, `feature_parity.py`, `feature_reconciliation.py` | `--audit-features`, `--reconcile-features`: feature quality and train-versus-live parity |
| `leakage_audit.py`, `overfit_diagnostics.py`, `model_audit.py` | `--audit-leakage`, `--overfit-report`: leakage, IC kept out of sample, what the models could know |

## Baselines and calibration

- **Baselines:** `benchmark_comparison.py`, `public_benchmarks.py` (`--benchmarks`).
- **Calibration:** `rank_signal_calibration.py` (spread, and book-history reconciliation), `confidence_threshold_calibration.py`, `rolling_ic_gate_calibration.py`, `volatility_threshold_calibration.py`, `probability_calibration.py`. Each takes a percentile of a real distribution, not a guess.
- **Core:** `rank_ic_core.py` is the torch-free rank IC and HAC t.
- **Runners:** `audit_runners.py`, `research_runners.py` load only what a flag needs. `ml_cleanup.py` is `aq clean ml`.
