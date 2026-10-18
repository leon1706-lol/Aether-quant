"""Backtest statistics of one finished Lean run (V6.3.0): the metric set of López de Prado, *Advances in Financial
Machine Learning*, ch. 14, computed from the run folder alone and rendered as the README's "Backtest Statistics".

Two return streams are reported side by side:
  * **portfolio**: Lean's own equity curve;
  * **strategy**: the same curve without the T-bill cash sweep's P&L (`phase_v2.cash_sweep`), so idle-cash carry is not
    read as alpha.
Bet-level numbers (bets, hit ratio, holding period, long share) exclude the sweep ticker: buying T-bills is not a bet.

The metric functions are pure (lists / arrays in, finite floats or None out); `compute_backtest_statistics` assembles
them from the parsers that already exist (`backtest_audit`, `lean_attribution`, `lean_statistics`, `fill_price_audit`).
A metric that cannot be computed is a row with `value None` and a `reason`, never a fabricated number.
"""

from __future__ import annotations

import bisect
import json
import math
from collections import defaultdict
from datetime import date as date_type
from pathlib import Path
from statistics import NormalDist

import numpy as np

from json_safety import sanitize_json_finite

DAYS_PER_YEAR = 365
EULER_GAMMA = 0.5772156649015329
_NORMAL = NormalDist()


# ---------------------------------------------------------------- pure metric functions


def _finite(value) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def hhi_concentration(values) -> float | None:
    """AFML 14.6 `getHHI`: concentration of `values` (all one sign) normalised to [0, 1]; 0 = evenly spread, 1 = all in
    one observation. None for two or fewer observations."""
    weights = np.abs(np.asarray([value for value in values if value is not None], dtype=float))
    n = len(weights)
    if n <= 2 or weights.sum() <= 0.0:
        return None
    weights = weights / weights.sum()
    hhi = float((weights**2).sum())
    return _finite((hhi - 1.0 / n) / (1.0 - 1.0 / n))


def drawdown_episodes(dates: list[str], equity: list[float]) -> list[dict]:
    """AFML 14.7 `computeDD_TuW` on an equity curve: one episode per high-watermark that is followed by a loss, with its
    depth (fraction of the watermark), the watermark and recovery dates and the time under water in calendar days. The
    last episode is `open` when the curve never regained its watermark."""
    episodes: list[dict] = []
    if len(equity) < 2:
        return episodes
    hwm, hwm_date, trough = equity[0], dates[0], equity[0]
    for day, value in zip(dates[1:], equity[1:]):
        if value > hwm:
            if trough < hwm:
                episodes.append(_episode(hwm, hwm_date, trough, day, open_episode=False))
            hwm, hwm_date, trough = value, day, value
        else:
            trough = min(trough, value)
    if trough < hwm:
        episodes.append(_episode(hwm, hwm_date, trough, dates[-1], open_episode=True))
    return episodes


def _episode(hwm: float, start: str, trough: float, end: str, *, open_episode: bool) -> dict:
    return {
        "start": start,
        "end": end,
        "depth": (1.0 - trough / hwm) if hwm > 0.0 else 0.0,
        "days_under_water": (date_type.fromisoformat(end) - date_type.fromisoformat(start)).days,
        "open": open_episode,
    }


def percentile(values, q: float) -> float | None:
    values = [value for value in values if value is not None and math.isfinite(value)]
    return _finite(np.percentile(values, q)) if values else None


def daily_returns(equity: list[float]) -> list[float]:
    return [after / before - 1.0 for before, after in zip(equity, equity[1:]) if before > 0.0]


def sharpe_ratio(returns, periods_per_year: int = DAYS_PER_YEAR) -> float | None:
    """Annualised mean / sample std of per-period returns, no risk-free rate."""
    values = np.asarray(returns, dtype=float)
    if len(values) < 2 or values.std(ddof=1) <= 0.0:
        return None
    return _finite(values.mean() / values.std(ddof=1) * math.sqrt(periods_per_year))


def information_ratio(returns, benchmark_returns, periods_per_year: int = DAYS_PER_YEAR) -> float | None:
    """Annualised mean / std of the active return (strategy minus benchmark, same periods)."""
    active = np.asarray(returns, dtype=float) - np.asarray(benchmark_returns, dtype=float)
    if len(active) < 2 or active.std(ddof=1) <= 0.0:
        return None
    return _finite(active.mean() / active.std(ddof=1) * math.sqrt(periods_per_year))


def _skew_kurtosis(values: np.ndarray) -> tuple[float, float]:
    """Sample skewness and (non-excess) kurtosis, population moments as in Bailey & López de Prado (2012)."""
    centred = values - values.mean()
    std = centred.std()
    if std <= 0.0:
        return 0.0, 3.0
    return float((centred**3).mean() / std**3), float((centred**4).mean() / std**4)


