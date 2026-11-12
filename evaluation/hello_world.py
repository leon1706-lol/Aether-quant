"""`aq hello` (V6.6.5, #343): the shipped book's rule on real daily bars, a cost-aware backtest and an honest report.

The rule is the forward definition in `ml/forward/candidates.json` (`t3_crypto_trend_blend_x_eos`): long a coin while its
trailing return over 20, 60 and 120 sessions is positive (one vote each), vol-scaled and capped by
`portfolio.premia_signals`, rebalanced every 5 sessions. Timing is the live path's: a decision on session D reads the bars
dated before D, and its orders fill at the close of the bar dated D. Costs are Coinbase's taker fee plus the simulator's
crypto slippage, with the live path's 0.2% deadband. The overfitting block runs the same rule over an 8-variant lookback
grid (PBO by CSCV, the deflated Sharpe on that grid) and haircuts the Sharpe for the project's own trial count.
"""

from __future__ import annotations

import html
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from evaluation.backtest_api import BacktestResult, backtest, summary_statistics
from evaluation.backtest_statistics import deflated_sharpe_ratio, probabilistic_sharpe_ratio
from evaluation.overfitting import haircut_sharpe, minimum_track_record_length
from evaluation.pbo import probability_of_backtest_overfitting
from execution.cost_models import coinbase_model
from portfolio.premia_signals import ResearchPanel, SleeveSpec, WeightSettings, signal_to_weights, sleeve_signal

__all__ = [
    "HELLO_RULE", "RESEARCH_TRIALS", "StatsRow", "HelloReport", "known_at_sessions", "load_closes", "rule_weights", "run_hello", "render_text", "render_html",
]

HELLO_RULE: dict[str, object] = {
    "id": "t3_crypto_trend_blend_x_eos",
    "kind": "time_series",
    "family": "crypto_trend",
    "universe": ["crypto"],
    "rebalance_every": 5,
    "params": {"lookback_a": 20, "lookback_b": 60, "lookback_c": 120},
}
# The deflated-Sharpe N of the project's research record after V6.6.4 (development/Problems.md #336).
RESEARCH_TRIALS = 217
GRID_A = (10, 20, 30, 40)
GRID_C = (120, 180)
DEADBAND = 0.002  # portfolio.target_weights.TargetWeightsConfig.min_weight_change
PERIODS_PER_YEAR = 365
NOTE = "No verified edge: this is the project's shipped book, labelled improved, not verified. Past results say nothing certain about the future."


@dataclass(frozen=True)
class StatsRow:
    """One column of the report."""

    name: str
    cagr: float
    volatility: float
    sharpe: float
    sortino: float
    max_drawdown: float
    calmar: float
    turnover: float
    cost_bps: float
    average_gross: float

    @classmethod
    def from_result(cls, name: str, result: BacktestResult) -> StatsRow:
        stats = result.stats()
        gross = float(result.weights.abs().sum(axis=1).mean()) if len(result.weights) else 0.0
        return cls(name, stats["cagr"], stats["annual_volatility"], stats["sharpe_ratio"], stats["sortino_ratio"], stats["max_drawdown"],
                   stats["calmar_ratio"], stats["turnover_annual"], stats["cost_drag_bps_annual"], gross)


@dataclass(frozen=True)
class HelloReport:
    """Everything `aq hello` prints, plus the equity curves."""

    start: str
    end: str
    coins: tuple[str, ...]
    data_source: str
    strategy: StatsRow
    btc_buy_hold: StatsRow
    equal_weight: StatsRow
    psr: float
    dsr_grid: float | None
    pbo: float | None
    min_track_record_years: float
    haircut_sharpe: float
    grid_sharpes: tuple[float, ...]
    equity: pd.Series = field(repr=False)
    benchmark_equity: pd.Series = field(repr=False)
    elapsed_s: float = 0.0

    def to_dict(self) -> dict[str, object]:
        """JSON-ready (finite numbers, curves as {date: value})."""
        def row(stats: StatsRow) -> dict[str, object]:
            return {key: _finite(value) if isinstance(value, float) else value for key, value in stats.__dict__.items()}

        return {
            "rule": HELLO_RULE["id"], "start": self.start, "end": self.end, "coins": list(self.coins), "data_source": self.data_source,
            "strategy": row(self.strategy), "btc_buy_hold": row(self.btc_buy_hold), "equal_weight": row(self.equal_weight),
            "psr": _finite(self.psr), "dsr_grid": _finite(self.dsr_grid), "research_trials": RESEARCH_TRIALS,
            "pbo": _finite(self.pbo), "min_track_record_years": _finite(self.min_track_record_years), "haircut_sharpe": _finite(self.haircut_sharpe),
            "grid_sharpes": [_finite(value) for value in self.grid_sharpes], "elapsed_s": round(self.elapsed_s, 2),
            "equity": {str(key): _finite(float(value)) for key, value in self.equity.items()},
            "benchmark_equity": {str(key): _finite(float(value)) for key, value in self.benchmark_equity.items()},
            "note": NOTE,
        }


