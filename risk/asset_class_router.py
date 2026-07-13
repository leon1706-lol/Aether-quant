"""Single dispatch point routing a symbol's position sizing to the right
asset-class-specific model, while every downstream consumer
(portfolio/book_construction.py, liquidity, analyzer, main.py::_apply_signal())
keeps working against ONE shared PositionSizingDecision shape
(risk/position_sizing.py:13-28) regardless of which asset class produced it.

Design: equity/crypto/bond all resolve via the EXISTING, unchanged
build_dynamic_position_sizing() - bonds get no new sizing formula in this
pass, only better upstream features (features/bond_features.py); a
duration-sensitive ETF is still correctly modeled as a vol-scaled weight on
a liquid, longable-only instrument. future/option resolve via
risk/futures_risk.py / portfolio/options_strategy.py, then get ADAPTED
onto the shared PositionSizingDecision shape by the two functions below.

The adapters can't express everything a futures/options decision carries
(an integer contract_count, a specific option contract) inside
PositionSizingDecision's fixed field set - route_position_sizing() returns
a (PositionSizingDecision, extra) pair, where `extra` carries whatever
asset-class-specific raw decision main.py::_apply_signal() needs to place
the RIGHT kind of order (MarketOrder(symbol, contract_count) for futures,
vs. SetHoldings(symbol, target_weight) for everything else) - `extra` is
empty for equity/crypto/bond, so existing callers that only ever look at
the PositionSizingDecision stay completely unaffected.
"""

from __future__ import annotations

from risk.futures_risk import FuturesSizingDecision, build_futures_position_sizing
from risk.position_sizing import PositionSizingDecision, build_dynamic_position_sizing

try:
    from portfolio.options_strategy import OptionsPositionDecision, build_options_position_sizing
except ImportError:  # pragma: no cover - portfolio package always present in this repo; defensive only
    OptionsPositionDecision = None
    build_options_position_sizing = None

FUTURES_OPTIONS_SENTINEL_VOLATILITY_REGIME = "not_applicable_non_volatility_sizing"


def _futures_decision_to_position_sizing(decision: FuturesSizingDecision) -> PositionSizingDecision:
    """Maps FuturesSizingDecision onto PositionSizingDecision's exact field
    set. volatility fields are 0.0/sentinel-string (futures sizing isn't
    volatility-driven at all - a real 0.0, not a missing value).
    leverage_factor repurposes its existing "how much of the cap did we
    use" semantic as margin_utilization / max_margin_utilization."""
    max_margin_utilization = decision.max_margin_utilization or 1.0
    return PositionSizingDecision(
        base_target_weight=decision.base_target_weight,
        target_weight=decision.target_weight,
        rolling_volatility=0.0,
        annualized_volatility=0.0,
        volatility_regime=FUTURES_OPTIONS_SENTINEL_VOLATILITY_REGIME,
        volatility_multiplier=0.0,
        confidence_multiplier=decision.confidence_multiplier,
        topology_multiplier=1.0,
        leverage_factor=decision.margin_utilization / max_margin_utilization,
        max_leverage=max_margin_utilization,
        sizing_reason=decision.sizing_reason,
        topology_sizing_reason="not_applicable_futures",
        volatility_source="not_applicable",
        rank_multiplier=1.0,
        rank_sizing_reason="not_applicable_futures",
    )


def _options_decision_to_position_sizing(decision, portfolio_value: float, max_vega_budget_pct_of_equity: float) -> PositionSizingDecision:
    """Maps target_delta -> volatility_multiplier's slot (delta IS the
    options-world analogue of "how much of the underlying's move this
    position captures"), and vega_budget_used / max budget ->
    leverage_factor (same "how much of the cap did we use" semantic as the
    futures adapter)."""
    max_budget = max_vega_budget_pct_of_equity or 1.0
    direction = 1.0 if decision.right == "call" else -1.0
    return PositionSizingDecision(
        base_target_weight=direction * decision.target_delta,
        target_weight=direction * (decision.vega_budget_used),
        rolling_volatility=0.0,
        annualized_volatility=0.0,
        volatility_regime=FUTURES_OPTIONS_SENTINEL_VOLATILITY_REGIME,
        volatility_multiplier=decision.actual_delta,
        confidence_multiplier=1.0,
        topology_multiplier=1.0,
        leverage_factor=decision.vega_budget_used / max_budget,
        max_leverage=max_budget,
        sizing_reason=decision.sizing_reason,
        topology_sizing_reason="not_applicable_options",
        volatility_source="not_applicable",
        rank_multiplier=1.0,
        rank_sizing_reason="not_applicable_options",
    )


def _zero_position_sizing(reason: str) -> PositionSizingDecision:
    return PositionSizingDecision(
        base_target_weight=0.0,
        target_weight=0.0,
        rolling_volatility=0.0,
        annualized_volatility=0.0,
        volatility_regime=FUTURES_OPTIONS_SENTINEL_VOLATILITY_REGIME,
        volatility_multiplier=0.0,
        confidence_multiplier=0.0,
        topology_multiplier=1.0,
        leverage_factor=0.0,
        max_leverage=0.0,
        sizing_reason=reason,
        topology_sizing_reason="not_applicable",
        volatility_source="not_applicable",
        rank_multiplier=1.0,
        rank_sizing_reason="not_applicable",
    )


def route_position_sizing(
    asset_class: str,
    signal_name: str,
    confidence: float,
    base_target_weight: float,
    *,
    equity_crypto_kwargs: dict | None = None,
    price: float = 0.0,
    portfolio_value: float = 0.0,
    contract_spec: dict | None = None,
    futures_kwargs: dict | None = None,
    available_chain: list[dict] | None = None,
    options_kwargs: dict | None = None,
) -> tuple[PositionSizingDecision, dict]:
    """Dispatches on asset_class (falls back to "equity" behavior for any
    unrecognized value - the existing, safest, most-tested path). Returns
    (PositionSizingDecision, extra) - extra is {} for equity/crypto/bond,
    {"contract_count": int} for future, {"options_decision": OptionsPositionDecision}
    for option (only when a position was actually sized; {} when the
    asset-class-specific sizer returned no position, e.g. an empty options
    chain because IB is disabled)."""
    if asset_class == "future":
        decision = build_futures_position_sizing(
            base_target_weight=base_target_weight,
            confidence=confidence,
            price=price,
            contract_spec=contract_spec,
            portfolio_value=portfolio_value,
            **(futures_kwargs or {}),
        )
        return _futures_decision_to_position_sizing(decision), {"contract_count": decision.contract_count}

    if asset_class == "option":
        if build_options_position_sizing is None:
            return _zero_position_sizing("options_strategy_module_unavailable"), {}
        decision = build_options_position_sizing(
            signal_direction=signal_name,
            confidence=confidence,
            available_chain=available_chain or [],
            portfolio_value=portfolio_value,
            **(options_kwargs or {}),
        )
        if decision is None:
            return _zero_position_sizing("no_usable_option_contract_or_zero_signal"), {}
        max_vega_budget = (options_kwargs or {}).get("max_vega_budget_pct_of_equity", 0.02)
        return _options_decision_to_position_sizing(decision, portfolio_value, max_vega_budget), {"options_decision": decision}

    # equity / crypto / bond / anything unrecognized: existing, unchanged path.
    decision = build_dynamic_position_sizing(
        base_target_weight=base_target_weight,
        confidence=confidence,
        **(equity_crypto_kwargs or {}),
    )
    return decision, {}
