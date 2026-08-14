"""V5.3.1 (development/Problems.md #34/#96) - an offline, counterfactual
answer to "how often would a real limit order actually fill" without a
live Lean run: for every (ticker, date) row in an existing dataset, this
computes a limit price the exact same way main.py's real order placement
does (execution.order_gate.resolve_limit_price(), the SAME pure function,
not a re-derived approximation), then scans that ticker's own next
`unfilled_timeout_bars` rows' high/low columns to determine whether a real
Lean fill engine plausibly would have crossed it.

APPROXIMATION, NOT A REPLAY (read before trusting these numbers): this
simulates a signal firing on EVERY row, independent of whether main.py's
book/gates would have actually placed an order that day - it measures "if
an order were placed here, would it fill", not "how many of the real
orders in a given backtest filled" (development/Problems.md #34/#96's own
real order-events.json evidence is the ground truth for the latter
question; this module is deliberately a different, complementary
question). It also has no intrabar depth/tick data (only daily OHLC), so
it can only ever answer "did price trade through the limit", never
simulate a genuine partial fill - the same historical-bar-CSV ceiling
that makes PartiallyFilled unverifiable offline at all (see #34/#96's
verification notes)."""

from __future__ import annotations

import pandas as pd

from execution.order_gate import resolve_limit_price


def simulate_limit_fills(
    dataset: pd.DataFrame,
    *,
    unfilled_timeout_bars: int,
    offset_multiplier: float = 1.0,
    ticker_column: str = "ticker",
    date_column: str = "date",
    security_type_column: str = "security_type",
) -> dict:
    """Per ticker (grouped, sorted by date_column): for every row with at
    least `unfilled_timeout_bars` rows of data remaining for that ticker
    (rows too close to the end of a ticker's history are EXCLUDED from the
    denominator entirely, not counted as a timeout - a thin-data edge
    effect, not a real timeout, matching calibrate_book_confidence_spread()'s
    own "excluded, not counted as 0" convention), simulates BOTH a buy and
    a sell limit order (the real book trades both long and short, so
    simulating only one side would under-cover the calibration question).

    A buy fills the first bar (within the timeout window) whose `low`
    reaches at/below the buy limit price; a sell fills the first bar whose
    `high` reaches at/above the sell limit price - otherwise it's a
    timeout. `liquidity_spread_proxy` (already in ml/datasets/*.csv, the
    same column execution.order_gate.resolve_limit_price() expects as
    spread_fraction) supplies the spread input.

    Returns {"overall": {...}, "by_asset_class": {security_type: {...}},
    "by_side": {"buy": {...}, "sell": {...}}}, each a dict of
    {"num_signals", "fill_rate", "timeout_rate", "mean_bars_to_fill"}.
    An empty/all-thin dataset returns all-zero stats, never raises."""
    records: list[dict] = []

    has_security_type = security_type_column in dataset.columns
    for _ticker, group in dataset.groupby(ticker_column, sort=False):
        group = group.sort_values(date_column).reset_index(drop=True)
        closes = group["close"].to_numpy()
        highs = group["high"].to_numpy()
        lows = group["low"].to_numpy()
        spreads = group["liquidity_spread_proxy"].to_numpy()
        security_types = group[security_type_column].to_numpy() if has_security_type else [None] * len(group)
        num_rows = len(group)

        for i in range(num_rows):
            if i + unfilled_timeout_bars >= num_rows:
                continue  # too close to the end of this ticker's data - excluded, not a timeout
            reference_price = float(closes[i])
            raw_spread = spreads[i]
            spread_fraction = 0.0 if pd.isna(raw_spread) else float(raw_spread)
            security_type = security_types[i]

            for is_buy in (True, False):
                limit_price = resolve_limit_price(reference_price, spread_fraction, is_buy, offset_multiplier)
                bars_to_fill = None
                for offset in range(1, unfilled_timeout_bars + 1):
                    j = i + offset
                    crossed = lows[j] <= limit_price if is_buy else highs[j] >= limit_price
                    if crossed:
                        bars_to_fill = offset
                        break
                records.append(
                    {
                        "side": "buy" if is_buy else "sell",
                        "security_type": security_type,
                        "filled": bars_to_fill is not None,
                        "bars_to_fill": bars_to_fill,
                    }
                )

    return {
        "overall": _summarize_fill_records(records),
        "by_asset_class": {
            str(security_type): _summarize_fill_records(group_records)
            for security_type, group_records in _group_by(records, "security_type").items()
        },
        "by_side": {
            side: _summarize_fill_records(group_records) for side, group_records in _group_by(records, "side").items()
        },
    }


def sweep_limit_fill_offsets(
    dataset: pd.DataFrame,
    *,
    unfilled_timeout_bars: int,
    offset_multipliers: list[float],
    ticker_column: str = "ticker",
    date_column: str = "date",
    security_type_column: str = "security_type",
) -> dict:
    """Runs simulate_limit_fills() once per offset_multiplier - calibration
    insight into how a more/less passive limit placement trades off fill
    rate vs. price improvement. Returns {str(multiplier): result}."""
    return {
        str(multiplier): simulate_limit_fills(
            dataset,
            unfilled_timeout_bars=unfilled_timeout_bars,
            offset_multiplier=multiplier,
            ticker_column=ticker_column,
            date_column=date_column,
            security_type_column=security_type_column,
        )
        for multiplier in offset_multipliers
    }


def _group_by(records: list[dict], key: str) -> dict:
    groups: dict = {}
    for record in records:
        groups.setdefault(record[key], []).append(record)
    return groups


def _summarize_fill_records(records: list[dict]) -> dict:
    num_signals = len(records)
    if num_signals == 0:
        return {"num_signals": 0, "fill_rate": 0.0, "timeout_rate": 0.0, "mean_bars_to_fill": None}
    num_filled = sum(1 for record in records if record["filled"])
    bars_to_fill_values = [record["bars_to_fill"] for record in records if record["bars_to_fill"] is not None]
    return {
        "num_signals": num_signals,
        "fill_rate": num_filled / num_signals,
        "timeout_rate": (num_signals - num_filled) / num_signals,
        "mean_bars_to_fill": (sum(bars_to_fill_values) / len(bars_to_fill_values)) if bars_to_fill_values else None,
    }