def probabilistic_sharpe_ratio(returns, benchmark_sharpe_per_period: float = 0.0) -> float | None:
    """PSR (Bailey & López de Prado 2012): P(true Sharpe > benchmark) given the sample's length, skew and kurtosis. Both
    Sharpe ratios are per period (not annualised)."""
    values = np.asarray(returns, dtype=float)
    n = len(values)
    if n < 3 or values.std(ddof=1) <= 0.0:
        return None
    sharpe = values.mean() / values.std(ddof=1)
    skew, kurtosis = _skew_kurtosis(values)
    denominator = 1.0 - skew * sharpe + (kurtosis - 1.0) / 4.0 * sharpe**2
    if denominator <= 0.0:
        return None
    return _finite(_NORMAL.cdf((sharpe - benchmark_sharpe_per_period) * math.sqrt(n - 1) / math.sqrt(denominator)))


def expected_max_sharpe(num_trials: int, trial_sharpe_variance: float) -> float | None:
    """SR0 of the deflated Sharpe ratio: the expected maximum Sharpe of `num_trials` unskilled trials whose Sharpe ratios
    have variance `trial_sharpe_variance` (same units as the returned value)."""
    if num_trials < 2 or trial_sharpe_variance is None or trial_sharpe_variance <= 0.0:
        return None
    quantile_a = _NORMAL.inv_cdf(1.0 - 1.0 / num_trials)
    quantile_b = _NORMAL.inv_cdf(1.0 - 1.0 / (num_trials * math.e))
    return _finite(math.sqrt(trial_sharpe_variance) * ((1.0 - EULER_GAMMA) * quantile_a + EULER_GAMMA * quantile_b))


def deflated_sharpe_ratio(returns, trial_annual_sharpes: list[float], periods_per_year: int = DAYS_PER_YEAR) -> dict:
    """DSR (Bailey & López de Prado 2014): PSR against SR0, the best Sharpe expected from the number of configurations
    tried. Trial Sharpes are annual; they are moved to this series' period (÷ sqrt(periods_per_year)) first."""
    trials = [value for value in (_finite(item) for item in trial_annual_sharpes) if value is not None]
    if len(trials) < 2:
        return {"value": None, "num_trials": len(trials), "reason": "fewer than 2 registered trials"}
    variance_annual = float(np.var(trials, ddof=1))
    sr0_annual = expected_max_sharpe(len(trials), variance_annual)
    if sr0_annual is None:
        return {"value": None, "num_trials": len(trials), "reason": "trial Sharpe ratios have no variance"}
    value = probabilistic_sharpe_ratio(returns, sr0_annual / math.sqrt(periods_per_year))
    return {
        "value": value, "num_trials": len(trials), "trial_sharpe_variance_annual": variance_annual,
        "expected_max_sharpe_annual": sr0_annual, "reason": None if value is not None else "return series too short or flat",
    }


def classification_scores(y_true, y_pred, probabilities=None) -> dict:
    """Accuracy, precision, recall, F1 of binary calls (1 = up / long), and the negative log-loss when probabilities of
    class 1 exist (higher is better; 0 is a perfect forecaster, -0.693 a coin flip)."""
    truth = np.asarray(y_true, dtype=int)
    predicted = np.asarray(y_pred, dtype=int)
    n = len(truth)
    if n == 0:
        return {"n": 0}
    tp = int(((predicted == 1) & (truth == 1)).sum())
    fp = int(((predicted == 1) & (truth == 0)).sum())
    fn = int(((predicted == 0) & (truth == 1)).sum())
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else (0.0 if precision == 0.0 or recall == 0.0 else None)
    scores = {
        "n": n,
        "accuracy": float((predicted == truth).mean()),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "positive_rate": float(predicted.mean()),
        "neg_log_loss": None,
    }
    if probabilities is not None:
        clipped = np.clip(np.asarray(probabilities, dtype=float), 1e-15, 1.0 - 1e-15)
        scores["neg_log_loss"] = _finite(np.mean(truth * np.log(clipped) + (1 - truth) * np.log(1.0 - clipped)))
    return scores


def bet_starts(positions_by_date: dict[str, dict[str, float]]) -> list[tuple[str, str, int]]:
    """(date, ticker, side) each time a position leaves zero or flips sign (AFML 14.2's definition of a bet)."""
    previous: dict[str, float] = {}
    starts = []
    for day in sorted(positions_by_date):
        for ticker, quantity in sorted(positions_by_date[day].items()):
            before = previous.get(ticker, 0.0)
            if quantity != 0.0 and (before == 0.0 or (before > 0.0) != (quantity > 0.0)):
                starts.append((day, ticker, 1 if quantity > 0.0 else -1))
            previous[ticker] = quantity
    return starts


