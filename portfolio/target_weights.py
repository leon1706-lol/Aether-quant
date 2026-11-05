"""Target-weights path (V6.5.0, `phase_v2.target_weights`, default off): a run that holds a file of target weights.

The gated live path is too complex to replicate offline: the simulator tracks Lean at a daily correlation of about 0.73 and
has disagreed with it in sign. This path has no gates between a weight and its order, so an offline engine
(`evaluation/target_weights_engine.py`, same functions) can track Lean closely enough to select on.

A row `date,ticker,weight` is a decision taken at the equity close of `date`. Equities fill at the next session's open.
Crypto and forex bars close at the following midnight, so their orders wait for that bar and fill at its close: sent
on the equity tick they would fill at a price 16 hours old, which flatters any signal with positive daily autocorrelation.

Stdlib only at import; never raises on bad numbers except in `load_weight_file`, where a damaged file must stop the run.
"""

from __future__ import annotations

import csv
import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from portfolio.cash_sweep import strategy_reserve

DEFAULT_SLIPPAGE_BPS = {"equity": 3.0, "bond": 3.0, "forex": 1.0, "crypto": 10.0}
NEXT_BAR_CLASSES = frozenset({"crypto", "forex"})


@dataclass(frozen=True)
class TargetWeightsConfig:
    enabled: bool = False
    weights_path: str = ""
    weights_sha256: str = ""
    min_weight_change: float = 0.002
    min_trade_usd: float = 100.0
    forex_min_trade_usd: float = 5000.0
    reserve_gross: float = 0.3
    equity_fee_bps: float = 1.5
    equity_min_fee_usd: float = 1.0
    slippage_bps_by_class: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_SLIPPAGE_BPS))
    financing_enabled: bool = True
    margin_spread_bps: float = 150.0
    borrow_bps: float = 25.0
    fx_spread_bps: float = 50.0


