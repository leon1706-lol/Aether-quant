"""Backtests, grouped by the job (V6.6.5): `backtest()` for any weights on any prices, the project's own rank-book and
target-weights simulators, Lean-exact statistics and Monte Carlo."""

from aether_quant.evaluation import MarketPanel, lean_statistics, run_monte_carlo, simulate_rank_book, simulate_target_weights
from evaluation.backtest_api import BacktestResult, backtest, summary_statistics

__all__ = ["BacktestResult", "MarketPanel", "backtest", "lean_statistics", "run_monte_carlo", "simulate_rank_book", "simulate_target_weights", "summary_statistics"]
