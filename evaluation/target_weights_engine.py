"""Offline engine of the target-weights path (V6.5.0): the same orders as `main.py::_target_weights_tick`, in seconds.

Timeline of one decision dated D, as Lean runs it at daily resolution:
  * the equity bar of D arrives at 16:00 D; the row is read; crypto and forex closes known then are the bars dated D-1;
  * equity orders (including the T-bill sweep) fill at the next session's open;
  * crypto and forex orders wait for the bar dated D, which closes at the following midnight, and fill at its close.

A row labelled D is what Lean's daily sample of D shows: equities at the close of D, crypto and forex at the close of the bar
dated before D (the one that ended at midnight, as D began). That is the timing `known_closes` gives the signals too.

Cash is kept per currency, as Lean's cash book does, so a USD-base pair such as USDJPY earns its P&L in the quote currency.
Calls the pure functions main.py calls (`portfolio.target_weights`, `portfolio.financing`, `portfolio.cash_sweep`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from features.fx_carry import split_forex_ticker
from portfolio.cash_sweep import (
    cash_sweep_target_weight,
    margin_fraction,
    resolve_cash_sweep_config,
    sweep_order_needed,
)
from portfolio.financing import daily_financing_usd, rate_asof
from portfolio.target_weights import (
    NEXT_BAR_CLASSES,
    TargetWeightsConfig,
    equity_fee_usd,
    names_to_exit_without_bars,
    no_bar_exit_cost_usd,
    rebalance_deltas,
    slippage_bps_for,
    sweep_reserve,
    update_missing_bars,
    weights_at_tick,
)

SWEEP_CLASS = "cash_sweep"
CRYPTO_LOT = 1e-6


def coinbase_taker_bps(date: str) -> float:
    """Taker fee of Lean's date-effective CoinbaseFeeModel for a market order on a USD pair, in bps, as its fills show."""
    if date < "2019-10-08":
        return 30.0 if date < "2019-03-23" else 25.0
    return 80.0


def default_fee_usd(asset_class: str, notional: float, date: str, config: TargetWeightsConfig) -> float:
    if asset_class == "crypto":
        return abs(notional) * coinbase_taker_bps(date) / 1e4
    if asset_class == "forex":
        return 0.0 if notional == 0.0 else max(abs(notional) * 0.2 / 1e4, 2.0)
    return equity_fee_usd(notional, config.equity_fee_bps, config.equity_min_fee_usd)


@dataclass
class MarketPanel:
    """Bars by calendar date (a NaN where the ticker has no bar that day). `sessions` are the equity sessions."""

    dates: list[str]
    tickers: list[str]
    opens: np.ndarray
    closes: np.ndarray
    asset_class: dict[str, str]
    sessions: set[str] = field(default_factory=set)

    def index(self) -> dict[str, int]:
        return {ticker: i for i, ticker in enumerate(self.tickers)}


def load_market_panel(root: Path, config: dict, *, extra_equity: tuple[str, ...] = ("BIL",), data_dir: str = "data") -> MarketPanel:
    """Every universe asset plus the sweep ticker, from the Lean zips under `root/data_dir`."""
    from data_pipeline.data_audit import asset_zip_paths, read_lean_daily_zip

    frames: dict[str, pd.DataFrame] = {}
    classes: dict[str, str] = {}
    assets = list(config["phase1"]["universe"]["assets"])
    for ticker in extra_equity:
        if ticker not in {str(asset["ticker"]) for asset in assets}:
            assets.append({"ticker": ticker, "security_type": "equity", "asset_class": SWEEP_CLASS,
                           "data_path": f"data/equity/usa/daily/{ticker.lower()}.zip"})
    for asset in assets:
        path = asset_zip_paths(asset, Path(root) / data_dir)["trade"]
        if not path.exists():
            continue
        frame = read_lean_daily_zip(path, str(asset.get("security_type")))
        if frame.empty:
            continue
        ticker = str(asset["ticker"])
        frames[ticker] = frame.set_index(frame["date"].dt.strftime("%Y-%m-%d"))[["open", "close"]]
        classes[ticker] = str(asset.get("asset_class") or asset.get("security_type"))
    dates = sorted({date for frame in frames.values() for date in frame.index})
    tickers = sorted(frames)
    opens = np.full((len(dates), len(tickers)), np.nan)
    closes = np.full((len(dates), len(tickers)), np.nan)
    position = {date: i for i, date in enumerate(dates)}
    sessions: set[str] = set()
    for column, ticker in enumerate(tickers):
        frame = frames[ticker]
        rows = [position[date] for date in frame.index]
        opens[rows, column] = frame["open"].to_numpy(float)
        closes[rows, column] = frame["close"].to_numpy(float)
        if classes[ticker] in ("equity", "bond", SWEEP_CLASS):
            sessions.update(frame.index)
    return MarketPanel(dates, tickers, opens, closes, classes, sessions)