def _finite(value, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def resolve_target_weights_config(raw: Mapping | None) -> TargetWeightsConfig:
    raw = raw or {}
    defaults = TargetWeightsConfig()
    numbers = {
        name: max(0.0, _finite(raw.get(name, getattr(defaults, name)), getattr(defaults, name)))
        for name in (
            "min_weight_change", "min_trade_usd", "forex_min_trade_usd", "reserve_gross", "equity_fee_bps",
            "equity_min_fee_usd", "margin_spread_bps", "borrow_bps", "fx_spread_bps",
        )
    }
    slippage = {**DEFAULT_SLIPPAGE_BPS}
    for name, value in (raw.get("slippage_bps_by_class") or {}).items():
        slippage[str(name)] = max(0.0, _finite(value, slippage.get(str(name), 0.0)))
    return TargetWeightsConfig(
        enabled=bool(raw.get("enabled", False)),
        weights_path=str(raw.get("weights_path") or ""),
        weights_sha256=str(raw.get("weights_sha256") or ""),
        slippage_bps_by_class=slippage,
        financing_enabled=bool(raw.get("financing_enabled", True)),
        **numbers,
    )


def load_weight_file(path: Path | str, expected_sha256: str = "") -> dict[str, dict[str, float]]:
    """date -> ticker -> weight. Raises ValueError on a hash mismatch, a malformed row or a non-finite weight: a run
    must not trade a file other than the one its config froze."""
    path = Path(path)
    payload = path.read_bytes()
    if expected_sha256:
        actual = hashlib.sha256(payload).hexdigest()
        if actual != expected_sha256:
            raise ValueError(f"{path.name}: sha256 {actual} is not the frozen {expected_sha256}")
    weights: dict[str, dict[str, float]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not {"date", "ticker", "weight"} <= set(reader.fieldnames):
            raise ValueError(f"{path.name}: expected the columns date,ticker,weight")
        for row in reader:
            value = float(row["weight"])
            if not math.isfinite(value):
                raise ValueError(f"{path.name}: non-finite weight for {row['ticker']} on {row['date']}")
            weights.setdefault(row["date"][:10], {})[row["ticker"]] = value
    return weights


def write_weight_file(weights_by_date: Mapping[str, Mapping[str, float]], path: Path | str) -> str:
    """Writes the file (LF, rows sorted, so one set of weights has one hash) and returns its sha256. A date with no
    positions gets a `__FLAT__` row with weight 0: without it, "go flat" would read as "no decision today"."""
    lines = ["date,ticker,weight"]
    for date in sorted(weights_by_date):
        row = {ticker: weight for ticker, weight in weights_by_date[date].items() if abs(_finite(weight, 0.0)) > 0.0}
        if not row:
            lines.append(f"{date},{FLAT_TICKER},0")
        for ticker in sorted(row):
            lines.append(f"{date},{ticker},{float(row[ticker]):.8f}")
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    Path(path).write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


FLAT_TICKER = "__FLAT__"


def weights_at_tick(weights: Mapping[str, Mapping[str, float]], tick_date: str) -> dict[str, float] | None:
    """The decision taken at this date's equity close; None when the file has no row for it (hold what is held)."""
    row = weights.get(str(tick_date)[:10])
    if row is None:
        return None
    return {ticker: float(weight) for ticker, weight in row.items() if ticker != FLAT_TICKER}


def rebalance_deltas(
    held_units: Mapping[str, float],
    usd_per_unit: Mapping[str, float],
    nav: float,
    target: Mapping[str, float],
    config: TargetWeightsConfig,
    *,
    lot_size: Mapping[str, float] | None = None,
    class_by_ticker: Mapping[str, str] | None = None,
) -> list[tuple[str, float]]:
    """(ticker, signed units to trade), reductions first: Lean checks buying power when an order is submitted and does
    not net sells that have not filled. A ticker with no usable price is skipped, never traded on a guess. A ticker the
    target omits is closed in full; otherwise a change below the deadband or the minimum trade size is left alone."""
    nav = _finite(nav, 0.0)
    if nav <= 0.0:
        return []
    lots = lot_size or {}
    classes = class_by_ticker or {}
    orders: list[tuple[str, float, bool]] = []
    for ticker in sorted(set(held_units) | set(target)):
        unit_value = _finite(usd_per_unit.get(ticker), 0.0)
        if unit_value <= 0.0:
            continue
        held = _finite(held_units.get(ticker, 0.0), 0.0)
        wanted = _finite(target.get(ticker, 0.0), 0.0)
        if wanted == 0.0:
            if held != 0.0:
                orders.append((ticker, -held, True))
            continue
        current = held * unit_value / nav
        if abs(wanted - current) < config.min_weight_change:
            continue
        lot = _finite(lots.get(ticker, 1.0), 1.0)
        lot = lot if lot > 0.0 else 1.0
        delta = math.trunc((wanted - current) * nav / unit_value / lot) * lot
        notional = abs(delta) * unit_value
        minimum = config.forex_min_trade_usd if classes.get(ticker) == "forex" else config.min_trade_usd
        if delta == 0.0 or notional < minimum:
            continue
        reduces = held != 0.0 and (delta < 0.0) == (held > 0.0)
        orders.append((ticker, delta, reduces))
    orders.sort(key=lambda order: (not order[2], order[0]))
    return [(ticker, delta) for ticker, delta, _ in orders]


def equity_fee_usd(notional: float, bps: float, min_usd: float) -> float:
    """Commission in basis points with a dollar minimum. Used instead of Lean's per-share IB model on this path: the
    data is split- and dividend-adjusted, so an old adjusted price of $0.49 would make a per-share fee 1% of the trade."""
    notional = abs(_finite(notional, 0.0))
    return 0.0 if notional <= 0.0 else max(notional * bps / 1e4, min_usd)


def slippage_bps_for(asset_class: str, config: TargetWeightsConfig) -> float:
    return float(config.slippage_bps_by_class.get(str(asset_class), 0.0))


def sweep_reserve(config: TargetWeightsConfig) -> dict:
    """What the T-bill sweep leaves free for the next session's orders on this path: a fixed share of gross, since the
    next row of the file must not be read before its date."""
    return strategy_reserve(
        rebalance_next=True, book_gross_cap=config.reserve_gross, max_short_exposure=config.reserve_gross,
        formed_long=0.0, formed_short=0.0, book_long=0.0, book_short=0.0, other_budget_remaining=0.0,
    )