def monthly_counts(days: list[str], first: str, last: str) -> list[int]:
    """Bets per calendar month from `first` to `last`, months without a bet included as zeros."""
    counts: dict[str, int] = defaultdict(int)
    for day in days:
        counts[day[:7]] += 1
    year, month = int(first[:4]), int(first[5:7])
    out = []
    while f"{year:04d}-{month:02d}" <= last[:7]:
        out.append(counts.get(f"{year:04d}-{month:02d}", 0))
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return out


def _duration_days(text: str | None) -> float | None:
    """Lean's 'd.hh:mm:ss' / 'hh:mm:ss' trade duration in days."""
    if not text:
        return None
    head, _, rest = str(text).partition(":")
    days = "0"
    if "." in head:
        days, head = head.split(".", 1)
    try:
        hours, minutes, seconds = (float(part) for part in f"{head}:{rest}".split(":"))
        return float(days) + (hours + minutes / 60.0 + seconds / 3600.0) / 24.0
    except ValueError:
        return None


# ---------------------------------------------------------------- assembly


def _row(metric: str, portfolio=None, strategy=None, fmt: str = "num", reason: str | None = None) -> dict:
    return {"metric": metric, "portfolio": portfolio, "strategy": strategy, "format": fmt, "reason": reason}


def _asof(series: dict[str, float], sorted_dates: list[str], day: str) -> float | None:
    position = bisect.bisect_right(sorted_dates, day) - 1
    return series[sorted_dates[position]] if position >= 0 else None


def _daily_chart_series(result: dict, chart: str, series: str) -> dict[str, float]:
    """Last point per UTC day of one chart series (the same rule as `backtest_audit.daily_equity_from_chart`)."""
    from evaluation.backtest_audit import _parse_time

    points = result.get("charts", {}).get(chart, {}).get("series", {}).get(series, {}).get("values", [])
    out: dict[str, float] = {}
    for point in sorted(points, key=lambda item: item[0]):
        stamp = _parse_time(point[0])
        value = _finite(point[-1])
        if stamp is not None and value is not None:
            out[stamp.date().isoformat()] = value
    return out


def _interval_sums(daily: dict[str, float], equity_dates: list[str]) -> list[float]:
    """Each value of `daily` added to the first equity date on or after its own date, then listed per equity return
    (dates[1:]); values before the first equity date land on the first return."""
    sums = [0.0] * len(equity_dates)
    for day, value in daily.items():
        position = min(bisect.bisect_left(equity_dates, day), len(equity_dates) - 1)
        sums[max(position, 1)] += value
    return sums[1:]


def _numbers(stats: dict, key: str) -> float | None:
    """A Lean statistics string ('16.848%', '$1210.90', '0.082') as a float in its own unit."""
    raw = stats.get(key)
    if raw is None:
        return None
    text = str(raw).replace("$", "").replace(",", "").replace("%", "").strip()
    return _finite(text)


