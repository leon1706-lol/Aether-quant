from risk.position_sizing import (
    build_dynamic_position_sizing,
    classify_volatility_regime,
)


def test_classify_volatility_regime():
    assert classify_volatility_regime(0.005, 0.01, 0.03) == "low_volatility"
    assert classify_volatility_regime(0.02, 0.01, 0.03) == "normal_volatility"
    assert classify_volatility_regime(0.04, 0.01, 0.03) == "high_volatility"


def test_dynamic_position_sizing_reduces_high_volatility_weight():
    decision = build_dynamic_position_sizing(
        base_target_weight=0.20,
        confidence=1.0,
        rolling_volatility=0.06,
        max_position_weight=0.20,
        target_daily_volatility=0.015,
        min_volatility_multiplier=0.35,
        max_volatility_multiplier=1.25,
    )

    assert decision.volatility_regime == "high_volatility"
    assert decision.target_weight < decision.base_target_weight
    assert decision.sizing_reason == "reduced_for_high_volatility"


def test_dynamic_position_sizing_expands_low_volatility_but_respects_cap():
    decision = build_dynamic_position_sizing(
        base_target_weight=0.18,
        confidence=1.0,
        rolling_volatility=0.005,
        max_position_weight=0.20,
        target_daily_volatility=0.015,
        min_volatility_multiplier=0.35,
        max_volatility_multiplier=1.25,
    )

    assert decision.volatility_regime == "low_volatility"
    assert decision.target_weight == 0.20
    assert decision.sizing_reason == "expanded_for_low_volatility"


def test_dynamic_position_sizing_returns_zero_without_active_signal():
    decision = build_dynamic_position_sizing(
        base_target_weight=0.0,
        confidence=1.0,
        rolling_volatility=0.01,
        max_position_weight=0.20,
    )

    assert decision.target_weight == 0.0
    assert decision.leverage_factor == 0.0
    assert decision.sizing_reason == "no_active_signal"
