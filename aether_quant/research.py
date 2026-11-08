"""Research and audit tools (V6.4.3): one report for any signal, the probability of backtest overfitting, factor
baselines and spanning, overfitting and leakage audits, the simulator / Lean gap, research probes, the trial registry."""

from evaluation.factor_spanning import FACTOR_COLUMNS, build_factor_returns, build_factor_scores, factor_spanning
from evaluation.leakage_audit import audit_leakage, identity_check, label_shuffle_check, single_feature_ic, tail_nan_check
from evaluation.overfit_diagnostics import head_ic, learning_curve, training_gap_report
from evaluation.pbo import probability_of_backtest_overfitting
from evaluation.research_harness import block_bootstrap_mean_ci, evaluate_signal, ic_summary
from evaluation.research_probes import fit_hgb_rank, fit_ridge_rank, load_research_frame, predict_scores
from evaluation.sim_lean_calibration import daily_gap_breakdown, gap_report, rung_attribution
from evaluation.trial_registry import build_registry, collect_trials, dedupe
from evaluation.premia_research import ResearchContext, annual_sharpe, build_context, max_drawdown, nulls_for, passes_sharpe_clauses, phase_offsets, placebo_p_value, placebo_sharpes, score_sleeve, selection_gate, weights_for
from evaluation.alpha_proof import (
    alpha_proof_report,
    alpha_regression,
    benchmark_daily_returns,
    deflated_sharpe_from_inputs,
    fresh_sessions,
    measured_annualization,
    period_report,
    r_alpha1,
    sharpe,
    sharpe_bootstrap_ci,
    strategy_daily_returns,
    to_sessions,
    window_report,
)
from evaluation.trial_ledger import append_trial, candidate_ids, deflation_inputs, legacy_trials, read_ledger
from evaluation.wide_context import WideCell, crypto_cell, daily_returns_for, equity_cell, liquid_mask_for_cell, path_config, sharpe_at_sessions, signal_ic_t, slice_market

from evaluation.wide_context import calendar_rows, crypto_ic, lag_onto, load_ohlcv, load_raw_closes, project_tickers, read_info, wide_config_for

__all__ = [
    "FACTOR_COLUMNS",
    "ResearchContext",
    "WideCell",
    "alpha_proof_report",
    "alpha_regression",
    "annual_sharpe",
    "append_trial",
    "audit_leakage",
    "benchmark_daily_returns",
    "block_bootstrap_mean_ci",
    "build_context",
    "build_factor_returns",
    "build_factor_scores",
    "build_registry",
    "calendar_rows",
    "candidate_ids",
    "collect_trials",
    "crypto_cell",
    "crypto_ic",
    "daily_gap_breakdown",
    "daily_returns_for",
    "dedupe",
    "deflated_sharpe_from_inputs",
    "deflation_inputs",
    "equity_cell",
    "evaluate_signal",
    "factor_spanning",
    "fit_hgb_rank",
    "fit_ridge_rank",
    "fresh_sessions",
    "gap_report",
    "head_ic",
    "ic_summary",
    "identity_check",
    "label_shuffle_check",
    "lag_onto",
    "learning_curve",
    "legacy_trials",
    "liquid_mask_for_cell",
    "load_ohlcv",
    "load_raw_closes",
    "load_research_frame",
    "max_drawdown",
    "measured_annualization",
    "nulls_for",
    "passes_sharpe_clauses",
    "path_config",
    "period_report",
    "phase_offsets",
    "placebo_p_value",
    "placebo_sharpes",
    "predict_scores",
    "probability_of_backtest_overfitting",
    "project_tickers",
    "r_alpha1",
    "read_info",
    "read_ledger",
    "rung_attribution",
    "score_sleeve",
    "selection_gate",
    "sharpe",
    "sharpe_at_sessions",
    "sharpe_bootstrap_ci",
    "signal_ic_t",
    "single_feature_ic",
    "slice_market",
    "strategy_daily_returns",
    "tail_nan_check",
    "to_sessions",
    "training_gap_report",
    "weights_for",
    "wide_config_for",
    "window_report",
]
