from risk.position_sizing import (
    build_dynamic_position_sizing,
    classify_volatility_regime,
    topology_sizing_multiplier,
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


# ---------------------------------------------------------------------------
# topology_sizing_multiplier
# ---------------------------------------------------------------------------


def test_topology_multiplier_no_adjustment_when_source_is_none():
    multiplier, reason = topology_sizing_multiplier(None, 0.9, 0.0)
    assert multiplier == 1.0
    assert reason == "topology_absent_or_fallback_no_adjustment"


def test_topology_multiplier_no_adjustment_when_source_is_fallback():
    multiplier, reason = topology_sizing_multiplier("fallback", 0.9, 0.0)
    assert multiplier == 1.0
    assert reason == "topology_absent_or_fallback_no_adjustment"


def test_topology_multiplier_shrinks_size_with_low_confidence_learned_topology():
    multiplier, reason = topology_sizing_multiplier("learned", 0.3, 0.0, min_topology_multiplier=0.5, max_topology_multiplier=1.0)
    assert 0.5 < multiplier < 1.0
    assert reason == "topology_confidence_scaled_sizing"


def test_topology_multiplier_never_exceeds_max():
    multiplier, _ = topology_sizing_multiplier("learned", 1.0, 0.0, min_topology_multiplier=0.5, max_topology_multiplier=1.0)
    assert multiplier == 1.0


def test_topology_multiplier_respects_min_bound():
    multiplier, _ = topology_sizing_multiplier("learned", 1.0, 1.0, min_topology_multiplier=0.5, max_topology_multiplier=1.0)
    assert multiplier == 0.5


def test_dynamic_position_sizing_shrinks_with_low_confidence_learned_topology():
    baseline = build_dynamic_position_sizing(
        base_target_weight=0.20,
        confidence=1.0,
        rolling_volatility=0.015,
        max_position_weight=0.20,
    )
    with_topology = build_dynamic_position_sizing(
        base_target_weight=0.20,
        confidence=1.0,
        rolling_volatility=0.015,
        max_position_weight=0.20,
        topology_source="learned",
        topology_confidence=0.3,
        topology_disagreement=0.0,
    )

    assert with_topology.topology_multiplier < 1.0
    assert with_topology.target_weight < baseline.target_weight
    assert with_topology.topology_sizing_reason == "topology_confidence_scaled_sizing"


def test_dynamic_position_sizing_topology_omitted_matches_no_adjustment():
    baseline = build_dynamic_position_sizing(
        base_target_weight=0.20,
        confidence=1.0,
        rolling_volatility=0.015,
        max_position_weight=0.20,
    )

    assert baseline.topology_multiplier == 1.0
    assert baseline.topology_sizing_reason == "topology_absent_or_fallback_no_adjustment"
