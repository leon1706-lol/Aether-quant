"""Evaluation statistics: rank IC with honest t-stats, Monte Carlo, Lean-exact Sharpe and PSR, deflated Sharpe and the
cost-aware rank-book simulator."""

from evaluation.backtest_statistics import (
    deflated_sharpe_ratio,
    drawdown_episodes,
    expected_max_sharpe,
    probabilistic_sharpe_ratio,
    sharpe_ratio,
)
from evaluation.lean_statistics import lean_statistics
from evaluation.monte_carlo import run_monte_carlo
from evaluation.rank_book_simulator import RankBookSimulationResult, simulate_rank_book, summarize_metric_stability
from evaluation.rank_ic_core import newey_west_t_stat, rank_ic_from_arrays
from evaluation.trade_bootstrap import bootstrap_mean_pnl
from evaluation.power_analysis import excluded_alpha_sharpe, fundamental_law_ir, minimum_detectable_alpha_sharpe, power_of_t_test, power_table
from evaluation.impact_model import compute_participation_rate, compute_sqrt_impact_bps
from evaluation.probability_calibration import (
    apply_isotonic,
    apply_temperature,
    balanced_accuracy,
    best_threshold_by_class,
    brier_score,
    calibration_report,
    cross_fitted_log_loss,
    expected_calibration_error,
    fit_isotonic,
    fit_temperature,
    log_loss,
    reliability_curve,
)
from evaluation.target_weights_engine import MarketPanel, coinbase_taker_bps, default_fee_usd, load_market_panel, simulate_target_weights
from evaluation.backtest_statistics import (
    bet_starts,
    classification_scores,
    compute_backtest_statistics,
    compute_for_run_dir,
    daily_returns,
    hhi_concentration,
    information_ratio,
    lean_book_calls,
    load_trial_sharpes,
    monthly_counts,
    percentile,
)
from evaluation.lean_verdict import engine_log_status, max_drawdown, r_lean13, r_lean14, strategy_sharpe, verdict_for_run_dirs

__all__ = [
    "MarketPanel",
    "RankBookSimulationResult",
    "apply_isotonic",
    "apply_temperature",
    "balanced_accuracy",
    "best_threshold_by_class",
    "bet_starts",
    "bootstrap_mean_pnl",
    "brier_score",
    "calibration_report",
    "classification_scores",
    "coinbase_taker_bps",
    "compute_backtest_statistics",
    "compute_for_run_dir",
    "compute_participation_rate",
    "compute_sqrt_impact_bps",
    "cross_fitted_log_loss",
    "daily_returns",
    "default_fee_usd",
    "deflated_sharpe_ratio",
    "drawdown_episodes",
    "engine_log_status",
    "excluded_alpha_sharpe",
    "expected_calibration_error",
    "expected_max_sharpe",
    "fit_isotonic",
    "fit_temperature",
    "fundamental_law_ir",
    "hhi_concentration",
    "information_ratio",
    "lean_book_calls",
    "lean_statistics",
    "load_market_panel",
    "load_trial_sharpes",
    "log_loss",
    "max_drawdown",
    "minimum_detectable_alpha_sharpe",
    "monthly_counts",
    "newey_west_t_stat",
    "percentile",
    "power_of_t_test",
    "power_table",
    "probabilistic_sharpe_ratio",
    "r_lean13",
    "r_lean14",
    "rank_ic_from_arrays",
    "reliability_curve",
    "run_monte_carlo",
    "sharpe_ratio",
    "simulate_rank_book",
    "simulate_target_weights",
    "strategy_sharpe",
    "summarize_metric_stability",
    "verdict_for_run_dirs",
]
