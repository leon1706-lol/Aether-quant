"""Paper-period protocol and band check (V6.4.0, lead L12).

The paper period is the only out-of-sample test left and its success is NOT "make money": a fixed-config run is inside the
bands a reference Lean run (the pinned final backtest) spans over windows of the same number of rebalances. This module
turns a finished run folder (a Lean backtest, or a paper run with `diagnostics.book_history.paper_enabled`) into the
protocol's checklist, builds the reference bands from every contiguous window of the reference run, and compares.

Pure apart from `paper_metrics_for_run_dir`, which reads the run folder and the Lean data zips.
"""

from __future__ import annotations

import math
import statistics
from bisect import bisect_left, bisect_right
from collections import defaultdict
from pathlib import Path

MIN_REBALANCES = 6
MIN_TRADING_DAYS = 120
DEFAULT_QUANTILES = (0.05, 0.95)
WARMUP_REASON = "thin_universe_or_zero_top_n"

# metric -> label; every one is a ratio or per-day figure so windows of different length stay comparable
METRICS = {
    "veto_rate": "share of rebalances vetoed (gate / spread)",
    "lock_rebalance_share": "share of rebalances with a kill-switch-locked member decision",
    "strategy_gross_exposure": "mean strategy gross exposure, x NAV, T-bill sweep excluded",
    "fills_per_rebalance": "fills per rebalance",
    "median_slippage_bps": "median adverse fill vs the bar open, bps",
    "p90_slippage_bps": "90th percentile adverse fill vs the bar open, bps",
    "fee_bps_per_turnover": "broker fees per traded notional, bps",
    "strategy_pnl_bps_per_day": "mean daily strategy P&L (sweep excluded), bps of NAV",
    "sweep_pnl_bps_per_day": "mean daily T-bill sweep P&L, bps of NAV",
    "daily_hit_ratio": "share of days with a positive strategy P&L",
    "annualized_turnover": "traded notional / mean NAV / years, sweep excluded",
}


def live_rebalances(history: list[dict]) -> list[dict]:
    """The run's rebalance records in date order, warm-up records (universe not ready) dropped."""
    return sorted((record for record in history if record.get("gate_veto_reason") != WARMUP_REASON), key=lambda r: r.get("date", ""))


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = q * (len(ordered) - 1)
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def daily_table(ticker_pnl: dict, nav_by_date: dict, closes: dict, sorted_closes: dict, sweep_tickers: set, rates=None) -> dict:
    """{date: {exposure, strategy_pnl, sweep_pnl, fees, notional, fills}}: the per-date figures every window is a slice of.
    `ticker_pnl` = `lean_attribution.daily_ticker_pnl` output; exposure marks each held position at its last close."""
    rates = rates or {}
    table = {}
    for day in sorted(nav_by_date):
        nav = nav_by_date[day]
        entries = ticker_pnl.get(day, {})
        exposure = strategy_pnl = sweep_pnl = fees = notional = 0.0
        fills = 0
        for ticker, entry in entries.items():
            net = entry["pnl"] - entry["fee"]
            if ticker in sweep_tickers:
                sweep_pnl += net
                continue
            strategy_pnl += net
            fees += entry["fee"]
            notional += entry["notional"]
            fills += entry["fills"]
            series = closes.get(ticker) or {}
            if entry["position"] and series:
                order = sorted_closes.get(ticker, [])
                position = bisect_right(order, day) - 1
                if position >= 0:
                    exposure += abs(entry["position"] * series[order[position]] * rates.get((ticker, day), 1.0))
        table[day] = {"exposure": exposure / nav if nav > 0.0 else 0.0, "strategy_pnl": strategy_pnl / nav if nav > 0.0 else 0.0,
                      "sweep_pnl": sweep_pnl / nav if nav > 0.0 else 0.0, "fees": fees, "notional": notional, "fills": fills,
                      "nav": nav}
    return table


def metrics_for_window(table: dict, rebalances: list[dict], slippage_by_date: dict[str, list[float]], start: str | None = None,
                       end: str | None = None) -> dict:
    """The protocol's checklist over `[start, end]` (inclusive; None = open). Metrics that cannot be computed are None."""
    days = [day for day in sorted(table) if (start is None or day >= start) and (end is None or day <= end)]
    window = [record for record in rebalances if (start is None or record["date"] >= start) and (end is None or record["date"] <= end)]
    if not days:
        return {"rebalances": len(window), "trading_days": 0, **dict.fromkeys(METRICS)}
    vetoed = sum(1 for record in window if not record.get("allocations"))
    locked = sum(
        1 for record in window
        if any(str(reason).startswith("kill_switch") for decision in (record.get("book_member_decisions") or {}).values()
               for reason in decision.get("reasons", []))
    )
    slippage = [value for day in days for value in slippage_by_date.get(day, [])]
    fills = sum(table[day]["fills"] for day in days)
    notional = sum(table[day]["notional"] for day in days)
    fees = sum(table[day]["fees"] for day in days)
    navs = [table[day]["nav"] for day in days]
    years = max(len(days), 1) / 365.0
    strategy = [table[day]["strategy_pnl"] for day in days]
    return {
        "rebalances": len(window), "trading_days": len(days),
        "veto_rate": vetoed / len(window) if window else None,
        "lock_rebalance_share": locked / len(window) if window else None,
        "strategy_gross_exposure": statistics.fmean(table[day]["exposure"] for day in days),
        "fills_per_rebalance": fills / len(window) if window else None,
        "median_slippage_bps": statistics.median(slippage) if slippage else None,
        "p90_slippage_bps": _quantile(slippage, 0.9) if slippage else None,
        "fee_bps_per_turnover": fees / notional * 1e4 if notional > 0.0 else None,
        "strategy_pnl_bps_per_day": statistics.fmean(strategy) * 1e4,
        "sweep_pnl_bps_per_day": statistics.fmean(table[day]["sweep_pnl"] for day in days) * 1e4,
        "daily_hit_ratio": sum(1 for value in strategy if value > 0.0) / len(strategy),
        "annualized_turnover": notional / statistics.fmean(navs) / years if navs and statistics.fmean(navs) > 0.0 else None,
    }


