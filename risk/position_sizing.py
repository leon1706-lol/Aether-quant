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
    topology_multiplier: float
    leverage_factor: float
    max_leverage: float
    sizing_reason: str
    topology_sizing_reason: str

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


def _clamp01(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def topology_sizing_multiplier(
    topology_source: str | None,
    topology_confidence: float | None,
    topology_disagreement: float | None,
    min_topology_multiplier: float = 0.5,
    max_topology_multiplier: float = 1.0,
) -> tuple[float, str]:
    """Bounded, continuous, shrink-only adjustment - never above
    max_topology_multiplier (1.0 by default), i.e. never amplifies size
    beyond what the deterministic-only sizing already computed. Only
    engages when topology_source == "learned" - topology/learned_topology.py
    already gates that label on confidence clearing
    min_confidence_for_learned upstream, so "fallback"/missing/None here is
    always a strict no-op, matching the same "a missing/degraded learned
    model never changes trading behavior" convention already established
    for the topology overlay itself (see analyzer/README.md and
    development/v2_architecture.md's V2-17.5 safety rule: probabilistic
    scoring may only ever produce a bounded, continuous adjustment, never
    a randomized or amplified decision)."""
    if topology_source != "learned" or topology_confidence is None:
        return 1.0, "topology_absent_or_fallback_no_adjustment"

    confidence = _clamp01(topology_confidence)
    disagreement = _clamp01(topology_disagreement) if topology_disagreement is not None else 0.0
    raw = confidence * (1.0 - disagreement)
    multiplier = min_topology_multiplier + (max_topology_multiplier - min_topology_multiplier) * raw
    return multiplier, "topology_confidence_scaled_sizing"


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
    topology_source: str | None = None,
    topology_confidence: float | None = None,
    topology_disagreement: float | None = None,
    min_topology_multiplier: float = 0.5,
    max_topology_multiplier: float = 1.0,
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
    topology_multiplier, topology_sizing_reason = topology_sizing_multiplier(
        topology_source,
        topology_confidence,
        topology_disagreement,
        min_topology_multiplier,
        max_topology_multiplier,
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
            topology_multiplier=topology_multiplier,
            leverage_factor=0.0,
            max_leverage=float(max_leverage),
            sizing_reason="no_active_signal",
            topology_sizing_reason=topology_sizing_reason,
        )

    safe_volatility = max(volatility, 1e-6)
    volatility_multiplier = target_daily_volatility / safe_volatility
    volatility_multiplier = max(min_volatility_multiplier, min(volatility_multiplier, max_volatility_multiplier))
    confidence_multiplier = 0.5 + 0.5 * confidence

    sized_weight = abs_base_target * volatility_multiplier * confidence_multiplier * topology_multiplier
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
        topology_multiplier=topology_multiplier,
        leverage_factor=leverage_factor,
        max_leverage=float(max_leverage),
        sizing_reason=reason,
        topology_sizing_reason=topology_sizing_reason,
    )