def compute_backtest_statistics(
    run: dict,
    config: dict,
    root: Path,
    *,
    run_name: str,
    book_history: list[dict] | None = None,
    trial_annual_sharpes: list[float] | None = None,
    offline_classification: dict[str, dict] | None = None,
    lean_basis: dict | None = None,
    attribution: dict | None = None,
) -> dict:
    """Every section of the README's "Backtest Statistics" for one loaded run (`backtest_audit.load_backtest_run`).
    `lean_basis` is `lean_statistics.statistics_table` output, `attribution` `lean_attribution.attribute_run` output; both
    optional. Pure apart from reading the Lean data zips under `root` for closes and opens."""
    from evaluation.backtest_audit import CASH_SWEEP_CLASS, class_by_ticker_from_config, daily_equity_from_chart
    from evaluation.fill_price_audit import fills_from_run, zip_opens_for_fills
    from evaluation.lean_attribution import closes_for_universe, daily_ticker_pnl, fills_from_order_events, quote_to_usd_rate

    result = run["result"]
    stats = result.get("statistics", {}) or {}
    days_per_year = int((config.get("runtime", {}) or {}).get("trading_days_per_year", DAYS_PER_YEAR) or DAYS_PER_YEAR)
    class_by_ticker = class_by_ticker_from_config(config)
    sweep = {ticker for ticker, kind in class_by_ticker.items() if kind == CASH_SWEEP_CLASS}
    forex = {ticker for ticker, kind in class_by_ticker.items() if kind == "forex"}

    equity_points = daily_equity_from_chart(result)
    dates = [day for day, _ in equity_points]
    nav = [value for _, value in equity_points]
    if len(nav) < 3:
        return {"run": run_name, "status": "no equity curve"}
    calendar_days = max((date_type.fromisoformat(dates[-1]) - date_type.fromisoformat(dates[0])).days, 1)
    years = calendar_days / 365.0

    fills = fills_from_order_events(run.get("order_events", []))
    closes = closes_for_universe(config, root, {fill.ticker for fill in fills})
    sorted_closes = {ticker: sorted(series) for ticker, series in closes.items()}
    ticker_pnl = daily_ticker_pnl(fills, closes, dates, forex)

    # ---- the two return streams
    portfolio_returns = daily_returns(nav)
    sweep_net_by_day = {
        day: sum(entry["pnl"] - entry["fee"] for ticker, entry in tickers.items() if ticker in sweep)
        for day, tickers in ticker_pnl.items()
    }
    sweep_per_return = _interval_sums(sweep_net_by_day, dates)
    strategy_pnl = [(after - before) - carry for before, after, carry in zip(nav, nav[1:], sweep_per_return)]
    strategy_returns = [pnl / before for pnl, before in zip(strategy_pnl, nav) if before > 0.0]
    strategy_curve = [nav[0]]
    for pnl in strategy_pnl:
        strategy_curve.append(strategy_curve[-1] + pnl)
    sweep_net_total = float(sum(sweep_per_return))

    # ---- positions, notionals, bets
    nav_by_date = dict(zip(dates, nav))
    positions_ex_sweep: dict[str, dict[str, float]] = {}
    gross_all, gross_ex, max_position = [], [], (0.0, None, None)
    notional_all = notional_ex = fees_all = fees_ex = 0.0
    for day in sorted(ticker_pnl):
        exposure_all = exposure_ex = 0.0
        held = {}
        for ticker, entry in ticker_pnl[day].items():
            notional_all += entry["notional"]
            fees_all += entry["fee"]
            if ticker not in sweep:
                notional_ex += entry["notional"]
                fees_ex += entry["fee"]
                held[ticker] = entry["position"]
            close = _asof(closes.get(ticker, {}), sorted_closes.get(ticker, []), day)
            if close is None or entry["position"] == 0.0:
                continue
            rate = quote_to_usd_rate(ticker, day, closes, sorted_closes) if ticker in forex else 1.0
            value = abs(entry["position"] * close * rate)
            exposure_all += value
            if ticker not in sweep:
                exposure_ex += value
                if value > max_position[0]:
                    max_position = (value, ticker, day)
        positions_ex_sweep[day] = held
        if day in nav_by_date and nav_by_date[day] > 0.0:
            gross_all.append(exposure_all / nav_by_date[day])
            gross_ex.append(exposure_ex / nav_by_date[day])
    bets = bet_starts(positions_ex_sweep)
    average_aum = float(np.mean(nav))

    # ---- closed trades (bets with an exit), sweep excluded
    trades = []
    for trade in result.get("totalPerformance", {}).get("closedTrades", []) or []:
        symbols = trade.get("symbols") or []
        ticker = str(symbols[0].get("value", "")).upper() if symbols else ""
        if ticker in sweep:
            continue
        entry_day = str(trade.get("entryTime", ""))[:10]
        rate = quote_to_usd_rate(ticker, entry_day, closes, sorted_closes) if ticker in forex else 1.0
        entry_notional = abs(float(trade.get("entryPrice", 0.0) or 0.0) * float(trade.get("quantity", 0.0) or 0.0)) * rate
        net = float(trade.get("profitLoss", 0.0) or 0.0) - float(trade.get("totalFees", 0.0) or 0.0)
        trades.append({
            "ticker": ticker, "long": int(trade.get("direction", 0) or 0) == 0, "net": net,
            "return": net / entry_notional if entry_notional > 0.0 else None,
            "days": _duration_days(trade.get("duration")), "notional": entry_notional,
        })
    hits = [trade for trade in trades if trade["net"] > 0.0]
    misses = [trade for trade in trades if trade["net"] <= 0.0]
    weighted_days = [(trade["days"], trade["notional"]) for trade in trades if trade["days"] is not None and trade["notional"] > 0.0]

    # (portfolio, strategy, benchmark) return per equity date on which the benchmark has both ends
    benchmark = _daily_chart_series(result, "Benchmark", "Benchmark")
    benchmark_flat = len({benchmark[day] for day in dates if day in benchmark}) <= 1
    paired = []
    for index in range(1, len(dates)):
        before, after = benchmark.get(dates[index - 1]), benchmark.get(dates[index])
        if before and after and index - 1 < len(strategy_returns):
            paired.append((portfolio_returns[index - 1], strategy_returns[index - 1], after / before - 1.0))
    paired_array = np.asarray(paired, dtype=float).reshape(-1, 3)

    def _benchmark_correlation(column: int) -> float | None:
        if benchmark_flat or len(paired_array) < 3 or paired_array[:, column].std() <= 0 or paired_array[:, 2].std() <= 0:
            return None
        return _finite(np.corrcoef(paired_array[:, column], paired_array[:, 2])[0, 1])

    pnl_total = nav[-1] - nav[0]
    total_return = nav[-1] / nav[0] - 1.0
    strategy_total = strategy_curve[-1] / strategy_curve[0] - 1.0
    cagr = (1.0 + total_return) ** (365.0 / calendar_days) - 1.0
    strategy_cagr = (1.0 + strategy_total) ** (365.0 / calendar_days) - 1.0 if strategy_total > -1.0 else None
    long_net = sum(trade["net"] for trade in trades if trade["long"])
    short_net = sum(trade["net"] for trade in trades if not trade["long"])

    general = [
        _row("Time range", f"{dates[0]} to {dates[-1]}", None, "text"),
        _row("Years", years, None, "num2"),
        _row("Average AUM", average_aum, None, "usd"),
        _row("Capacity (Lean estimate)", _numbers(stats, "Estimated Strategy Capacity"), None, "usd",
             reason=f"lowest-capacity asset {stats.get('Lowest Capacity Asset', 'n/a')}"),
        _row("Leverage, mean (gross exposure / NAV)", _finite(np.mean(gross_all)) if gross_all else None,
             _finite(np.mean(gross_ex)) if gross_ex else None, "x"),
        _row("Leverage, max", _finite(max(gross_all)) if gross_all else None, _finite(max(gross_ex)) if gross_ex else None, "x"),
        _row("Maximum dollar position", None, max_position[0] or None, "usd",
             reason=f"{max_position[1]} on {max_position[2]}" if max_position[1] else "no position"),
        _row("Ratio of longs (share of bets)", None, (sum(1 for bet in bets if bet[2] > 0) / len(bets)) if bets else None, "pct"),
        _row("Longs : shorts (bets)", None, f"{sum(1 for bet in bets if bet[2] > 0)} : {sum(1 for bet in bets if bet[2] < 0)}", "text"),
        _row("Frequency of bets (per year)", None, len(bets) / years if bets else None, "num1"),
        _row("Average holding period (days, notional-weighted)", None,
             (sum(days * weight for days, weight in weighted_days) / sum(weight for _, weight in weighted_days)) if weighted_days else None, "num1"),
        _row("Annualized turnover (traded notional / AUM)", notional_all / average_aum / years, notional_ex / average_aum / years, "x"),
        _row("Correlation to underlying (SPY, daily)", _benchmark_correlation(0), _benchmark_correlation(1),
             "num3", reason="flat benchmark feed" if benchmark_flat else None),
        _row("Start equity", _numbers(stats, "Start Equity"), None, "usd"),
        _row("End equity", _numbers(stats, "End Equity"), None, "usd"),
        _row("Total orders", _numbers(stats, "Total Orders"), None, "int"),
        _row("Lean portfolio turnover (daily mean)", _numbers(stats, "Portfolio Turnover"), None, "pct_raw"),
    ]

    performance = [
        _row("PnL", pnl_total, pnl_total - sweep_net_total, "usd_signed"),
        _row("PnL from the T-bill sweep (carry)", sweep_net_total, None, "usd_signed"),
        _row("PnL from long positions (closed bets, net of fees)", None, long_net, "usd_signed"),
        _row("PnL from short positions (closed bets, net of fees)", None, short_net, "usd_signed"),
        _row("Annualized rate of return", cagr, strategy_cagr, "pct_signed"),
        _row("Hit ratio (closed bets net of fees)", None, len(hits) / len(trades) if trades else None, "pct"),
        _row("Average return from hits", None, _finite(np.mean([t["return"] for t in hits if t["return"] is not None])) if hits else None, "pct_signed"),
        _row("Average return from misses", None, _finite(np.mean([t["return"] for t in misses if t["return"] is not None])) if misses else None, "pct_signed"),
        _row("Time-weighted return (no external flows: the chained return)", float(np.prod([1.0 + r for r in portfolio_returns]) - 1.0),
             strategy_total, "pct_signed"),
        _row("Net profit (Lean)", _numbers(stats, "Net Profit"), None, "pct_raw"),
        _row("Win rate / loss rate (Lean, all trades)", f"{stats.get('Win Rate', 'n/a')} / {stats.get('Loss Rate', 'n/a')}", None, "text"),
        _row("Average win / average loss (Lean)", f"{stats.get('Average Win', 'n/a')} / {stats.get('Average Loss', 'n/a')}", None, "text"),
        _row("Profit-loss ratio (Lean)", _numbers(stats, "Profit-Loss Ratio"), None, "num2"),
        _row("Expectancy (Lean)", _numbers(stats, "Expectancy"), None, "num3"),
        _row("Unrealized at the end (Lean)", _numbers(result.get("runtimeStatistics", {}) or {}, "Unrealized"), None, "usd_signed"),
    ]

    episodes = drawdown_episodes(dates, nav)
    strategy_episodes = drawdown_episodes(dates, strategy_curve)
    trade_stats = result.get("totalPerformance", {}).get("tradeStatistics", {}) or {}
    runs = [
        _row("HHI of positive returns", hhi_concentration([r for r in portfolio_returns if r > 0.0]),
             hhi_concentration([r for r in strategy_returns if r > 0.0]), "num3"),
        _row("HHI of negative returns", hhi_concentration([r for r in portfolio_returns if r < 0.0]),
             hhi_concentration([r for r in strategy_returns if r < 0.0]), "num3"),
        _row("HHI of time between bets (bets per month)", None, hhi_concentration(monthly_counts([bet[0] for bet in bets], dates[0], dates[-1])) if bets else None, "num3"),
        _row("95-percentile drawdown", percentile([e["depth"] for e in episodes], 95), percentile([e["depth"] for e in strategy_episodes], 95), "pct"),
        _row("95-percentile time under water (days)", percentile([e["days_under_water"] for e in episodes], 95),
             percentile([e["days_under_water"] for e in strategy_episodes], 95), "num1"),
        _row("Maximum drawdown", max((e["depth"] for e in episodes), default=0.0), max((e["depth"] for e in strategy_episodes), default=0.0), "pct"),
        _row("Longest time under water (days)", max((e["days_under_water"] for e in episodes), default=0),
             max((e["days_under_water"] for e in strategy_episodes), default=0), "int"),
        _row("Drawdown episodes", len(episodes), len(strategy_episodes), "int"),
        _row("Drawdown (Lean)", _numbers(stats, "Drawdown"), None, "pct_raw"),
        _row("Drawdown recovery (Lean, days)", _numbers(stats, "Drawdown Recovery"), None, "int"),
        _row("Maximum drawdown duration (Lean)", trade_stats.get("maximumDrawdownDuration"), None, "text"),
    ]

    run_fills = fills_from_run(run)
    zip_opens = zip_opens_for_fills(run_fills, Path(root) / "data")
    slippage_all = slippage_ex = covered_all = covered_ex = 0.0
    missing = 0
    for fill in run_fills:
        reference = zip_opens.get((fill["symbol"], fill["date"]))
        ticker = fill["symbol"].upper()
        rate = quote_to_usd_rate(ticker, fill["date"], closes, sorted_closes) if ticker in forex else 1.0
        notional = abs(fill["price"] * fill.get("quantity", 0.0)) * rate
        if reference is None or reference <= 0.0 or notional <= 0.0:
            missing += 1
            continue
        cost = fill["direction"] * (fill["price"] - reference) / reference * notional
        slippage_all += cost
        covered_all += notional
        if ticker not in sweep:
            slippage_ex += cost
            covered_ex += notional
    strategy_net = pnl_total - sweep_net_total
    shortfall = [
        _row("Traded notional", notional_all, notional_ex, "usd"),
        _row("Broker fees", fees_all, fees_ex, "usd"),
        _row("Broker fees per turnover (bps of traded notional)", fees_all / notional_all * 1e4 if notional_all else None,
             fees_ex / notional_ex * 1e4 if notional_ex else None, "bps"),
        _row("Average slippage per turnover (bps vs the bar's open)", slippage_all / covered_all * 1e4 if covered_all else None,
             slippage_ex / covered_ex * 1e4 if covered_ex else None, "bps",
             reason=f"{missing} fills without a reference open" if missing else None),
        _row("Dollar performance per turnover (bps)", pnl_total / notional_all * 1e4 if notional_all else None,
             strategy_net / notional_ex * 1e4 if notional_ex else None, "bps"),
        _row("Return on execution costs (net PnL / (fees + slippage))",
             pnl_total / (fees_all + slippage_all) if fees_all + slippage_all > 0.0 else None,
             strategy_net / (fees_ex + slippage_ex) if fees_ex + slippage_ex > 0.0 else None, "x"),
        _row("Total fees (Lean)", _numbers(stats, "Total Fees"), None, "usd"),
    ]

    strategy_dsr = deflated_sharpe_ratio(strategy_returns, trial_annual_sharpes or [], days_per_year)
    portfolio_dsr = deflated_sharpe_ratio(portfolio_returns, trial_annual_sharpes or [], days_per_year)
    has_benchmark = len(paired_array) > 2 and not benchmark_flat
    efficiency = [
        _row("Annualized Sharpe ratio (Lean: risk-free rate subtracted)", _numbers(stats, "Sharpe Ratio"), None, "num3"),
        _row("Annualized Sharpe ratio (no risk-free rate)", sharpe_ratio(portfolio_returns, days_per_year), sharpe_ratio(strategy_returns, days_per_year), "num3"),
        _row("Information ratio vs SPY",
             information_ratio(paired_array[:, 0], paired_array[:, 2], days_per_year) if has_benchmark else None,
             information_ratio(paired_array[:, 1], paired_array[:, 2], days_per_year) if has_benchmark else None,
             "num3", reason="flat benchmark feed" if benchmark_flat else None),
        _row("Information ratio (Lean)", _numbers(stats, "Information Ratio"), None, "num3"),
        _row("Probabilistic Sharpe ratio (P[true Sharpe > 0])", probabilistic_sharpe_ratio(portfolio_returns), probabilistic_sharpe_ratio(strategy_returns), "pct"),
        _row("Probabilistic Sharpe ratio (Lean, vs its benchmark)", _numbers(stats, "Probabilistic Sharpe Ratio"), None, "pct_raw"),
        _row("Deflated Sharpe ratio", portfolio_dsr["value"], strategy_dsr["value"], "pct",
             reason=(f"{strategy_dsr['num_trials']} registered trials, expected best Sharpe {strategy_dsr['expected_max_sharpe_annual']:.2f}"
                     if strategy_dsr.get("expected_max_sharpe_annual") is not None else strategy_dsr.get("reason"))),
        _row("Sortino ratio (Lean)", _numbers(stats, "Sortino Ratio"), None, "num3"),
        _row("Alpha / beta (Lean)", f"{stats.get('Alpha', 'n/a')} / {stats.get('Beta', 'n/a')}", None, "text"),
        _row("Annual standard deviation (Lean)", _numbers(stats, "Annual Standard Deviation"), None, "num3"),
        _row("Annual variance (Lean)", _numbers(stats, "Annual Variance"), None, "num4"),
        _row("Tracking error (Lean)", _numbers(stats, "Tracking Error"), None, "num3"),
        _row("Treynor ratio (Lean)", _numbers(stats, "Treynor Ratio"), None, "num3"),
    ]
    for label, row in ((lean_basis or {}).get("replica") or {}).items():
        efficiency.append(_row(f"Sharpe, Lean formula ({label})", _finite(row.get("sharpe_ratio")), None, "num3"))

    classification = _classification_section(book_history, closes, sorted_closes, offline_classification)
    attribution_section = _attribution_section(ticker_pnl, dates, nav, class_by_ticker, years, average_aum, days_per_year, attribution)

    return sanitize_json_finite({
        "run": run_name,
        "status": "OK",
        "window": {"start": dates[0], "end": dates[-1], "days": calendar_days},
        "sections": {
            "general": general, "performance": performance, "runs": runs, "shortfall": shortfall,
            "efficiency": efficiency, "classification": classification, "attribution": attribution_section,
        },
    })