def reference_bands(table: dict, rebalances: list[dict], slippage_by_date: dict, window_rebalances: int = MIN_REBALANCES,
                    quantiles: tuple[float, float] = DEFAULT_QUANTILES) -> dict:
    """Per metric: the empirical `quantiles` range over every contiguous window of `window_rebalances` rebalances of the
    reference run. {"bands": {metric: {"low", "high", "windows"}}, "windows": n, "window_rebalances": W}."""
    dates = [record["date"] for record in rebalances]
    days = sorted(table)
    samples: dict[str, list[float]] = defaultdict(list)
    count = 0
    for index in range(0, len(dates) - window_rebalances + 1):
        # a window = W rebalances and the days up to (excluding) the next rebalance: a whole number of cadences
        following = index + window_rebalances
        end = days[bisect_left(days, dates[following]) - 1] if following < len(dates) else None
        metrics = metrics_for_window(table, rebalances, slippage_by_date, dates[index], end)
        count += 1
        for name in METRICS:
            if metrics.get(name) is not None and math.isfinite(metrics[name]):
                samples[name].append(metrics[name])
    bands = {name: {"low": _quantile(values, quantiles[0]), "high": _quantile(values, quantiles[1]), "windows": len(values)}
             for name, values in samples.items() if values}
    return {"bands": bands, "windows": count, "window_rebalances": window_rebalances, "quantiles": list(quantiles)}


def band_check(metrics: dict, bands: dict) -> dict:
    """{"inside": every metric with a band is within it, "outside": [names], "rows": [...]}. A metric the run could not
    compute counts as outside; a metric without a band is reported but not judged."""
    rows, outside = [], []
    for name, label in METRICS.items():
        band = (bands.get("bands") or {}).get(name)
        value = metrics.get(name)
        if band is None:
            rows.append({"metric": name, "label": label, "value": value, "low": None, "high": None, "inside": None})
            continue
        inside = value is not None and band["low"] <= value <= band["high"]
        if not inside:
            outside.append(name)
        rows.append({"metric": name, "label": label, "value": value, "low": band["low"], "high": band["high"], "inside": inside})
    enough = (metrics.get("rebalances") or 0) >= MIN_REBALANCES and (metrics.get("trading_days") or 0) >= MIN_TRADING_DAYS
    return {"inside": not outside, "outside": outside, "rows": rows, "minimum_met": enough,
            "minimum": {"rebalances": MIN_REBALANCES, "trading_days": MIN_TRADING_DAYS}}


def _slippage_by_date(run: dict, data_root: Path) -> dict[str, list[float]]:
    from evaluation.fill_price_audit import fills_from_run, zip_opens_for_fills

    fills = fills_from_run(run)
    references = zip_opens_for_fills(fills, data_root)
    out: dict[str, list[float]] = defaultdict(list)
    for fill in fills:
        reference = references.get((fill["symbol"], fill["date"]))
        if reference and reference > 0.0:
            out[fill["date"]].append(fill["direction"] * (fill["price"] - reference) / reference * 1e4)
    return out


def paper_metrics_for_run_dir(run_dir, config: dict, root, *, start: str | None = None, end: str | None = None) -> dict:
    """Load one run folder (+ its book history) and return {"table", "rebalances", "slippage_by_date", "metrics"}; the
    first three feed `reference_bands` when this run is the reference."""
    import json

    from evaluation.backtest_audit import CASH_SWEEP_CLASS, class_by_ticker_from_config, daily_equity_from_chart, load_backtest_run
    from evaluation.lean_attribution import (
        closes_for_universe, daily_ticker_pnl, fills_from_order_events, find_book_history_for_run, quote_to_usd_rate,
    )

    root = Path(root)
    run = load_backtest_run(Path(run_dir))
    class_by_ticker = class_by_ticker_from_config(config)
    sweep = {ticker for ticker, kind in class_by_ticker.items() if kind == CASH_SWEEP_CLASS}
    forex = {ticker for ticker, kind in class_by_ticker.items() if kind == "forex"}
    points = daily_equity_from_chart(run["result"])
    dates = [day for day, _ in points]
    nav_by_date = dict(points)
    fills = fills_from_order_events(run.get("order_events", []))
    closes = closes_for_universe(config, root, {fill.ticker for fill in fills})
    sorted_closes = {ticker: sorted(series) for ticker, series in closes.items()}
    ticker_pnl = daily_ticker_pnl(fills, closes, dates, forex)
    rates = {}
    for day, entries in ticker_pnl.items():
        for ticker in entries:
            if ticker in forex:
                rates[(ticker, day)] = quote_to_usd_rate(ticker, day, closes, sorted_closes)
    table = daily_table(ticker_pnl, nav_by_date, closes, sorted_closes, sweep, rates)
    history_path = find_book_history_for_run(Path(run_dir), root / "visualization" / "book_history")
    history = []
    if history_path is not None:
        history = [json.loads(line) for line in Path(history_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    rebalances = live_rebalances(history)
    slippage = _slippage_by_date(run, root / "data")
    return {"table": table, "rebalances": rebalances, "slippage_by_date": slippage,
            "metrics": metrics_for_window(table, rebalances, slippage, start, end),
            "book_history": str(history_path) if history_path else None}
