"""Cost-aware offline simulation of the cross-sectional rank book (V5.1
Phase 0). Reuses the EXACT selection/neutrality machinery main.py's live
decision path uses - portfolio.book_construction.build_rank_based_book()
and portfolio.book_neutrality.apply_book_neutrality() - so this module's
numbers are the offline mirror of live behavior, not an independently
re-derived approximation. Both of those are pure Python/dataclasses (no
torch, no pandas), so importing them here does not compromise this
package's torch-free contract (see evaluation/__init__.py's docstring).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace

import numpy as np
import pandas as pd

from portfolio.book_construction import BookAllocation, build_rank_based_book
from portfolio.book_neutrality import apply_book_neutrality

DEFAULT_SECTOR_MAX_NET_WEIGHT = 0.05


@dataclass(frozen=True)
class RankBookSimulationResult:
    gross_sharpe: float
    net_sharpe: float
    gross_total_return: float
    net_total_return: float
    net_max_drawdown: float
    annualized_turnover: float
    cost_drag_annual_bps: float
    num_rebalances: int
    num_dates_used: int
    mean_names_long: float
    mean_names_short: float
    per_date_net_return: list = field(default_factory=list)
    per_date: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _annualized_sharpe(returns: np.ndarray, trading_days_per_year: int) -> float:
    """Same convention as train.py::compute_strategy_metrics() -
    (mean/std) * sqrt(trading_days_per_year) - kept identical so this
    simulator's Sharpe is directly comparable to every other Sharpe number
    already reported by this codebase."""
    if len(returns) < 2:
        return 0.0
    std = float(returns.std(ddof=1))
    if std <= 0.0:
        return 0.0
    return float(returns.mean() / std) * math.sqrt(trading_days_per_year)


def _empty_result(trading_days_per_year: int) -> RankBookSimulationResult:
    return RankBookSimulationResult(
        gross_sharpe=0.0,
        net_sharpe=0.0,
        gross_total_return=0.0,
        net_total_return=0.0,
        net_max_drawdown=0.0,
        annualized_turnover=0.0,
        cost_drag_annual_bps=0.0,
        num_rebalances=0,
        num_dates_used=0,
        mean_names_long=0.0,
        mean_names_short=0.0,
        per_date_net_return=[],
        per_date=[],
    )


def _simulate_rank_book_core(
    frame: pd.DataFrame,
    *,
    prediction_column: str,
    forward_return_column: str = "target_return_1d",
    ticker_column: str = "ticker",
    date_column: str = "date",
    top_n: int,
    bottom_n: int,
    rebalance_every_bars: int,
    cost_bps_per_side: float,
    commission_bps: float,
    gross_exposure: float,
    dollar_neutral: bool,
    sector_neutral: bool,
    sector_by_ticker: dict[str, str] | None = None,
    hysteresis_rank_margin: float = 0.0,
    max_weight_per_name: float,
    min_universe_size: int = 20,
    sector_max_net_weight: float = DEFAULT_SECTOR_MAX_NET_WEIGHT,
    trading_days_per_year: int = 252,
) -> tuple[RankBookSimulationResult, dict[str, int]]:
    """The real implementation, shared by simulate_rank_book() (public,
    returns just the result) and capacity_curve() (needs held_days_by_ticker
    too, to estimate which held name is the liquidity bottleneck). See
    simulate_rank_book()'s docstring for the full parameter/behavior
    contract - this function is not itself part of the public API.

    Per date, in sorted order: dates with fewer than min_universe_size
    eligible (non-NaN prediction AND forward-return) rows are SKIPPED
    entirely (no selection, no return accrual) - same convention as
    train.py::build_cross_sectional_rank_targets()'s min_universe_size
    gate; the book silently carries over across a skipped date, as if it
    did not exist for accounting purposes. On a rebalance date (every
    rebalance_every_bars-th non-skipped date, first date always rebalances),
    predictions are handed to build_rank_based_book() (with hysteresis
    against the previous allocation) for top/bottom-N selection, each leg
    is equal-weighted to gross_exposure/2, then apply_book_neutrality()
    applies the sector/dollar/gross constraints. Cost
    (cost_bps_per_side + commission_bps, in bps) is charged on the turnover
    of that single rebalance event only - held-and-unchanged positions
    between rebalances accrue zero cost, matching main.py's own
    hold-until-next-rebalance contract (portfolio/book_construction.py::
    should_rebalance_this_bar())."""
    sector_by_ticker = sector_by_ticker or {}
    working = frame.dropna(subset=[prediction_column]).copy()
    unique_dates = sorted(working[date_column].unique())

    held_weights: dict[str, float] = {}
    held_allocations: dict[str, BookAllocation] = {}
    held_days_by_ticker: dict[str, int] = {}

    gross_returns: list[float] = []
    net_returns: list[float] = []
    per_date_used: list = []
    names_long_series: list[int] = []
    names_short_series: list[int] = []
    total_turnover = 0.0
    total_cost_return = 0.0
    num_rebalances = 0
    rebalance_counter = 0

    net_cumprod = 1.0
    gross_cumprod = 1.0
    net_running_peak = 1.0
    net_max_drawdown = 0.0

    for date in unique_dates:
        date_frame = working[working[date_column] == date]
        eligible = date_frame.dropna(subset=[forward_return_column])
        if len(eligible) < min_universe_size:
            continue

        is_rebalance = (rebalance_counter % max(1, rebalance_every_bars)) == 0
        rebalance_counter += 1
        cost_this_date = 0.0

        if is_rebalance:
            book_candidates = {
                str(ticker): {"predicted_rank_20d": float(rank), "trading_eligible": True, "asset_class": None}
                for ticker, rank in zip(eligible[ticker_column], eligible[prediction_column])
            }
            allocations = build_rank_based_book(
                book_candidates,
                top_n=top_n,
                bottom_n=bottom_n,
                min_rank_confidence_spread=0.0,
                previous_allocations=held_allocations or None,
                hysteresis_rank_margin=hysteresis_rank_margin,
            )

            if allocations:
                long_symbols = [symbol for symbol, allocation in allocations.items() if allocation.role == "long"]
                short_symbols = [symbol for symbol, allocation in allocations.items() if allocation.role == "short"]
                raw_weights: dict[str, float] = {}
                if long_symbols:
                    per_name = (gross_exposure / 2.0) / len(long_symbols)
                    raw_weights.update({symbol: per_name for symbol in long_symbols})
                if short_symbols:
                    per_name = (gross_exposure / 2.0) / len(short_symbols)
                    raw_weights.update({symbol: -per_name for symbol in short_symbols})

                new_weights, _diagnostics = apply_book_neutrality(
                    raw_weights,
                    sector_by_symbol=sector_by_ticker,
                    dollar_neutral=dollar_neutral,
                    sector_neutral=sector_neutral,
                    gross_exposure_cap=gross_exposure,
                    max_weight_per_name=max_weight_per_name,
                    sector_max_net_weight=sector_max_net_weight,
                )
                held_allocations = {
                    symbol: replace(allocation, target_weight=new_weights.get(symbol, 0.0))
                    for symbol, allocation in allocations.items()
                }
            else:
                new_weights = {}
                held_allocations = {}

            all_symbols = set(new_weights) | set(held_weights)
            turnover_this_rebalance = sum(
                abs(new_weights.get(symbol, 0.0) - held_weights.get(symbol, 0.0)) for symbol in all_symbols
            )
            total_turnover += turnover_this_rebalance
            cost_this_date = turnover_this_rebalance * (cost_bps_per_side + commission_bps) / 1e4
            total_cost_return += cost_this_date
            num_rebalances += 1
            held_weights = new_weights

        for symbol in held_weights:
            held_days_by_ticker[symbol] = held_days_by_ticker.get(symbol, 0) + 1
        names_long_series.append(sum(1 for weight in held_weights.values() if weight > 0.0))
        names_short_series.append(sum(1 for weight in held_weights.values() if weight < 0.0))

        date_returns = dict(zip(eligible[ticker_column], eligible[forward_return_column]))
        bar_return = sum(
            weight * float(date_returns.get(symbol, 0.0)) for symbol, weight in held_weights.items()
        )
        net_return = bar_return - cost_this_date

        gross_returns.append(bar_return)
        net_returns.append(net_return)
        per_date_used.append(str(date))
        gross_cumprod *= 1.0 + bar_return
        net_cumprod *= 1.0 + net_return
        net_running_peak = max(net_running_peak, net_cumprod)
        net_max_drawdown = min(net_max_drawdown, net_cumprod / net_running_peak - 1.0)

    if not per_date_used:
        return _empty_result(trading_days_per_year), held_days_by_ticker

    num_dates_used = len(per_date_used)
    years = num_dates_used / trading_days_per_year
    gross_array = np.asarray(gross_returns, dtype=float)
    net_array = np.asarray(net_returns, dtype=float)

    result = RankBookSimulationResult(
        gross_sharpe=_annualized_sharpe(gross_array, trading_days_per_year),
        net_sharpe=_annualized_sharpe(net_array, trading_days_per_year),
        gross_total_return=float(gross_cumprod - 1.0),
        net_total_return=float(net_cumprod - 1.0),
        net_max_drawdown=float(net_max_drawdown),
        annualized_turnover=float(total_turnover / years) if years > 0 else 0.0,
        cost_drag_annual_bps=float(total_cost_return / years * 10_000.0) if years > 0 else 0.0,
        num_rebalances=num_rebalances,
        num_dates_used=num_dates_used,
        mean_names_long=float(np.mean(names_long_series)) if names_long_series else 0.0,
        mean_names_short=float(np.mean(names_short_series)) if names_short_series else 0.0,
        per_date_net_return=[float(value) for value in net_returns],
        per_date=per_date_used,
    )
    return result, held_days_by_ticker


def simulate_rank_book(frame: pd.DataFrame, **kwargs) -> RankBookSimulationResult:
    """Public entry point - see _simulate_rank_book_core()'s docstring for
    the full algorithm. Discards held_days_by_ticker (only capacity_curve()
    needs it)."""
    result, _held_days_by_ticker = _simulate_rank_book_core(frame, **kwargs)
    return result


def capacity_curve(
    frame: pd.DataFrame,
    *,
    dollar_volume_column: str = "liquidity_log_dollar_volume",
    participation_cap: float,
    base_kwargs: dict,
    top_n_sweep: list[int],
) -> dict:
    """Breadth + capacity check (V5.1 Phase 0, an addition beyond the
    original roadmap table - see the V5.1 plan's own §1 "one thing missing
    from the list"): sweeps top_n==bottom_n across top_n_sweep, holding
    every other simulate_rank_book() kwarg fixed via base_kwargs, so a
    rank-IC concentrated in a handful of names (net_sharpe collapses as
    top_n shrinks toward the extreme) is visibly distinguishable from one
    genuinely spread across the cross-section.

    capacity_usd is a deliberately simple, honestly-approximate estimate,
    not a precision claim: among names actually held during the BASE run
    (base_kwargs's own top_n/bottom_n), the one with the lowest average
    dollar volume (dollar_volume_column, already a LOG value - exponentiated
    back here) is the binding constraint; scaling its average dollar volume
    by participation_cap and by the number of held names gives a rough
    total-book capacity ceiling. binding_ticker names exactly which held
    name limits it, so this is auditable rather than a black-box number."""
    per_top_n: list[dict] = []
    base_held_days: dict[str, int] | None = None
    base_top_n = base_kwargs.get("top_n")

    for n in top_n_sweep:
        sweep_kwargs = dict(base_kwargs)
        sweep_kwargs["top_n"] = n
        sweep_kwargs["bottom_n"] = n
        result, held_days = _simulate_rank_book_core(frame, **sweep_kwargs)
        per_top_n.append({"top_n": n, "net_sharpe": result.net_sharpe})
        if n == base_top_n:
            base_held_days = held_days

    if base_held_days is None:
        _, base_held_days = _simulate_rank_book_core(frame, **base_kwargs)

    if not base_held_days:
        return {"capacity_usd": 0.0, "binding_ticker": None, "per_top_n": per_top_n}

    ticker_column = base_kwargs.get("ticker_column", "ticker")
    avg_log_dollar_volume = frame.groupby(ticker_column)[dollar_volume_column].mean()
    held_avg_dollar_volume = {
        ticker: float(np.exp(avg_log_dollar_volume.get(ticker, 0.0))) for ticker in base_held_days
    }
    if not held_avg_dollar_volume:
        return {"capacity_usd": 0.0, "binding_ticker": None, "per_top_n": per_top_n}

    binding_ticker = min(held_avg_dollar_volume, key=held_avg_dollar_volume.get)
    capacity_usd = float(held_avg_dollar_volume[binding_ticker] * participation_cap * len(held_avg_dollar_volume))
    return {"capacity_usd": capacity_usd, "binding_ticker": binding_ticker, "per_top_n": per_top_n}


def stress_test_costs(frame: pd.DataFrame, *, base_kwargs: dict, cost_multipliers: tuple = (1.0, 2.0, 3.0)) -> list[dict]:
    """One simulate_rank_book() run per cost multiplier, scaling BOTH
    cost_bps_per_side and commission_bps - answers "does the edge survive
    if real-world costs turn out to be 2x/3x the calibrated estimate",
    the robustness check item 12 of the V5.1 roadmap asks for."""
    results = []
    for multiplier in cost_multipliers:
        stressed_kwargs = dict(base_kwargs)
        stressed_kwargs["cost_bps_per_side"] = float(base_kwargs.get("cost_bps_per_side", 0.0)) * multiplier
        stressed_kwargs["commission_bps"] = float(base_kwargs.get("commission_bps", 0.0)) * multiplier
        result = simulate_rank_book(frame, **stressed_kwargs)
        results.append({"cost_multiplier": multiplier, **result.to_dict()})
    return results


def _bootstrap_mean_confidence_interval(
    values: list[float], n_resamples: int = 2000, confidence: float = 0.95, seed: int = 42
) -> dict:
    """Torch-free duplicate of train.py::bootstrap_ic_confidence_interval()'s
    resample-with-replacement bootstrap over a plain float series - same
    algorithm and defaults, deliberately reimplemented here (not imported)
    since train.py imports torch and this package must stay torch-free (see
    evaluation/__init__.py's docstring)."""
    if not values:
        return {"lower_bound": 0.0, "upper_bound": 0.0, "mean": 0.0}
    rng = np.random.default_rng(seed)
    array = np.asarray(values, dtype=float)
    resampled_means = np.empty(n_resamples)
    for i in range(n_resamples):
        resampled_means[i] = rng.choice(array, size=len(array), replace=True).mean()
    alpha = (1.0 - confidence) / 2.0
    return {
        "lower_bound": float(np.quantile(resampled_means, alpha)),
        "upper_bound": float(np.quantile(resampled_means, 1.0 - alpha)),
        "mean": float(array.mean()),
    }


def summarize_metric_stability(per_window_values: list[float], *, min_windows: int, max_sign_flip_fraction: float) -> dict:
    """Cross-window stability summary (used by Phase 4's walk-forward
    evaluation and Phase 5's ablation) - mirrors
    train.py::assess_ranking_quality()'s era-sign-instability check, one
    level up: a window whose sign disagrees with the overall mean's sign is
    a "flip", same concept as an opposite-sign era. num_windows below
    min_windows or a sign-flip fraction above max_sign_flip_fraction both
    fail "stable"."""
    values = [float(value) for value in per_window_values]
    num_windows = len(values)
    if num_windows == 0:
        return {
            "num_windows": 0, "mean": 0.0, "sign_flip_fraction": 0.0, "stable": False,
            "failures": ["no_windows"], "bootstrap": _bootstrap_mean_confidence_interval([]),
        }

    mean_value = float(np.mean(values))
    overall_positive = mean_value >= 0.0
    flips = sum(1 for value in values if (value >= 0.0) != overall_positive)
    sign_flip_fraction = flips / num_windows

    failures = []
    if num_windows < min_windows:
        failures.append("insufficient_windows")
    if sign_flip_fraction > max_sign_flip_fraction:
        failures.append("sign_flip_fraction_above_gate")

    return {
        "num_windows": num_windows,
        "mean": mean_value,
        "sign_flip_fraction": sign_flip_fraction,
        "stable": not failures,
        "failures": failures,
        "bootstrap": _bootstrap_mean_confidence_interval(values),
    }