def _forward_return(series: dict[str, float], sorted_dates: list[str], day: str, horizon: int) -> float | None:
    position = bisect.bisect_right(sorted_dates, day) - 1
    if position < 0 or position + horizon >= len(sorted_dates):
        return None
    start, end = series[sorted_dates[position]], series[sorted_dates[position + horizon]]
    return end / start - 1.0 if start > 0.0 else None


def _classification_section(book_history, closes, sorted_closes, offline: dict[str, dict] | None, horizon: int = 20) -> list[dict]:
    """One row per source: the Lean run's book calls (side vs the sign of the ticker's own 20-bar forward return) and
    the offline direction_20d heads (written by `aq evaluate --classification`)."""
    rows = []
    truth, predicted = [], []
    for record in book_history or []:
        for ticker, allocation in (record.get("allocations") or {}).items():
            role = str((allocation or {}).get("role", "")).lower()
            series = closes.get(str(ticker).upper())
            if role not in ("long", "short") or not series:
                continue
            forward = _forward_return(series, sorted_closes[str(ticker).upper()], record.get("date", ""), horizon)
            if forward is None or forward == 0.0:
                continue
            truth.append(1 if forward > 0.0 else 0)
            predicted.append(1 if role == "long" else 0)
    lean_scores = classification_scores(truth, predicted) if truth else {"n": 0}
    rows.append({"source": "Lean book calls (side vs 20-bar forward move)", **lean_scores,
                 "reason": "no probability is logged per book call" if truth else "no book history for this run"})
    for model, scores in sorted((offline or {}).items()):
        rows.append({"source": f"Offline {model} direction_20d (backtest split, threshold {scores.get('threshold', 0.5)})",
                     **{key: scores.get(key) for key in ("n", "accuracy", "precision", "recall", "f1", "positive_rate", "neg_log_loss")},
                     "reason": None})
    return rows