def _finite(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def known_at_sessions(closes: pd.DataFrame, sessions: list[str]) -> pd.DataFrame:
    """Closes known on each session: the bar dated before it (a crypto bar dated D closes at the midnight after D)."""
    calendar = closes.sort_index().ffill()
    lagged = calendar.shift(1)
    return lagged.reindex(lagged.index.union(sessions)).ffill().reindex(sessions)


def _weekday_sessions(index: pd.Index, start: str, end: str) -> list[str]:
    days = pd.to_datetime(pd.Index(index))
    return [day.strftime("%Y-%m-%d") for day in days if day.weekday() < 5 and start <= day.strftime("%Y-%m-%d") <= end]


def rule_weights(closes: pd.DataFrame, *, start: str, end: str, params: dict[str, float] | None = None,
                 rebalance_every: int | None = None) -> pd.DataFrame:
    """The rule's decisions as a calendar dates x coins frame (rows without a decision are NaN), from `start` to `end`."""
    sessions = _weekday_sessions(closes.index, closes.index.min(), end)
    known = known_at_sessions(closes, sessions)
    rule_params = dict(params or HELLO_RULE["params"])  # type: ignore[arg-type]
    spec = SleeveSpec(str(HELLO_RULE["id"]), "hello", str(HELLO_RULE["kind"]), str(HELLO_RULE["family"]), tuple(HELLO_RULE["universe"]),  # type: ignore[arg-type]
                      int(rebalance_every or HELLO_RULE["rebalance_every"]), rule_params)  # type: ignore[call-overload]
    panel = ResearchPanel(known, {ticker: "crypto" for ticker in closes.columns})
    rows = signal_to_weights(sleeve_signal(spec, panel), panel, kind=spec.kind, rebalance_every=spec.rebalance_every, settings=WeightSettings(), start=start, end=end)
    # Built row by row: pandas 2 `from_dict` drops a date whose dict is empty, pandas 3 keeps it. An empty decision (no live
    # coin) means hold nothing, as `simulate_target_weights` and the forward ledger read it.
    days = sorted(rows)
    frame = pd.DataFrame([[float(rows[day].get(ticker, 0.0)) for ticker in closes.columns] for day in days], index=days, columns=closes.columns, dtype=float)
    frame = frame.reindex(closes.index)
    return frame[(frame.index >= start) & (frame.index <= end)].reindex(closes.index)


SAMPLE_SOURCE = "bundled sample (Coinbase public candles, 2021-06-01 to 2026-10-31)"


def load_closes(*, offline: bool = False, start: str = "2022-01-01", end: str | None = None, cache_dir: Path | None = None,
                get_json: Callable[[str], object] | None = None) -> tuple[pd.DataFrame, str, str | None]:
    """(closes, source, notice). Downloads the 11 coins from Coinbase's public candles (about 6 months before `start`,
    for the 120-session lookback) unless `offline`; any failure falls back to the bundled sample, with a one-line notice."""
    from aether_quant import samples
    from data_pipeline.public_candles import bars_to_panel, default_get_json, fetch_daily_bars

    sample = samples.load_sample_prices()
    if offline:
        return sample, SAMPLE_SOURCE, None
    last = date.fromisoformat(end) if end else datetime.now(timezone.utc).date()
    first = date.fromisoformat(start) - timedelta(days=200)
    try:
        bars, failed = fetch_daily_bars(list(sample.columns), first, last, get_json=get_json or default_get_json, cache_dir=cache_dir)
    except Exception as exc:  # noqa: BLE001 - any network failure falls back to the sample
        bars, failed = {}, [f"network: {exc}"]
    if bars and "BTCUSD" in bars and not failed:
        cache = "cache off" if cache_dir is None else f"cache {cache_dir}"
        return bars_to_panel(bars, "close"), f"Coinbase public candles, downloaded ({cache})", None
    return sample, SAMPLE_SOURCE, f"download incomplete ({', '.join(failed) or 'no data'}); using the bundled sample."


def _run(weights: pd.DataFrame, closes: pd.DataFrame, start: str, end: str) -> BacktestResult:
    window = closes[(closes.index >= start) & (closes.index <= end)]
    return backtest(weights.reindex(window.index), window, fill="close", cost_model=coinbase_model(end), periods_per_year=PERIODS_PER_YEAR,
                    min_weight_change=DEADBAND)


def run_hello(closes: pd.DataFrame, *, start: str = "2022-01-01", end: str | None = None, data_source: str = "sample") -> HelloReport:
    """The whole demo on a calendar dates x coins frame of closes (needs ~6 months of history before `start`)."""
    began = time.perf_counter()
    closes = closes.sort_index().astype(float)
    end = end or str(closes.index.max())
    weights = rule_weights(closes, start=start, end=end)
    result = _run(weights, closes, start, end)

    window = closes[(closes.index >= start) & (closes.index <= end)]
    btc = pd.DataFrame(np.nan, index=window.index, columns=window.columns)
    btc.iloc[0] = 0.0
    btc.iloc[0, list(window.columns).index("BTCUSD")] = 1.0
    btc_result = backtest(btc, window, fill="close", cost_model=coinbase_model(end), periods_per_year=PERIODS_PER_YEAR)
    equal = pd.DataFrame(np.nan, index=window.index, columns=window.columns)
    month_starts = ~pd.Series(pd.to_datetime(window.index).to_period("M"), index=window.index).duplicated()
    for day in window.index[month_starts.to_numpy()]:
        live = window.loc[day].notna()
        equal.loc[day] = np.where(live, 1.0 / max(int(live.sum()), 1), 0.0)
    equal_result = backtest(equal, window, fill="close", cost_model=coinbase_model(end), periods_per_year=PERIODS_PER_YEAR)

    grid_returns, grid_sharpes = [], []
    for lookback_a, lookback_c in product(GRID_A, GRID_C):
        variant = _run(rule_weights(closes, start=start, end=end, params={"lookback_a": lookback_a, "lookback_b": 60, "lookback_c": lookback_c}), closes, start, end)
        grid_returns.append(variant.returns.to_numpy(float))
        grid_sharpes.append(summary_statistics(variant.returns, periods_per_year=PERIODS_PER_YEAR)["sharpe_ratio"])
    matrix = np.column_stack(grid_returns)[1:]
    usable = len(matrix) - len(matrix) % 8
    pbo_value = probability_of_backtest_overfitting(matrix[-usable:], blocks=8, periods_per_year=PERIODS_PER_YEAR)["pbo"] if usable >= 80 else None

    net = result.returns.iloc[1:].to_numpy(float)
    stats = summary_statistics(result.returns, periods_per_year=PERIODS_PER_YEAR)
    dsr_grid = deflated_sharpe_ratio(net, grid_sharpes, periods_per_year=PERIODS_PER_YEAR)["value"]
    psr = probabilistic_sharpe_ratio(net, 0.0)
    min_trl = minimum_track_record_length(net, periods_per_year=PERIODS_PER_YEAR) / PERIODS_PER_YEAR
    haircut = haircut_sharpe(stats["sharpe_ratio"], len(net), RESEARCH_TRIALS, periods_per_year=PERIODS_PER_YEAR)["haircut_sharpe"]
    return HelloReport(
        start=str(window.index.min()), end=str(window.index.max()), coins=tuple(str(column) for column in closes.columns), data_source=data_source,
        strategy=StatsRow.from_result("Shipped rule", result), btc_buy_hold=StatsRow.from_result("BTC buy & hold", btc_result),
        equal_weight=StatsRow.from_result("Equal weight", equal_result), psr=float(psr) if psr is not None else float("nan"),
        dsr_grid=dsr_grid, pbo=pbo_value, min_track_record_years=min_trl, haircut_sharpe=haircut, grid_sharpes=tuple(grid_sharpes),
        equity=result.nav / result.nav.iloc[0], benchmark_equity=btc_result.nav / btc_result.nav.iloc[0], elapsed_s=time.perf_counter() - began,
    )


def _pct(value: float | None) -> str:
    return "n/a" if value is None or not math.isfinite(value) else f"{value:.1%}"


def _num(value: float | None) -> str:
    return "n/a" if value is None or not math.isfinite(value) else f"{value:.2f}"


def _table(report: HelloReport) -> list[tuple[str, str, str, str]]:
    rows = (report.strategy, report.btc_buy_hold, report.equal_weight)
    return [
        ("", *(row.name for row in rows)),
        ("CAGR", *(_pct(row.cagr) for row in rows)),
        ("Volatility", *(_pct(row.volatility) for row in rows)),
        ("Sharpe (no T-bill)", *(_num(row.sharpe) for row in rows)),
        ("Sortino", *(_num(row.sortino) for row in rows)),
        ("Max drawdown", *(_pct(row.max_drawdown) for row in rows)),
        ("Calmar", *(_num(row.calmar) for row in rows)),
        ("Avg gross exposure", *(_pct(row.average_gross) for row in rows)),
        ("Turnover / yr", *(f"{row.turnover:.1f}x" for row in rows)),
        ("Costs / yr", *(f"{row.cost_bps:.0f} bps" for row in rows)),
    ]  # type: ignore[list-item]


def _checks(report: HelloReport) -> list[tuple[str, str]]:
    return [
        ("Probabilistic Sharpe (vs 0)", _pct(report.psr)),
        ("PBO over an 8-variant lookback grid (CSCV)", f"{_num(report.pbo)}  (above 0.5: the best variant tends to lose out of sample)"),
        ("Deflated Sharpe, 8 grid trials", _pct(report.dsr_grid)),
        (f"Haircut Sharpe, the project's {RESEARCH_TRIALS} trials (BHY)", _num(report.haircut_sharpe)),
        ("Minimum track record for Sharpe > 0", f"{_num(report.min_track_record_years)} years"),
    ]


def _aligned(pairs: list[tuple[str, str]]) -> list[str]:
    width = max(len(name) for name, _ in pairs)
    return [f"{name.ljust(width)}  {value}" for name, value in pairs]


def render_text(report: HelloReport) -> str:
    """The plain-text report `aq hello` prints."""
    table = _table(report)
    widths = [max(len(str(row[column])) for row in table) for column in range(4)]
    lines = [
        "Aether Quant: hello world",
        "=========================",
        f"Rule     {HELLO_RULE['id']} (trend votes over 20/60/120 sessions, rebalanced every 5)",
        f"Data     {len(report.coins)} coins, {report.start} to {report.end}, {report.data_source}",
        "Costs    Coinbase taker fee 80 bps + 10 bps slippage per trade, 0.2% deadband",
        "",
    ]
    lines += ["  ".join(str(cell).rjust(widths[i]) if i else str(cell).ljust(widths[i]) for i, cell in enumerate(row)) for row in table]
    lines += [
        "",
        "Overfitting checks",
        "------------------",
        *_aligned(_checks(report)),
        "",
        NOTE,
        "",
        "Next: the notebooks (notebooks/README.md, each opens in Colab), the docs (https://leon1706-lol.github.io/Aether-quant/),",
        "      `aq hello --html report.html` for a page with the equity curve, and `aq --help`.",
        f"({report.elapsed_s:.1f} s)",
    ]
    return "\n".join(lines)


def _svg_curve(series: list[pd.Series], colors: list[str], width: int = 720, height: int = 260) -> str:
    values = np.concatenate([curve.to_numpy(float) for curve in series])
    values = values[np.isfinite(values)]
    low, high = (float(values.min()), float(values.max())) if values.size else (0.0, 1.0)
    span = high - low or 1.0
    paths = []
    for curve, color in zip(series, colors):
        data = curve.to_numpy(float)
        steps = max(len(data) - 1, 1)
        points = " ".join(f"{i / steps * width:.1f},{height - (value - low) / span * height:.1f}" for i, value in enumerate(data) if math.isfinite(value))
        paths.append(f'<polyline fill="none" stroke="{color}" stroke-width="1.6" points="{points}"/>')
    return f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="Equity curves">{"".join(paths)}</svg>'


def render_html(report: HelloReport) -> str:
    """A self-contained page: the table, the checks and the equity curve against BTC (no scripts, no external files)."""
    table = _table(report)
    head = "".join(f"<th>{html.escape(str(cell))}</th>" for cell in table[0])
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row) + "</tr>" for row in table[1:])
    checks = _checks(report)
    check_rows = "".join(f"<tr><td>{html.escape(name)}</td><td>{html.escape(value)}</td></tr>" for name, value in checks)
    svg = _svg_curve([report.equity, report.benchmark_equity], ["#d97706", "#64748b"])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aether Quant hello world</title><style>
