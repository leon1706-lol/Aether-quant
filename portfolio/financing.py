"""Daily financing of the target-weights path (V6.5.0): what a broker charges and Lean does not.

Lean charges no margin interest and no stock borrow, and pays no FX swap (`portfolio/cash_sweep.py`), so a leveraged or carry
candidate looks better in a backtest than it can be live. main.py books this amount on the USD cash and the offline
engine adds it to its cash, so both see the same charge.

Pure, NaN-safe. A negative result is a cost.
"""

from __future__ import annotations

import bisect
import csv
import math
from collections.abc import Iterable
from pathlib import Path

DAY_COUNT = 360.0


def _finite(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def daily_financing_usd(
    *,
    long_usd: float,
    short_usd: float,
    nav: float,
    rf_annual_pct: float,
    fx_positions: Iterable[tuple[float, float]] = (),
    days: float = 1.0,
    margin_spread_bps: float = 150.0,
    borrow_bps: float = 25.0,
    fx_spread_bps: float = 50.0,
) -> float:
    """Financing for `days` calendar days. `long_usd` and `short_usd` (positive) cover everything but forex, including
    the T-bill sweep. The debit is what the longs need beyond NAV and the short proceeds, charged at the risk-free rate
    plus the spread. Each forex position is (signed USD notional of the base currency, r_base - r_quote in percentage points):
    long the base earns the differential, either way less the spread. Positive cash earns nothing, as in Lean."""
    days = max(0.0, _finite(days))
    if days == 0.0:
        return 0.0
    long_value, short_value = abs(_finite(long_usd)), abs(_finite(short_usd))
    debit = max(0.0, long_value - short_value - _finite(nav))
    rate = max(0.0, _finite(rf_annual_pct) + _finite(margin_spread_bps) / 100.0)
    amount = -debit * rate / 100.0
    amount -= short_value * _finite(borrow_bps) / 1e4
    for notional, carry_pct in fx_positions:
        value = _finite(notional)
        amount += value * _finite(carry_pct) / 100.0
        amount -= abs(value) * _finite(fx_spread_bps) / 1e4
    return amount * days / DAY_COUNT


def load_rate_series(path: Path | str) -> tuple[list[str], list[float]]:
    """(ISO dates, rates in percent) of Lean's `interest-rate.csv`; empty when the file is missing or unreadable, so a
    run without it charges a 0% base rate plus the spread rather than failing."""
    dates: list[str] = []
    rates: list[float] = []
    try:
        with Path(path).open(newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
    except OSError:
        return [], []
    for row in rows[1:]:
        if len(row) >= 2:
            value = _finite(row[1], float("nan"))
            if math.isfinite(value):
                dates.append(row[0][:10])
                rates.append(value)
    return dates, rates


def rate_asof(dates: list[str], rates: list[float], date: str) -> float:
    """The last rate at or before `date`; 0.0 before the first observation."""
    index = bisect.bisect_right(dates, str(date)[:10]) - 1
    return rates[index] if index >= 0 else 0.0