def _usd_rates(closes_ff: np.ndarray, index: Mapping[str, int]) -> dict[str, np.ndarray]:
    """USD per one unit of each currency, by date, from the USD pairs in the panel."""
    rates = {"USD": np.ones(closes_ff.shape[0])}
    for ticker, column in index.items():
        pair = split_forex_ticker(ticker)
        if pair is None:
            continue
        base, quote = pair
        if quote == "USD":
            rates[base] = closes_ff[:, column]
        elif base == "USD":
            with np.errstate(divide="ignore", invalid="ignore"):
                rates[quote] = 1.0 / closes_ff[:, column]
    return rates


def simulate_target_weights(
    weights_by_date: Mapping[str, Mapping[str, float]],
    panel: MarketPanel,
    config: TargetWeightsConfig,
    *,
    start: str,
    end: str,
    nav: float = 100_000.0,
    sweep_config: dict | None = None,
    sweep_ticker: str = "BIL",
    rf_dates: list[str] | None = None,
    rf_rates: list[float] | None = None,
    carry_fn: Callable[[str, str], float] | None = None,
    max_total_drawdown: float | None = None,
    max_drawdown_velocity: float | None = None,
    fee_fn: Callable[[str, float, str, TargetWeightsConfig], float] = default_fee_usd,
    lot_size: Mapping[str, float] | None = None,
) -> dict:
    """One path over [start, end]. Returns {"nav", "strategy" (ex-sweep daily return), "strategy_excess" (that, less the
    risk-free return on the net capital invested), "total" (daily return), "gross", "fees", "financing", "turnover", "fills",
    "locked_on"}, the series indexed by calendar date.

    "strategy" is what Lean reports. Ex-sweep, a long book pays nothing for the cash it ties up, which the sweep would have
    earned, so a long sleeve's Sharpe is raw and not excess unless it is scored on "strategy_excess". A forex position is
    self-financed and has no such cost.

    A drawdown lock (on the strategy, ex sweep, as main.py reads it) closes everything at the next fills and stops trading."""
    index = panel.index()
    classes = {ticker: panel.asset_class.get(ticker, "equity") for ticker in panel.tickers}
    next_bar_columns = [index[ticker] for ticker in panel.tickers if classes[ticker] in NEXT_BAR_CLASSES]
    closes_ff = pd.DataFrame(panel.closes).ffill().to_numpy(copy=True)  # pandas 3 hands out read-only views
    # a crypto or forex bar reaches this row's label when it ended, at the midnight that began this row
    if next_bar_columns:
        closes_ff[1:, next_bar_columns] = closes_ff[:-1, next_bar_columns].copy()
        closes_ff[0, next_bar_columns] = np.nan
    rates = _usd_rates(closes_ff, index)
    sweep = resolve_cash_sweep_config(sweep_config) if sweep_config else None
    sweep_column = index.get(sweep_ticker) if sweep and sweep.get("enabled") else None
    columns = [(ticker, column) for ticker, column in index.items() if column != sweep_column or sweep_column is None]
    pairs = {ticker: split_forex_ticker(ticker) if classes[ticker] == "forex" else None for ticker in panel.tickers}
    if lot_size is None:
        lot_size = {ticker: CRYPTO_LOT for ticker in panel.tickers if classes[ticker] == "crypto"}

    units = np.zeros(len(panel.tickers))
    cash: dict[str, float] = {"USD": float(nav)}
    pending_open: dict[str, float] = {}
    pending_target: dict[str, float] | None = None
    positions = [i for i, date in enumerate(panel.dates) if start <= date <= end]

    nav_series, strategy_series, excess_series, total_series, gross_series = {}, {}, {}, {}, {}
    net_invested_previous = 0.0
    previous_date = None
    missing_bars: dict[str, int] = {}
    no_bar_exits: list[str] = []
    fees = financing_total = traded = 0.0
    fills = 0
    previous_nav = None
    strategy_value = None
    sweep_pnl_previous = 0.0
    sweep_cost = 0.0
    sweep_units = 0.0
    peak = None
    previous_drawdown = 0.0
    locked_on = None
    last_financing_date = None

    def usd_rate(currency: str, row: int) -> float:
        series = rates.get(currency)
        value = float(series[row]) if series is not None else float("nan")
        return value if np.isfinite(value) and value > 0.0 else 0.0

    def unit_value(ticker: str, row: int) -> float:
        price = float(closes_ff[row, index[ticker]])
        if not np.isfinite(price) or price <= 0.0:
            return 0.0
        pair = pairs[ticker]
        return price * usd_rate(pair[1], row) if pair else price

    def value_now(row: int) -> float:
        total = sum(amount * usd_rate(currency, row) for currency, amount in cash.items())
        for ticker, column in index.items():
            if units[column] != 0.0 and pairs[ticker] is None:
                price = closes_ff[row, column]
                if np.isfinite(price):
                    total += units[column] * price
        return float(total)

    def fill(ticker: str, delta: float, raw_price: float, row: int, date: str) -> None:
        nonlocal fees, traded, fills, sweep_cost, sweep_units
        column = index[ticker]
        asset_class = classes[ticker]
        bps = 1.0 if column == sweep_column else slippage_bps_for(asset_class, config)
        price = raw_price * (1.0 + bps / 1e4) if delta > 0 else raw_price * (1.0 - bps / 1e4)
        pair = pairs[ticker]
        if pair:
            cash[pair[0]] = cash.get(pair[0], 0.0) + delta
            cash[pair[1]] = cash.get(pair[1], 0.0) - delta * price
            notional = abs(delta) * price * usd_rate(pair[1], row)
        else:
            cash["USD"] = cash["USD"] - delta * price
            notional = abs(delta) * price
        fee = fee_fn(asset_class if column != sweep_column else "equity", notional, date, config)
        cash["USD"] -= fee
        fees += fee
        traded += notional if column != sweep_column else 0.0
        fills += 1
        if column == sweep_column:
            sweep_cost += delta * price + fee
            sweep_units += delta
        units[column] += delta

    for row in positions:
        date = panel.dates[row]
        is_session = date in panel.sessions

        # a crypto or forex order fills as soon as its next bar has closed, at the midnight that begins this row
        if pending_target and row > 0:
            fresh = {ticker for ticker in pending_target if np.isfinite(panel.closes[row - 1, index[ticker]])}
            if fresh:
                held = {ticker: float(units[index[ticker]]) for ticker in fresh}
                values = {ticker: unit_value(ticker, row) for ticker in fresh}
                target = {ticker: weight for ticker, weight in pending_target.items() if ticker in fresh and weight != 0.0}
                deltas = rebalance_deltas(held, values, value_now(row), target, config, lot_size=lot_size, class_by_ticker=classes)
                for ticker, delta in deltas:
                    fill(ticker, delta, float(closes_ff[row, index[ticker]]), row, date)
                pending_target = {t: w for t, w in pending_target.items() if t not in fresh} or None

        if config.no_bar_exit:
            held_now = {ticker: float(units[column]) for ticker, column in columns if units[column] != 0.0}
            has_bar = {}
            for ticker in held_now:
                late = classes[ticker] in NEXT_BAR_CLASSES
                if not late and not is_session:
                    has_bar[ticker] = True  # an equity session did not happen: nothing went missing
                else:
                    has_bar[ticker] = row > 0 and np.isfinite(panel.closes[row - 1 if late else row, index[ticker]])
            missing_bars = update_missing_bars(missing_bars, held_now, has_bar)
            for ticker in names_to_exit_without_bars(missing_bars, config):
                column = index[ticker]
                price = unit_value(ticker, row)
                cash["USD"] += float(units[column]) * price - no_bar_exit_cost_usd(units[column], price, classes[ticker], config)
                units[column] = 0.0
                missing_bars.pop(ticker, None)
                pending_open.pop(ticker, None)
                if pending_target:
                    pending_target = {name: weight for name, weight in pending_target.items() if name != ticker} or None
                no_bar_exits.append(f"{date}:{ticker}")

        if is_session and pending_open:
            for ticker, delta in pending_open.items():
                raw = panel.opens[row, index[ticker]]
                if np.isfinite(raw) and raw > 0.0:
                    fill(ticker, delta, float(raw), row, date)
            pending_open = {}

        nav_now = value_now(row)

        if is_session and config.financing_enabled and last_financing_date is not None:
            days = (pd.Timestamp(date) - pd.Timestamp(last_financing_date)).days
            long_usd = short_usd = 0.0
            fx_positions = []
            for ticker, column in index.items():
                if units[column] == 0.0:
                    continue
                value = units[column] * unit_value(ticker, row)
                if pairs[ticker]:
                    fx_positions.append((value, carry_fn(ticker, date) if carry_fn else 0.0))
                elif value > 0.0:
                    long_usd += value
                else:
                    short_usd -= value
            rf = rate_asof(rf_dates or [], rf_rates or [], date)
            amount = daily_financing_usd(
                long_usd=long_usd, short_usd=short_usd, nav=nav_now, rf_annual_pct=rf, fx_positions=fx_positions,
                days=days, margin_spread_bps=config.margin_spread_bps, borrow_bps=config.borrow_bps,
                fx_spread_bps=config.fx_spread_bps,
            )
            cash["USD"] += amount
            financing_total += amount
            nav_now += amount
        if is_session:
            last_financing_date = date

        # main.py evaluates the lock on the session's own tick, with that session's close already in the marks
        if is_session and locked_on is None and peak and previous_nav:
            sweep_now = 0.0
            if sweep_column is not None and (sweep_units != 0.0 or sweep_cost != 0.0):
                sweep_price = closes_ff[row, sweep_column]
                if np.isfinite(sweep_price):
                    sweep_now = sweep_units * sweep_price - sweep_cost
            provisional = strategy_value * (1.0 + ((nav_now - previous_nav) - (sweep_now - sweep_pnl_previous)) / previous_nav)
            drawdown = 1.0 - provisional / max(peak, provisional)
            velocity = drawdown - previous_drawdown
            previous_drawdown = drawdown
            if (max_total_drawdown is not None and drawdown >= max_total_drawdown) or (
                max_drawdown_velocity is not None and velocity >= max_drawdown_velocity
            ):
                locked_on = date
                weights_by_date = {}
                pending_target = {
                    ticker: 0.0 for ticker in index
                    if units[index[ticker]] != 0.0 and classes[ticker] in NEXT_BAR_CLASSES
                } or None
                pending_open = {
                    ticker: -float(units[index[ticker]]) for ticker in index
                    if units[index[ticker]] != 0.0 and classes[ticker] not in NEXT_BAR_CLASSES and index[ticker] != sweep_column
                }

        if is_session:
            target_row = weights_at_tick(weights_by_date, date)
            if target_row is not None:
                target_row = {
                    ticker: (max(0.0, weight) if classes[ticker] == "crypto" else weight)
                    for ticker, weight in target_row.items() if ticker in index and index[ticker] != sweep_column
                }
                equity_like = {
                    ticker for ticker, column in index.items()
                    if classes[ticker] not in NEXT_BAR_CLASSES and column != sweep_column and (units[column] != 0.0 or ticker in target_row)
                }
                held = {ticker: float(units[index[ticker]]) for ticker in equity_like}
                values = {ticker: unit_value(ticker, row) for ticker in equity_like}
                target = {ticker: weight for ticker, weight in target_row.items() if ticker in equity_like}
                for ticker, delta in rebalance_deltas(held, values, nav_now, target, config, lot_size=lot_size, class_by_ticker=classes):
                    pending_open[ticker] = delta
                pending_target = {
                    ticker: target_row.get(ticker, 0.0) for ticker, column in index.items()
                    if classes[ticker] in NEXT_BAR_CLASSES and (ticker in target_row or units[column] != 0.0)
                } or None

            if sweep_column is not None:
                long_weight = short_weight = 0.0
                margin_inputs = []
                for ticker, column in index.items():
                    if column == sweep_column:
                        continue
                    quantity = units[column] + pending_open.get(ticker, 0.0)
                    if quantity == 0.0:
                        continue
                    weight = quantity * unit_value(ticker, row) / nav_now if nav_now > 0.0 else 0.0
                    margin_inputs.append(({"crypto": "crypto", "forex": "forex"}.get(classes[ticker], "equity"), weight))
                    if weight > 0.0:
                        long_weight += weight
                    else:
                        short_weight -= weight
                sweep_target = cash_sweep_target_weight(
                    long_weight=long_weight, short_weight=short_weight, margin_used=margin_fraction(margin_inputs),
                    reserve=sweep_reserve(config), config=sweep,
                )
                price = float(closes_ff[row, sweep_column])
                if np.isfinite(price) and price > 0.0 and nav_now > 0.0:
                    current = units[sweep_column] * price / nav_now
                    if sweep_order_needed(current, sweep_target, sweep["min_trade_weight"]):
                        quantity = float(int((sweep_target - current) * nav_now / price))
                        if sweep_target <= 0.0:
                            quantity = -float(units[sweep_column])
                        if quantity != 0.0:
                            pending_open[sweep_ticker] = quantity

        nav_now = value_now(row)
        sweep_pnl = 0.0
        if sweep_column is not None and (sweep_units != 0.0 or sweep_cost != 0.0):
            price = closes_ff[row, sweep_column]
            if np.isfinite(price):
                sweep_pnl = sweep_units * price - sweep_cost
        if previous_nav is not None and previous_nav > 0.0:
            total_series[date] = nav_now / previous_nav - 1.0
            strategy_series[date] = ((nav_now - previous_nav) - (sweep_pnl - sweep_pnl_previous)) / previous_nav
            days_held = (pd.Timestamp(date) - pd.Timestamp(previous_date)).days if previous_date else 1
            rf_annual = rate_asof(rf_dates or [], rf_rates or [], date) / 100.0
            excess_series[date] = strategy_series[date] - net_invested_previous * rf_annual * days_held / 365.0
        if nav_now > 0.0:
            net_invested_previous = sum(
                units[column] * unit_value(ticker, row) for ticker, column in columns if units[column] != 0.0 and pairs[ticker] is None
            ) / nav_now
        previous_date = date
        previous_nav = nav_now
        sweep_pnl_previous = sweep_pnl
        nav_series[date] = nav_now
        gross_series[date] = (
            sum(abs(units[column]) * unit_value(ticker, row) for ticker, column in columns if units[column] != 0.0) / nav_now
            if nav_now > 0.0 else 0.0
        )

        if strategy_value is None:
            strategy_value = nav_now
            peak = nav_now
        elif date in strategy_series:
            strategy_value *= 1.0 + strategy_series[date]
            peak = max(peak, strategy_value)

    years = max(len(positions) / 365.25, 1e-9)
    return {
        "nav": pd.Series(nav_series, dtype=float),
        "strategy": pd.Series(strategy_series, dtype=float),
        "strategy_excess": pd.Series(excess_series, dtype=float),
        "no_bar_exits": no_bar_exits,
        "total": pd.Series(total_series, dtype=float),
        "gross": pd.Series(gross_series, dtype=float),
        "fees": fees,
        "financing": financing_total,
        "turnover": traded / (sum(nav_series.values()) / len(nav_series) if nav_series else float(nav)) / years,
        "fills": fills,
        "locked_on": locked_on,
    }
