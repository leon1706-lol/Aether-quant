"""Forex position sizing - leverage-utilization-targeted, the FX sibling
of risk/futures_risk.py's margin-utilization-targeted model (not the
volatility-of-notional model risk/position_sizing.py uses for equity/
crypto/bond).

Forex trades in whole LOTS (this module follows futures' own "whole
units, never fractional weights" convention for consistency, rather than
supporting fractional/micro lots), and the real constraint is how much of
the account's margin a position consumes at the pair's max leverage - the
same "budget, not volatility" shape risk/futures_risk.py already
established for futures, adapted to lot_size/leverage_max/margin_pct
instead of a fixed per-contract multiplier/margin (forex margin scales
with the pair's CURRENT price, unlike futures' fixed initial_margin_usd
per contract - "one lot" is a fixed base-currency notional, not a fixed
dollar margin).

V4.6 (development/Problems.md, Roadmap "Assets") - code-complete,
IB/Lean-backtest-unverified, the exact same status futures/options
shipped with: main.py::_add_asset() wires self.add_forex(), but zero
forex tickers are configured in phase1.universe.assets and
phase_v2.forex_risk.enabled defaults False.

Confirmed via direct Lean source inspection that Forex is fully
first-class in this Lean version (SecurityType.Forex,
Common/Securities/Forex/Forex.cs, real pip-size/lot-size symbol
properties) - unlike individual bonds (see features/bond_features.py's
own module docstring), there is no native-support question here."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PAIR_SPECS_PATH = Path(__file__).resolve().parents[1] / "data" / "reference" / "forex_pair_specs.json"


@dataclass(frozen=True)
class ForexSizingDecision:
    lot_count: int
    notional_value: float
    margin_required: float
    margin_utilization: float
    target_weight: float
    base_target_weight: float
    confidence_multiplier: float
    max_leverage_utilization: float
    sizing_reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def load_forex_pair_specs(path: Path = DEFAULT_PAIR_SPECS_PATH) -> dict:
    """Defensive load - returns {} (not a raised exception) on a missing or
    unparseable specs file, same convention as
    risk/futures_risk.py::load_futures_contract_specs(). A missing spec
    for a given pair means build_forex_position_sizing() can't size it -
    callers must treat that as "no position", not a crash."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("load_forex_pair_specs(%s): unreadable — %s", path, exc)
        return {}
    return {key: value for key, value in data.items() if not key.startswith("_")}


def build_forex_position_sizing(
    base_target_weight: float,
    confidence: float,
    price: float,
    pair_spec: dict | None,
    portfolio_value: float,
    target_leverage_utilization: float = 0.20,
    max_leverage_utilization: float = 0.40,
) -> ForexSizingDecision:
    """Leverage-utilization-targeted sizing: computes the max lots
    affordable at max_leverage_utilization (the hard ceiling), then scales
    toward target_leverage_utilization by confidence using the same
    "0.5 + 0.5*confidence" shape as
    risk/futures_risk.py::build_futures_position_sizing()'s
    confidence_multiplier, and floors to an integer lot_count.

    Per-lot margin is `lot_size * price * margin_pct` (equivalently
    `lot_size * price / leverage_max`, since margin_pct and leverage_max
    are reciprocals by construction in forex_pair_specs.json).

    target_weight is a DERIVED reconciliation value for downstream
    weight-based consumers (exposure caps) - lot_count is the source of
    truth and is what main.py::_apply_signal() actually executes via
    MarketOrder(), never fed back into SetHoldings().

    Returns an all-zero decision (lot_count=0) when pair_spec is
    missing/empty, confidence is 0, base_target_weight is 0, or
    portfolio_value/price/lot_size/margin_pct are non-positive - never
    raises, matching risk/futures_risk.py's "no active signal -> zero
    position" convention."""
    confidence = max(0.0, min(float(confidence), 1.0))
    base_target_weight = float(base_target_weight)
    portfolio_value = max(float(portfolio_value), 0.0)
    price = max(float(price), 0.0)
    max_leverage_utilization = max(float(max_leverage_utilization), 0.0)
    target_leverage_utilization = max(0.0, min(float(target_leverage_utilization), max_leverage_utilization))

    pair_spec = pair_spec or {}
    lot_size = float(pair_spec.get("lot_size", 0.0))
    margin_pct = float(pair_spec.get("margin_pct", 0.0))

    if (
        base_target_weight == 0.0
        or confidence == 0.0
        or portfolio_value <= 0.0
        or price <= 0.0
        or lot_size <= 0.0
        or margin_pct <= 0.0
    ):
        return ForexSizingDecision(
            lot_count=0,
            notional_value=0.0,
            margin_required=0.0,
            margin_utilization=0.0,
            target_weight=0.0,
            base_target_weight=base_target_weight,
            confidence_multiplier=0.0,
            max_leverage_utilization=max_leverage_utilization,
            sizing_reason="no_active_signal_or_missing_pair_spec",
        )

    margin_per_lot = lot_size * price * margin_pct
    confidence_multiplier = 0.5 + 0.5 * confidence
    max_lots_affordable = int(portfolio_value * max_leverage_utilization // margin_per_lot)
    lots_at_target = int(portfolio_value * target_leverage_utilization // margin_per_lot)
    lot_count = min(int(lots_at_target * confidence_multiplier), max_lots_affordable)
    lot_count = max(lot_count, 0)

    direction = 1.0 if base_target_weight >= 0.0 else -1.0
    notional_value = lot_count * lot_size * price
    margin_required = lot_count * margin_per_lot
    margin_utilization = margin_required / portfolio_value if portfolio_value > 0.0 else 0.0
    target_weight = direction * (notional_value / portfolio_value) if portfolio_value > 0.0 else 0.0

    sizing_reason = "no_active_signal_or_missing_pair_spec" if lot_count == 0 else "leverage_utilization_scaled_sizing"

    return ForexSizingDecision(
        lot_count=int(direction) * lot_count,
        notional_value=notional_value,
        margin_required=margin_required,
        margin_utilization=margin_utilization,
        target_weight=target_weight,
        base_target_weight=base_target_weight,
        confidence_multiplier=confidence_multiplier,
        max_leverage_utilization=max_leverage_utilization,
        sizing_reason=sizing_reason,
    )
