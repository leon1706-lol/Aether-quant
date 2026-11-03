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

__all__ = [
    "FACTOR_COLUMNS",
    "audit_leakage",
    "block_bootstrap_mean_ci",
    "build_factor_returns",
    "build_factor_scores",
    "build_registry",
    "collect_trials",
    "daily_gap_breakdown",
    "dedupe",
    "evaluate_signal",
    "factor_spanning",
    "fit_hgb_rank",
    "fit_ridge_rank",
    "gap_report",
    "head_ic",
    "ic_summary",
    "identity_check",
    "label_shuffle_check",
    "learning_curve",
    "load_research_frame",
    "predict_scores",
    "probability_of_backtest_overfitting",
    "rung_attribution",
    "single_feature_ic",
    "tail_nan_check",
    "training_gap_report",
]
