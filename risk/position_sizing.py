"""Dynamic position sizing for Aether Quant V2."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass


TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class PositionSizingDecision:
    base_target_weight: float
    target_weight: float
    rolling_volatility: float
    annualized_volatility: float
    volatility_regime: str
    volatility_multiplier: float
    confidence_multiplier: float
    leverage_factor: float
    max_leverage: float
    sizing_reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def classify_volatility_regime(
    rolling_volatility: float,
    low_volatility_threshold: float,
    high_volatility_threshold: float,
) -> str:
    volatility = abs(float(rolling_volatility))
    if volatility >= high_volatility_threshold:
        return "high_volatility"
    if volatility <= low_volatility_threshold:
        return "low_volatility"
    return "normal_volatility"


def build_dynamic_position_sizing(
    base_target_weight: float,
    confidence: float,
    rolling_volatility: float,
    max_position_weight: float,
    target_daily_volatility: float = 0.015,
    min_position_weight: float = 0.0,
    low_volatility_threshold: float = 0.01,
    high_volatility_threshold: float = 0.03,
    min_volatility_multiplier: float = 0.35,
    max_volatility_multiplier: float = 1.25,
    max_leverage: float = 1.0,
) -> PositionSizingDecision:
    base_target_weight = float(base_target_weight)
    confidence = max(0.0, min(float(confidence), 1.0))
    max_position_weight = max(float(max_position_weight), 0.0)
    abs_base_target = abs(base_target_weight)
    volatility = abs(float(rolling_volatility))
    annualized_volatility = volatility * math.sqrt(TRADING_DAYS_PER_YEAR)
    volatility_regime = classify_volatility_regime(
        volatility,
        low_volatility_threshold,
        high_volatility_threshold,
    )

    if abs_base_target == 0.0 or confidence == 0.0 or max_position_weight == 0.0:
        return PositionSizingDecision(
            base_target_weight=base_target_weight,
            target_weight=0.0,
            rolling_volatility=volatility,
            annualized_volatility=annualized_volatility,
            volatility_regime=volatility_regime,
            volatility_multiplier=0.0,
            confidence_multiplier=0.0,
            leverage_factor=0.0,
            max_leverage=float(max_leverage),
            sizing_reason="no_active_signal",
        )

    safe_volatility = max(volatility, 1e-6)
    volatility_multiplier = target_daily_volatility / safe_volatility
    volatility_multiplier = max(min_volatility_multiplier, min(volatility_multiplier, max_volatility_multiplier))
    confidence_multiplier = 0.5 + 0.5 * confidence

    sized_weight = abs_base_target * volatility_multiplier * confidence_multiplier
    sized_weight = min(sized_weight, max_position_weight)
    if sized_weight > 0.0 and min_position_weight > 0.0:
        sized_weight = max(sized_weight, min_position_weight)

    direction = 1.0 if base_target_weight >= 0.0 else -1.0
    target_weight = direction * sized_weight
    leverage_factor = min(float(max_leverage), sized_weight / max(abs_base_target, 1e-9))

    if volatility_regime == "high_volatility":
        reason = "reduced_for_high_volatility"
    elif volatility_regime == "low_volatility" and volatility_multiplier > 1.0:
        reason = "expanded_for_low_volatility"
    else:
        reason = "normal_volatility_sizing"

    return PositionSizingDecision(
        base_target_weight=base_target_weight,
        target_weight=target_weight,
        rolling_volatility=volatility,
        annualized_volatility=annualized_volatility,
        volatility_regime=volatility_regime,
        volatility_multiplier=volatility_multiplier,
        confidence_multiplier=confidence_multiplier,
        leverage_factor=leverage_factor,
        max_leverage=float(max_leverage),
        sizing_reason=reason,
    )