def _attribution_section(ticker_pnl, dates, nav, class_by_ticker, years, average_aum, days_per_year, attribution) -> dict:
    """Risk and return per asset class (the sweep is its own class), plus Lean-attribution components when given."""
    daily_by_class: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    fees_by_class: dict[str, float] = defaultdict(float)
    for day, tickers in ticker_pnl.items():
        for ticker, entry in tickers.items():
            asset_class = class_by_ticker.get(ticker, "equity")
            daily_by_class[asset_class][day] += entry["pnl"] - entry["fee"]
            fees_by_class[asset_class] += entry["fee"]
    per_class = {name: np.asarray(_interval_sums(days, dates)) for name, days in daily_by_class.items()}
    nav_before = np.asarray(nav[:-1], dtype=float)
    total = sum(per_class.values()) if per_class else np.zeros(len(nav) - 1)
    total_variance = float(np.var(total / nav_before, ddof=1)) if len(nav_before) > 1 else 0.0
    rows = []
    for name in sorted(per_class):
        pnl = per_class[name]
        returns = pnl / nav_before
        cumulative = np.cumsum(pnl)
        peak = np.maximum.accumulate(np.concatenate([[0.0], cumulative]))[1:]
        std = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
        rows.append({
            "class": name,
            "net_pnl": float(pnl.sum()),
            "annual_return_on_aum": float(pnl.sum()) / average_aum / years,
            "annual_volatility": std * math.sqrt(days_per_year),
            "sharpe": _finite(returns.mean() / std * math.sqrt(days_per_year)) if std > 0.0 else None,
            "max_drawdown_on_aum": float((peak - cumulative).max()) / average_aum if len(cumulative) else 0.0,
            "risk_share": _finite(np.cov(returns, total / nav_before, ddof=1)[0, 1] / total_variance) if total_variance > 0.0 else None,
            "fees": fees_by_class[name],
        })
    lean_net = nav[-1] - nav[0]
    components = []
    for name, entry in sorted(((attribution or {}).get("components") or {}).items()):
        if entry.get("fills") or entry.get("pnl"):
            components.append({"component": name, "net_pnl": entry.get("net"), "fees": entry.get("fee"), "fills": entry.get("fills")})
    return {
        "classes": rows,
        "unattributed_pnl": lean_net - float(sum(row["net_pnl"] for row in rows)),
        "components": components,
    }


