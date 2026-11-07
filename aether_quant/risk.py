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
from risk.asset_class_router import (
    asset_listed_on_venue,
    book_candidate_trading_eligible,
    load_venue_listing_dates,
    resolve_asset_class_enabled,
    route_multi_leg_option_sizing,
    route_position_sizing,
    should_liquidate_disabled_asset_class_position,
)
from risk.forex_risk import ForexSizingDecision, build_forex_position_sizing, cap_forex_target_to_book_weight, load_forex_pair_specs
from risk.futures_risk import FuturesSizingDecision, build_futures_position_sizing, build_live_contract_spec, load_futures_contract_specs, resolve_futures_margin_source, rollover_due
from risk.rl_sizing import build_rl_sizing_state, load_rl_sizing_model, resolve_rl_shadow_guard, rl_excess_return, rl_shadow_guard_allows, rl_sizing_multiplier

__all__ = [
    "ForexSizingDecision",
    "FuturesSizingDecision",
    "KillSwitchDecision",
    "PositionSizingDecision",
    "assess_drawdown_lock",
    "asset_listed_on_venue",
    "book_candidate_trading_eligible",
    "build_dynamic_position_sizing",
    "build_forex_position_sizing",
    "build_futures_position_sizing",
    "build_live_contract_spec",
    "build_rl_sizing_state",
    "cap_forex_target_to_book_weight",
    "cap_target_weight",
    "classify_volatility_regime",
    "compute_incremental_order_quantity",
    "cost_sizing_multiplier",
    "evaluate_kill_switch",
    "load_forex_pair_specs",
    "load_futures_contract_specs",
    "load_rl_sizing_model",
    "load_venue_listing_dates",
    "projected_signed_quantity",
    "rank_sizing_multiplier",
    "resolve_asset_class_enabled",
    "resolve_futures_margin_source",
    "resolve_rl_shadow_guard",
    "rl_excess_return",
    "rl_shadow_guard_allows",
    "rl_sizing_multiplier",
    "rollover_due",
    "route_multi_leg_option_sizing",
    "route_position_sizing",
    "should_liquidate_disabled_asset_class_position",
    "topology_sizing_multiplier",
]
