"""Futures position sizing - margin-utilization-targeted, not the
volatility-of-notional model risk/position_sizing.py uses for equity/crypto/
bond.

Margin, contract count, and mark-to-market are fundamentally different from
a portfolio-weight-scaled sizing model: Lean trades futures in whole
contracts (not fractional weights), and the real constraint is how much of
the account's margin budget a position consumes, not how much daily-return
volatility it contributes. This module is deliberately separate from
risk/position_sizing.py rather than a new branch inside it - see
risk/asset_class_router.py for how its FuturesSizingDecision output gets
adapted onto the shared PositionSizingDecision shape everything downstream
(portfolio/book_construction.py, liquidity, analyzer, _apply_signal())
consumes.

Continuous-futures rollover/mark-to-market itself is NOT reimplemented here
- that's entirely delegated to Lean's native add_future() + continuous-
contract SetFilter() mapping (main.py::_add_asset()). rollover_due() below
is a diagnostic/logging signal only, never a trade trigger - a second,
hand-rolled rollover state machine racing against Lean's own would be a bug
class, not a feature.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CONTRACT_SPECS_PATH = Path(__file__).resolve().parents[1] / "data" / "reference" / "futures_contract_specs.json"


@dataclass(frozen=True)
class FuturesSizingDecision:
    contract_count: int
    notional_value: float
    margin_required: float
    margin_utilization: float
    target_weight: float
    base_target_weight: float
    confidence_multiplier: float
    max_margin_utilization: float
    sizing_reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def load_futures_contract_specs(path: Path = DEFAULT_CONTRACT_SPECS_PATH) -> dict:
    """Defensive load - returns {} (not a raised exception) on a missing or
    unparseable specs file, same convention as train.py::load_sector_mapping().
    A missing spec for a given ticker means build_futures_position_sizing()
    can't size it - callers must treat that as "no position", not a crash."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("load_futures_contract_specs(%s): unreadable — %s", path, exc)
        return {}
    return {key: value for key, value in data.items() if not key.startswith("_")}


def build_futures_position_sizing(
    base_target_weight: float,
    confidence: float,
    price: float,
    contract_spec: dict | None,
    portfolio_value: float,
    target_margin_utilization: float = 0.20,
    max_margin_utilization: float = 0.40,
) -> FuturesSizingDecision:
    """Margin-utilization-targeted sizing: computes the max contracts
    affordable at max_margin_utilization (the hard ceiling), then scales
    toward target_margin_utilization by confidence using the same
    "0.5 + 0.5*confidence" shape as
    risk/position_sizing.py::build_dynamic_position_sizing()'s
    confidence_multiplier, and floors to an integer contract_count (Lean
    trades futures in whole contracts, never fractional weights).

    target_weight is a DERIVED reconciliation value for downstream weight-
    based consumers (exposure caps, book construction) - contract_count is
    the source of truth and is what main.py::_apply_signal() actually
    executes via MarketOrder(), never fed back into SetHoldings().

    Returns an all-zero decision (contract_count=0) when contract_spec is
    missing/empty, confidence is 0, base_target_weight is 0, or
    portfolio_value/price/multiplier/margin are non-positive - never
    raises, matching risk/position_sizing.py's "no active signal -> zero
    weight" convention."""
    confidence = max(0.0, min(float(confidence), 1.0))
    base_target_weight = float(base_target_weight)
    portfolio_value = max(float(portfolio_value), 0.0)
    price = max(float(price), 0.0)
    max_margin_utilization = max(float(max_margin_utilization), 0.0)
    target_margin_utilization = max(0.0, min(float(target_margin_utilization), max_margin_utilization))

    contract_spec = contract_spec or {}
    multiplier = float(contract_spec.get("multiplier", 0.0))
    margin_per_contract = float(contract_spec.get("initial_margin_usd", 0.0))

    if (
        base_target_weight == 0.0
        or confidence == 0.0
        or portfolio_value <= 0.0
        or price <= 0.0
        or multiplier <= 0.0
        or margin_per_contract <= 0.0
    ):
        return FuturesSizingDecision(
            contract_count=0,
            notional_value=0.0,
            margin_required=0.0,
            margin_utilization=0.0,
            target_weight=0.0,
            base_target_weight=base_target_weight,
            confidence_multiplier=0.0,
            max_margin_utilization=max_margin_utilization,
            sizing_reason="no_active_signal_or_missing_contract_spec",
        )

    confidence_multiplier = 0.5 + 0.5 * confidence
    max_contracts_affordable = int(portfolio_value * max_margin_utilization // margin_per_contract)
    contracts_at_target = int(portfolio_value * target_margin_utilization // margin_per_contract)
    contract_count = min(int(contracts_at_target * confidence_multiplier), max_contracts_affordable)
    contract_count = max(contract_count, 0)

    direction = 1.0 if base_target_weight >= 0.0 else -1.0
    notional_value = contract_count * multiplier * price
    margin_required = contract_count * margin_per_contract
    margin_utilization = margin_required / portfolio_value if portfolio_value > 0.0 else 0.0
    target_weight = direction * (notional_value / portfolio_value) if portfolio_value > 0.0 else 0.0

    sizing_reason = "no_active_signal_or_missing_contract_spec" if contract_count == 0 else "margin_utilization_scaled_sizing"

    return FuturesSizingDecision(
        contract_count=int(direction) * contract_count,
        notional_value=notional_value,
        margin_required=margin_required,
        margin_utilization=margin_utilization,
        target_weight=target_weight,
        base_target_weight=base_target_weight,
        confidence_multiplier=confidence_multiplier,
        max_margin_utilization=max_margin_utilization,
        sizing_reason=sizing_reason,
    )


def rollover_due(current_date: date, contract_expiry_date: date | None, rollover_days_before_expiry: int = 5) -> bool:
    """Pure date comparison - a diagnostic/logging signal only. Actual
    contract rollover is entirely delegated to Lean's native add_future() +
    continuous-contract SetFilter() mapping (main.py::_add_asset()); this
    function must never itself trigger a trade. Returns False when
    contract_expiry_date is unknown (e.g. Lean's continuous-contract
    subscription hasn't surfaced the mapped contract's expiry yet)."""
    if contract_expiry_date is None:
        return False
    return (contract_expiry_date - current_date).days <= rollover_days_before_expiry
