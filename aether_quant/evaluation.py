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

__all__ = [
    "RankBookSimulationResult",
    "bootstrap_mean_pnl",
    "deflated_sharpe_ratio",
    "drawdown_episodes",
    "expected_max_sharpe",
    "lean_statistics",
    "newey_west_t_stat",
    "probabilistic_sharpe_ratio",
    "rank_ic_from_arrays",
    "run_monte_carlo",
    "sharpe_ratio",
    "simulate_rank_book",
    "summarize_metric_stability",
]
