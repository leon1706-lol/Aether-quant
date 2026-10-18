"""Lean's portfolio statistics, reproduced from a backtest result (V6.2.0).

Lean's Sharpe ratio is (AnnualPerformance - average risk-free rate) / AnnualStandardDeviation, where (Lean source,
Common/Statistics/Statistics.cs, StatisticsBuilder.cs, PortfolioStatistics.cs, Common/Data/InterestRateProvider.cs):

  * the daily performance list is the result's "Strategy Equity / Return" series in percent, first two points dropped,
    every calendar day it holds (a portfolio with crypto has weekend points);
  * AnnualPerformance = (1 + mean)^N - 1 and AnnualVariance = sample variance x N, N = `tradingDaysPerYear`;
  * the risk-free rate is the mean of the filled-forward primary credit rate
    (data/alternative/interest-rate/usa/interest-rate.csv, percent) over every equity-curve sample (several a day);
  * Sortino uses the annual variance of the returns below 0; PSR the observed (daily) Sharpe with skew / kurtosis.

This reproduces Lean's printed statistics exactly (V6.1 BT1: -1.673), so a counterfactual - a refreshed risk-free
file, another day count, extra daily returns such as a T-bill sweep's - can be priced before a Lean run is spent.
Stdlib + math only.
"""

from __future__ import annotations

import bisect
import json
import math
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

DEFAULT_RISK_FREE_RATE = 0.01  # InterestRateProvider.DefaultRiskFreeRate, used before the file's first row


def load_backtest_series(result_path: str | Path) -> dict:
    """The daily performance list (fractions, Lean's own preprocessing) and the equity dates of one Lean result JSON."""
    result = json.loads(Path(result_path).read_text(encoding="utf-8"))
    series = result["charts"]["Strategy Equity"]["series"]
    returns = [(_utc_date(point[0]), float(point[1]) / 100.0) for point in series["Return"]["values"] if point[1] is not None]
    # every equity sample, duplicates included: Lean averages the rate over the equity curve's points, not its days
    equity_dates = [_utc_date(point[0]) for point in series["Equity"]["values"]]
    configuration = result.get("algorithmConfiguration") or {}
    return {
        "performance": [value for _day, value in returns[2:]],
        "performance_dates": [day for day, _value in returns[2:]],
        "equity_dates": equity_dates,
        "trading_days_per_year": int(configuration.get("tradingDaysPerYear") or 252),
        "statistics": result.get("statistics", {}),
    }


def _utc_date(timestamp: float) -> date:
    return datetime.fromtimestamp(float(timestamp), UTC).date()


def load_interest_rate_changes(path: str | Path) -> list[tuple[date, float]]:
    """(date, rate as a fraction) rows of Lean's interest-rate file, sorted; a header or malformed row is skipped."""
    changes = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(",")
        if len(parts) < 2:
            continue
        try:
            changes.append((date.fromisoformat(parts[0].strip()), float(parts[1]) / 100.0))
        except ValueError:
            continue
    return sorted(changes)


def rate_on(day: date, changes: Sequence[tuple[date, float]]) -> float:
    """The rate in force on `day`: the last change on or before it (filled forward past the file's end)."""
    position = bisect.bisect_right([change_day for change_day, _rate in changes], day) - 1
    if position < 0:
        return changes[0][1] if changes else DEFAULT_RISK_FREE_RATE
    return changes[position][1]


def average_risk_free_rate(days: Iterable[date], changes: Sequence[tuple[date, float]]) -> float:
    days = list(days)
    if not days:
        return 0.0
    keys = [change_day for change_day, _rate in changes]
    total = 0.0
    for day in days:
        position = bisect.bisect_right(keys, day) - 1
        total += changes[max(position, 0)][1] if changes else DEFAULT_RISK_FREE_RATE
    return total / len(days)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _sample_variance(values: Sequence[float]) -> float:
    if len(values) < 2:
        return float("nan")
    mean = _mean(values)
    return sum((value - mean) ** 2 for value in values) / (len(values) - 1)


def _annual_variance(values: Sequence[float], days: int) -> float:
    variance = _sample_variance(values)
    return 0.0 if not math.isfinite(variance) or variance == 0.0 else variance * days