# ---------------------------------------------------------------- I/O wrapper


def load_trial_sharpes(registry_path: Path) -> list[float]:
    """Annual Sharpe ratios of every registered research trial (`scripts/build_trial_registry.py`)."""
    try:
        payload = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [trial["median_sharpe"] for trial in payload.get("trials", []) if _finite(trial.get("median_sharpe")) is not None]


def compute_for_run_dir(run_dir: Path, config: dict, root: Path) -> dict:
    """`aq evaluate --backtest-stats`: load the run folder and its companions, then compute every section."""
    from evaluation.backtest_audit import load_backtest_run
    from evaluation.lean_attribution import attribute_run, find_book_history_for_run, run_config_path
    from evaluation.lean_statistics import statistics_table

    run_dir = Path(run_dir)
    root = Path(root)
    run = load_backtest_run(run_dir)
    snapshot = run_config_path(run_dir, root)
    run_config = json.loads(snapshot.read_text(encoding="utf-8")) if snapshot else config
    history_path = find_book_history_for_run(run_dir, root / "visualization" / "book_history")
    history = []
    if history_path is not None:
        history = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    evaluation_dir = root / "ml" / "evaluation"
    offline = {}
    for model in ("multitask", "sequence"):
        path = evaluation_dir / f"classification_scores_{model}.json"
        if path.exists():
            try:
                offline[model] = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                pass
    lean_basis = None
    result_path = next((path for path in run_dir.glob("*.json") if path.stem.isdigit()), None)
    rate_files = {"shipped rate file, 365 days": root / "data" / "alternative" / "interest-rate" / "usa" / "interest-rate.csv"}
    if result_path is not None and all(path.exists() for path in rate_files.values()):
        try:
            table = statistics_table(result_path, {"shipped rate file": rate_files["shipped rate file, 365 days"]}, (365,))
            pre = evaluation_dir / "v620" / "interest-rate_pre_v620.csv"
            if pre.exists():
                old = statistics_table(result_path, {"pre-V6.2 rate file": pre}, (252,))
                table["replica"].update(old["replica"])
            lean_basis = table
        except (OSError, ValueError, KeyError, ZeroDivisionError):
            lean_basis = None
    attribution = attribute_run(run, history, run_config, root) if history else None
    stats = compute_backtest_statistics(
        run, run_config, root, run_name=run_dir.name, book_history=history,
        trial_annual_sharpes=load_trial_sharpes(evaluation_dir / "trial_registry.json"),
        offline_classification=offline, lean_basis=lean_basis, attribution=attribution,
    )
    stats["book_history"] = str(history_path) if history_path else None
    stats["config"] = str(snapshot) if snapshot else "config.json"
    return stats