:root{{color-scheme:light dark;--fg:#111827;--bg:#ffffff;--muted:#6b7280;--line:#e5e7eb}}
@media (prefers-color-scheme: dark){{:root{{--fg:#f3f4f6;--bg:#111827;--muted:#9ca3af;--line:#374151}}}}
body{{font:15px/1.5 system-ui,sans-serif;color:var(--fg);background:var(--bg);max-width:900px;margin:2rem auto;padding:0 16px}}
table{{border-collapse:collapse;width:100%;margin:1rem 0}}td,th{{border-bottom:1px solid var(--line);padding:.35rem .5rem;text-align:right}}
td:first-child,th:first-child{{text-align:left}}.muted{{color:var(--muted)}}</style></head><body>
<h1>Aether Quant: hello world</h1>
<p class="muted">{html.escape(str(HELLO_RULE["id"]))} on {len(report.coins)} coins, {html.escape(report.start)} to {html.escape(report.end)} ({html.escape(report.data_source)}). Coinbase taker fee plus slippage.</p>
<h2>Equity</h2>{svg}<p class="muted"><span style="color:#d97706">&#9632;</span> shipped rule &nbsp; <span style="color:#64748b">&#9632;</span> BTC buy &amp; hold</p>
<h2>Statistics</h2><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
<h2>Overfitting checks</h2><table><tbody>{check_rows}</tbody></table>
<p><strong>{html.escape(NOTE)}</strong></p></body></html>
"""