def _skewness(values: Sequence[float]) -> float:
    n = len(values)
    if n < 3:
        return float("nan")
    mean, sd = _mean(values), math.sqrt(_sample_variance(values))
    if sd == 0.0:
        return float("nan")
    return n / ((n - 1) * (n - 2)) * sum(((value - mean) / sd) ** 3 for value in values)


def _excess_kurtosis(values: Sequence[float]) -> float:
    n = len(values)
    if n < 4:
        return float("nan")
    mean, sd = _mean(values), math.sqrt(_sample_variance(values))
    if sd == 0.0:
        return float("nan")
    fourth = sum(((value - mean) / sd) ** 4 for value in values)
    return (n + 1) * n / ((n - 1) * (n - 2) * (n - 3)) * fourth - 3 * (n - 1) ** 2 / ((n - 2) * (n - 3))


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def lean_statistics(
    performance: Sequence[float], equity_dates: Iterable[date], *, trading_days_per_year: int,
    rate_changes: Sequence[tuple[date, float]],
) -> dict:
    """Sharpe, Sortino, PSR and their inputs exactly as Lean computes them; non-finite inputs give 0 like Lean's guards."""
    values = [float(value) for value in performance if value is not None and math.isfinite(float(value))]
    days = int(trading_days_per_year)
    risk_free = average_risk_free_rate(equity_dates, rate_changes)
    annual_return = (1.0 + _mean(values)) ** days - 1.0 if values else 0.0
    annual_std = math.sqrt(_annual_variance(values, days))
    downside_std = math.sqrt(_annual_variance([value for value in values if value < 0.0], days))
    sharpe = 0.0 if annual_std == 0.0 else (annual_return - risk_free) / annual_std
    sortino = 0.0 if downside_std == 0.0 else (annual_return - risk_free) / downside_std
    daily_sd = math.sqrt(_sample_variance(values)) if len(values) > 1 else float("nan")
    observed = 0.0 if not math.isfinite(daily_sd) or daily_sd == 0.0 else (_mean(values) - risk_free / days) / daily_sd
    skew, kurtosis = _skewness(values), _excess_kurtosis(values)
    psr = 0.0
    if len(values) > 1 and math.isfinite(skew) and math.isfinite(kurtosis):
        estimate = (1 - skew * observed + (kurtosis - 1) / 4 * observed**2) / (len(values) - 1)
        if estimate > 0.0:
            psr = _normal_cdf((observed - 1.0 / math.sqrt(days)) / math.sqrt(estimate))
    return {
        "sharpe_ratio": sharpe, "sortino_ratio": sortino, "probabilistic_sharpe_ratio": psr,
        "annual_return": annual_return, "annual_standard_deviation": annual_std, "risk_free_rate": risk_free,
        "trading_days_per_year": days, "observations": len(values),
    }


def with_extra_daily_returns(
    performance: Sequence[float], performance_dates: Sequence[date], extra_by_date: dict[date, float],
) -> list[float]:
    """Counterfactual daily performance: each day's return plus `extra_by_date[day]` (e.g. a sweep's weight x its
    T-bill return, as a fraction of NAV). Additive in return space, which is exact to first order for a small sleeve."""
    return [value + float(extra_by_date.get(day, 0.0)) for value, day in zip(performance, performance_dates)]


def statistics_table(result_path: str | Path, rate_files: dict[str, str | Path], day_counts: Sequence[int] = (252, 365)) -> dict:
    """Lean's printed statistics next to the replica on every (rate file, day count): `aq evaluate --lean-stats`."""
    series = load_backtest_series(result_path)
    rows = {}
    for label, path in rate_files.items():
        changes = load_interest_rate_changes(path)
        for days in day_counts:
            rows[f"{label}/{days}"] = lean_statistics(
                series["performance"], series["equity_dates"], trading_days_per_year=days, rate_changes=changes
            )
    printed = series["statistics"]
    return {
        "lean_printed": {key: printed.get(key) for key in ("Sharpe Ratio", "Sortino Ratio", "Probabilistic Sharpe Ratio",
                                                            "Annual Standard Deviation", "Compounding Annual Return")},
        "run_trading_days_per_year": series["trading_days_per_year"],
        "replica": rows,
    }
