"""Proof of alpha for one finished Lean run (V6.4.4, `aq evaluate --alpha-proof`, rule R-ALPHA1).

The question is whether the strategy (the run without its T-bill carry) earns a return its market exposures do not
explain, beyond what the number of configurations tried would produce by luck. Per period it reports:

  * the annualised Sharpe and its stationary-block-bootstrap 95% interval,
  * the alpha of an OLS of the strategy's daily return on SPY, AGG and BTC daily returns, with a Newey-West t
    (`evaluation.factor_spanning`, the same HAC estimator the factor-spanning test uses),
  * the probabilistic and deflated Sharpe ratios (`evaluation.backtest_statistics`, trials from the registry).

R-ALPHA1 is descriptive - it ships nothing: "demonstrated" iff the full-window alpha t >= 2, the deflated Sharpe >=
0.95, and the alpha is positive in the holdout and in the fresh (never-seen) period, when that period is long enough.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

PERIODS = {
    "backtest": ("2023-07-01", "2025-06-30"),
    "holdout": ("2025-07-01", "2026-11-02"),
}
# V6.5.0 froze its data at 2026-11-02: everything after it was unseen by every rule of that phase, which makes it the forward test.
FRESH_START = "2026-11-03"
MIN_FRESH_POINTS = 5
FORWARD_MIN_POINTS = 60
BENCHMARKS = ("SPY", "AGG", "BTCUSD")


def strategy_daily_returns(run: dict, config: dict, root: Path) -> pd.Series:
    """Daily strategy return (NAV change minus the T-bill sweep's net P&L, over the previous NAV), indexed by the date
    the return ends on - the same series `backtest_statistics.compute_backtest_statistics` calls the strategy."""
    from evaluation.backtest_audit import CASH_SWEEP_CLASS, class_by_ticker_from_config, daily_equity_from_chart
    from evaluation.backtest_statistics import _interval_sums
    from evaluation.lean_attribution import closes_for_universe, daily_ticker_pnl, fills_from_order_events

    points = daily_equity_from_chart(run["result"])
    dates = [day for day, _ in points]
    nav = [value for _, value in points]
    if len(nav) < 3:
        return pd.Series(dtype=float)
    class_by_ticker = class_by_ticker_from_config(config)
    sweep = {ticker for ticker, kind in class_by_ticker.items() if kind == CASH_SWEEP_CLASS}
    forex = {ticker for ticker, kind in class_by_ticker.items() if kind == "forex"}
    fills = fills_from_order_events(run.get("order_events", []))
    closes = closes_for_universe(config, root, {fill.ticker for fill in fills})
    ticker_pnl = daily_ticker_pnl(fills, closes, dates, forex)
    sweep_by_day = {day: sum(e["pnl"] - e["fee"] for t, e in tickers.items() if t in sweep) for day, tickers in ticker_pnl.items()}
    carry = _interval_sums(sweep_by_day, dates)
    returns = {}
    for index, (before, after, sweep_pnl) in enumerate(zip(nav, nav[1:], carry), start=1):
        if before > 0.0:
            returns[dates[index]] = ((after - before) - sweep_pnl) / before
    return pd.Series(returns, dtype=float).sort_index()


def benchmark_daily_returns(root: Path, config: dict, tickers=BENCHMARKS, *, start: str, end: str, data_dir: str = "data") -> pd.DataFrame:
    """Session-calendar daily returns of the benchmark tickers from their config zips: the calendar is the first
    ticker's (SPY, US equity sessions); a ticker that also trades on other days (BTC) is priced at its last close on or
    before each session, so every column spans the same session-to-session interval. Tickers not in the universe are
    left out."""
    from data_pipeline.data_audit import asset_zip_paths, read_lean_daily_zip

    assets = {str(asset["ticker"]): asset for asset in config["phase1"]["universe"]["assets"]}
    closes = {}
    for ticker in tickers:
        asset = assets.get(ticker)
        if asset is None:
            continue
        frame = read_lean_daily_zip(asset_zip_paths(asset, Path(root) / data_dir)["trade"], str(asset.get("security_type")))
        series = frame.set_index(frame["date"].dt.strftime("%Y-%m-%d"))["close"].astype(float).sort_index()
        # A crypto or forex bar dated D ends at the midnight after the equity close of D, so a run's daily sample of D holds the bar
        # dated before it. On the bar's own date this column led the strategy by a day, which hid a crypto book's beta and
        # booked it as alpha (a long-only crypto sleeve's t read 2.76, and 1.30 aligned).
        closes[ticker] = series.shift(1).dropna() if str(asset.get("security_type")) in ("crypto", "forex") else series
    if not closes:
        return pd.DataFrame()
    sessions = closes[next(iter(closes))].index
    table = pd.DataFrame({ticker: series.reindex(series.index.union(sessions)).ffill().reindex(sessions)
                          for ticker, series in closes.items()})
    returns = table.pct_change()
    return returns[(returns.index >= start) & (returns.index <= end)]


def to_sessions(daily: pd.Series, sessions) -> pd.Series:
    """Compounds a calendar-daily return series onto `sessions`: each session gets every return dated after the previous
    session and up to itself (weekend crypto moves land on Monday, as they do in a session-based benchmark)."""
    sessions = sorted(str(day) for day in sessions)
    if not sessions or daily.empty:
        return pd.Series(dtype=float)
    position = np.searchsorted(np.asarray(sessions), np.asarray([str(day) for day in daily.index]), side="left")
    keep = position < len(sessions)
    labels = np.asarray(sessions)[position[keep]]
    grouped = (1.0 + daily[keep]).groupby(labels).prod() - 1.0
    return grouped.sort_index()


def alpha_regression(y: pd.Series, x: pd.DataFrame, *, hac_lags: int = 5, annualization: float = 252.0) -> dict:
    """OLS alpha of `y` on `x` (inner-joined dates, NaN rows dropped) with a Newey-West t; `annualization` is the
    number of `y` periods a year (session data: 252)."""
    from evaluation.factor_spanning import factor_spanning

    out = factor_spanning(y, x, hac_lags=hac_lags, periods_per_year=int(annualization))
    return {
        "n": out.get("num_dates"),
        "alpha_daily": out.get("alpha_daily"),
        "alpha_annual": out.get("alpha_annual"),
        "t_hac": out.get("alpha_t"),
        "betas": out.get("betas"),
        "r2": out.get("r2"),
    }


def sharpe(values: np.ndarray, annualization: float) -> float | None:
    values = values[np.isfinite(values)]
    if len(values) < 2 or values.std(ddof=1) <= 0.0:
        return None
    return float(values.mean() / values.std(ddof=1) * math.sqrt(annualization))


def sharpe_bootstrap_ci(y: pd.Series, *, annualization: float, block: int = 10, draws: int = 2000, seed: int = 7) -> tuple[float | None, float | None]:
    """95% interval of the annualised Sharpe by a stationary block bootstrap (Politis & Romano, mean block `block`)."""
    values = y.to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    n = len(values)
    if n < 10:
        return None, None
    rng = np.random.default_rng(seed)
    stats = []
    p = 1.0 / max(block, 1)
    for _ in range(draws):
        index = np.empty(n, dtype=int)
        index[0] = rng.integers(n)
        jumps = rng.random(n) < p
        starts = rng.integers(n, size=n)
        for i in range(1, n):
            index[i] = starts[i] if jumps[i] else (index[i - 1] + 1) % n
        value = sharpe(values[index], annualization)
        if value is not None:
            stats.append(value)
    if not stats:
        return None, None
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


def period_report(y: pd.Series, benchmarks: pd.DataFrame, *, annualization: float, trial_sharpes: list[float]) -> dict:
    from evaluation.backtest_statistics import deflated_sharpe_ratio, probabilistic_sharpe_ratio

    values = y.to_numpy(dtype=float)
    low, high = sharpe_bootstrap_ci(y, annualization=annualization)
    dsr = deflated_sharpe_ratio(values, trial_sharpes, int(annualization)) if len(values) >= 3 else {"value": None}
    return {
        "start": str(y.index.min()) if len(y) else None,
        "end": str(y.index.max()) if len(y) else None,
        "n": int(len(y)),
        "total_return": float(np.prod(1.0 + values) - 1.0) if len(values) else 0.0,
        "sharpe": sharpe(values, annualization),
        "sharpe_ci95": [low, high],
        "psr": probabilistic_sharpe_ratio(values) if len(values) >= 3 else None,
        "dsr": dsr.get("value"),
        "dsr_trials": dsr.get("num_trials"),
        "alpha": alpha_regression(to_sessions(y, benchmarks.index), benchmarks) if len(y) > 10 and not benchmarks.empty else None,
    }


def deflated_sharpe_from_inputs(returns, *, num_trials: int, trial_variance: float | None, annualization: float) -> dict:
    """The deflated Sharpe with N and the trial variance given (`evaluation.trial_ledger.deflation_inputs`), not derived from
    a list of trial Sharpes: the variance must come from trials on the window being judged."""
    from evaluation.backtest_statistics import expected_max_sharpe, probabilistic_sharpe_ratio

    if trial_variance is None:
        return {"value": None, "expected_max_sharpe_annual": None, "num_trials": num_trials}
    sr0 = expected_max_sharpe(num_trials, trial_variance)
    if sr0 is None:
        return {"value": None, "expected_max_sharpe_annual": None, "num_trials": num_trials}
    value = probabilistic_sharpe_ratio(np.asarray(returns, dtype=float), sr0 / math.sqrt(annualization))
    return {"value": value, "expected_max_sharpe_annual": sr0, "num_trials": num_trials}


def window_report(y: pd.Series, benchmarks: pd.DataFrame, *, start: str, end: str, annualization: float, deflation: dict | None = None) -> dict:
    """Sharpe, alpha, max drawdown and (with `deflation`) the deflated Sharpe of a strategy series on one window."""
    part = y[(y.index >= start) & (y.index <= end)]
    if part.empty:
        return {"start": start, "end": end, "n": 0}
    values = part.to_numpy(dtype=float)
    curve = np.cumprod(1.0 + values)
    report = {
        "start": str(part.index.min()), "end": str(part.index.max()), "n": int(len(part)),
        "total_return": float(curve[-1] - 1.0), "sharpe": sharpe(values, annualization),
        "max_drawdown": float(1.0 - (curve / np.maximum.accumulate(curve)).min()),
        "alpha": alpha_regression(to_sessions(part, benchmarks.index), benchmarks) if len(part) > 10 and not benchmarks.empty else None,
    }
    if deflation:
        report["dsr"] = deflated_sharpe_from_inputs(values, num_trials=deflation["N"], trial_variance=deflation["var"], annualization=annualization)
        report["dsr_legacy_variance"] = deflated_sharpe_from_inputs(values, num_trials=deflation["N"], trial_variance=deflation.get("legacy_var"), annualization=annualization)
    return report


def r_alpha1(report: dict) -> dict:
    """The descriptive verdict over the per-period figures."""
    periods = report["periods"]
    failed = []
    full_alpha = (periods.get("full") or {}).get("alpha") or {}
    if not (full_alpha.get("t_hac") is not None and full_alpha["t_hac"] >= 2.0):
        failed.append("full-window alpha t < 2.0")
    if not ((periods.get("full") or {}).get("dsr") is not None and periods["full"]["dsr"] >= 0.95):
        failed.append("deflated Sharpe < 0.95")
    holdout_alpha = ((periods.get("holdout") or {}).get("alpha") or {}).get("alpha_annual")
    if not (holdout_alpha is not None and holdout_alpha > 0.0):
        failed.append("holdout alpha <= 0")
    fresh = periods.get("fresh") or {}
    if fresh.get("judgeable"):
        fresh_alpha = (fresh.get("alpha") or {}).get("alpha_annual")
        if not (fresh_alpha is not None and fresh_alpha > 0.0):
            failed.append("fresh-period alpha <= 0")
    return {"rule": "R-ALPHA1", "verdict": "demonstrated" if not failed else "not demonstrated", "failed": failed,
            "fresh_judged": bool(fresh.get("judgeable"))}


def alpha_proof_report(run_dir: Path, config: dict, root: Path, *, trial_sharpes: list[float]) -> dict:
    """Every period's figures and the R-ALPHA1 verdict for one Lean run folder (its frozen config when present)."""
    from evaluation.backtest_audit import load_backtest_run
    from evaluation.lean_attribution import run_config_path

    run_dir, root = Path(run_dir), Path(root)
    run = load_backtest_run(run_dir)
    snapshot = run_config_path(run_dir, root)
    run_config = json.loads(snapshot.read_text(encoding="utf-8")) if snapshot else config
    annualization = float((run_config.get("runtime", {}) or {}).get("trading_days_per_year", 365) or 365)
    y = strategy_daily_returns(run, run_config, root)
    if y.empty:
        return {"run": run_dir.name, "status": "no equity curve"}
    benchmarks = benchmark_daily_returns(root, run_config, start=str(y.index.min()), end=str(y.index.max()))
    windows = {"full": (str(y.index.min()), str(y.index.max())), **PERIODS, "fresh": (FRESH_START, str(y.index.max()))}
    periods = {}
    for name, (start, end) in windows.items():
        part = y[(y.index >= start) & (y.index <= end)]
        if part.empty:
            periods[name] = {"n": 0}
            continue
        periods[name] = period_report(part, benchmarks, annualization=annualization, trial_sharpes=trial_sharpes)
    periods["fresh"]["judgeable"] = periods["fresh"].get("n", 0) >= MIN_FRESH_POINTS
    periods["fresh"]["forward_judgeable"] = periods["fresh"].get("n", 0) >= FORWARD_MIN_POINTS
    report = {"run": run_dir.name, "config": str(snapshot) if snapshot else "config.json", "annualization": annualization,
              "benchmarks": [c for c in benchmarks.columns], "periods": periods}
    report["r_alpha1"] = r_alpha1(report)
    return report
