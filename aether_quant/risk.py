"""Risk controls: the kill switch, the bounded sizing multipliers and the exposure / drawdown gates (formally verified
in formal/AetherFormal/{KillSwitch,PositionSizing,RiskControls}.lean)."""

from risk.kill_switch import KillSwitchDecision, evaluate_kill_switch
from risk.position_sizing import (
    PositionSizingDecision,
    build_dynamic_position_sizing,
    classify_volatility_regime,
    cost_sizing_multiplier,
    rank_sizing_multiplier,
    topology_sizing_multiplier,
)
from risk_controls import (
    assess_drawdown_lock,
    cap_target_weight,
    compute_incremental_order_quantity,
    projected_signed_quantity,
)

__all__ = [
    "KillSwitchDecision",
    "PositionSizingDecision",
    "assess_drawdown_lock",
    "build_dynamic_position_sizing",
    "cap_target_weight",
    "classify_volatility_regime",
    "compute_incremental_order_quantity",
    "cost_sizing_multiplier",
    "evaluate_kill_switch",
    "projected_signed_quantity",
    "rank_sizing_multiplier",
    "topology_sizing_multiplier",
]
