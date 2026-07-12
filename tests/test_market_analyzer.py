from analyzer import build_market_analysis_decision, compute_signal_quality_score


def _regime(confidence=0.6, risk_regime="risk_neutral"):
    return {"confidence": confidence, "risk_regime": risk_regime}


def _gating(decision_source="baseline_and_experts"):
    return {"decision_source": decision_source}


def test_trade_lock_forces_reduce_risk():
    decision = build_market_analysis_decision(
        signal_name="buy", confidence=0.8, probability_up=0.7, target_weight=0.15,
        regime=_regime(), gating=_gating(),
        trading_eligible=True, trade_lock_active=True, trade_lock_reason="total_drawdown_limit_breached",
    )
    assert decision.action == "reduce_risk"
    assert decision.target_weight == 0.0
    assert "total_drawdown_limit_breached" in decision.reasons


def test_risk_off_regime_overrides_directional_signal():
    decision = build_market_analysis_decision(
        signal_name="sell", confidence=0.9, probability_up=0.2, target_weight=-0.15,
        regime=_regime(confidence=0.8, risk_regime="risk_off"), gating=_gating(),
        trading_eligible=True, trade_lock_active=False,
    )
    assert decision.action == "reduce_risk"
    assert decision.signal == "hold"


def test_short_signal_trades_when_eligible_and_confident():
    # Phase 3 of the 5/10 -> 9/10 roadmap: "short" (portfolio-book-only,
    # see portfolio/book_construction.py) must reach "trade" the same way
    # "buy"/"sell" already do - it is not silently excluded from the
    # trading tier.
    decision = build_market_analysis_decision(
        signal_name="short", confidence=0.5, probability_up=0.3, target_weight=-0.12,
        regime=_regime(), gating=_gating(),
        trading_eligible=True, trade_lock_active=False, min_confidence_to_trade=0.12,
    )
    assert decision.action == "trade"
    assert decision.target_weight == -0.12


def test_short_signal_overridden_by_risk_off_regime():
    decision = build_market_analysis_decision(
        signal_name="short", confidence=0.9, probability_up=0.2, target_weight=-0.15,
        regime=_regime(confidence=0.8, risk_regime="risk_off"), gating=_gating(),
        trading_eligible=True, trade_lock_active=False,
    )
    assert decision.action == "reduce_risk"
    assert decision.signal == "hold"


def test_short_signal_overridden_by_trade_lock():
    decision = build_market_analysis_decision(
        signal_name="short", confidence=0.8, probability_up=0.2, target_weight=-0.15,
        regime=_regime(), gating=_gating(),
        trading_eligible=True, trade_lock_active=True, trade_lock_reason="total_drawdown_limit_breached",
    )
    assert decision.action == "reduce_risk"
    assert decision.target_weight == 0.0


def test_short_signal_downgraded_by_liquidity_block():
    decision = build_market_analysis_decision(
        signal_name="short", confidence=0.8, probability_up=0.2, target_weight=-0.15,
        regime=_regime(), gating=_gating(),
        trading_eligible=True, trade_lock_active=False,
        liquidity={"recommended_action": "block"},
    )
    assert decision.action == "simulate"
    assert decision.signal == "short"
    assert decision.target_weight == 0.0


def test_baseline_fallback_with_low_regime_confidence_flags_retrain_candidate():
    decision = build_market_analysis_decision(
        signal_name="buy", confidence=0.5, probability_up=0.6, target_weight=0.1,
        regime=_regime(confidence=0.10), gating=_gating(decision_source="baseline_fallback"),
        trading_eligible=True, trade_lock_active=False,
    )
    assert decision.action == "retrain_candidate"


def test_baseline_fallback_with_healthy_regime_confidence_does_not_flag_retrain():
    decision = build_market_analysis_decision(
        signal_name="buy", confidence=0.5, probability_up=0.6, target_weight=0.1,
        regime=_regime(confidence=0.9), gating=_gating(decision_source="baseline_fallback"),
        trading_eligible=True, trade_lock_active=False,
    )
    assert decision.action != "retrain_candidate"


def test_trading_eligible_directional_signal_above_confidence_trades():
    decision = build_market_analysis_decision(
        signal_name="buy", confidence=0.5, probability_up=0.7, target_weight=0.12,
        regime=_regime(), gating=_gating(),
        trading_eligible=True, trade_lock_active=False, min_confidence_to_trade=0.12,
    )
    assert decision.action == "trade"
    assert decision.target_weight == 0.12


def test_observation_only_asset_with_directional_signal_simulates():
    decision = build_market_analysis_decision(
        signal_name="buy", confidence=0.5, probability_up=0.7, target_weight=0.12,
        regime=_regime(confidence=0.6), gating=_gating(),
        trading_eligible=False, trade_lock_active=False,
    )
    assert decision.action == "simulate"
    assert decision.target_weight == 0.0


def test_trading_eligible_low_confidence_simulates_instead_of_trading():
    decision = build_market_analysis_decision(
        signal_name="buy", confidence=0.05, probability_up=0.55, target_weight=0.05,
        regime=_regime(confidence=0.6), gating=_gating(),
        trading_eligible=True, trade_lock_active=False, min_confidence_to_trade=0.12,
    )
    assert decision.action == "simulate"


def test_no_directional_signal_observes():
    decision = build_market_analysis_decision(
        signal_name="hold", confidence=0.0, probability_up=0.5, target_weight=0.0,
        regime=_regime(), gating=_gating(),
        trading_eligible=True, trade_lock_active=False,
    )
    assert decision.action == "observe"


def test_low_regime_confidence_with_directional_signal_observes_not_simulates():
    decision = build_market_analysis_decision(
        signal_name="buy", confidence=0.5, probability_up=0.7, target_weight=0.12,
        regime=_regime(confidence=0.10, risk_regime="risk_neutral"), gating=_gating(decision_source="experts_only"),
        trading_eligible=False, trade_lock_active=False, low_regime_confidence_threshold=0.35,
    )
    assert decision.action == "observe"


def test_topology_absent_degrades_gracefully():
    decision = build_market_analysis_decision(
        signal_name="buy", confidence=0.5, probability_up=0.7, target_weight=0.12,
        regime=_regime(), gating=_gating(),
        trading_eligible=True, trade_lock_active=False, topology=None,
    )
    assert decision.topology_considered is False
    assert "topology_absent_v2_11_pending" in decision.reasons


def test_topology_present_is_recorded_but_does_not_block_trade_yet():
    decision = build_market_analysis_decision(
        signal_name="buy", confidence=0.5, probability_up=0.7, target_weight=0.12,
        regime=_regime(), gating=_gating(),
        trading_eligible=True, trade_lock_active=False, topology={"state": "clustered"},
    )
    assert decision.topology_considered is True
    assert decision.action == "trade"


def test_priority_tiebreak_trade_lock_beats_retrain_candidate_conditions():
    decision = build_market_analysis_decision(
        signal_name="buy", confidence=0.5, probability_up=0.6, target_weight=0.1,
        regime=_regime(confidence=0.05), gating=_gating(decision_source="baseline_fallback"),
        trading_eligible=True, trade_lock_active=True, trade_lock_reason="daily_drawdown_limit_breached",
    )
    assert decision.action == "reduce_risk"


def test_priority_tiebreak_risk_off_beats_retrain_candidate_conditions():
    decision = build_market_analysis_decision(
        signal_name="sell", confidence=0.5, probability_up=0.3, target_weight=-0.1,
        regime=_regime(confidence=0.05, risk_regime="risk_off"), gating=_gating(decision_source="baseline_fallback"),
        trading_eligible=True, trade_lock_active=False,
    )
    assert decision.action == "reduce_risk"


def test_topology_elevated_forces_reduce_risk():
    decision = build_market_analysis_decision(
        signal_name="buy", confidence=0.8, probability_up=0.7, target_weight=0.15,
        regime=_regime(), gating=_gating(),
        trading_eligible=True, trade_lock_active=False,
        topology={"state": "ready", "topology_risk": "elevated"},
    )
    assert decision.action == "reduce_risk"
    assert "topology_elevated_volatility_pressure_overrides_directional_signal" in decision.reasons


def test_topology_isolated_downgrades_trade_to_simulate():
    decision = build_market_analysis_decision(
        signal_name="buy", confidence=0.5, probability_up=0.7, target_weight=0.12,
        regime=_regime(confidence=0.6), gating=_gating(),
        trading_eligible=True, trade_lock_active=False, min_confidence_to_trade=0.12,
        topology={"state": "ready", "topology_risk": "isolated"},
    )
    assert decision.action == "simulate"
    assert decision.target_weight == 0.0
    assert "topology_isolated_asset_lacks_peer_confirmation_simulate_instead" in decision.reasons


def test_topology_normal_does_not_change_trade_outcome():
    decision = build_market_analysis_decision(
        signal_name="buy", confidence=0.5, probability_up=0.7, target_weight=0.12,
        regime=_regime(), gating=_gating(),
        trading_eligible=True, trade_lock_active=False, min_confidence_to_trade=0.12,
        topology={"state": "ready", "topology_risk": "normal"},
    )
    assert decision.action == "trade"
    assert decision.target_weight == 0.12


def test_priority_tiebreak_topology_elevated_beats_retrain_candidate_conditions():
    decision = build_market_analysis_decision(
        signal_name="buy", confidence=0.5, probability_up=0.6, target_weight=0.1,
        regime=_regime(confidence=0.05), gating=_gating(decision_source="baseline_fallback"),
        trading_eligible=True, trade_lock_active=False,
        topology={"state": "ready", "topology_risk": "elevated"},
    )
    assert decision.action == "reduce_risk"


# --- V2-12 liquidity tiers ---

def test_liquidity_blocked_downgrades_to_simulate():
    decision = build_market_analysis_decision(
        signal_name="buy", confidence=0.5, probability_up=0.7, target_weight=0.12,
        regime=_regime(), gating=_gating(),
        trading_eligible=True, trade_lock_active=False, min_confidence_to_trade=0.12,
        topology={"topology_risk": "normal"},
        liquidity={"recommended_action": "block"},
    )
    assert decision.action == "simulate"
    assert decision.liquidity_considered is True
    assert "liquidity_blocked_insufficient_volume_simulate_instead" in decision.reasons


def test_liquidity_thin_downgrades_to_simulate():
    decision = build_market_analysis_decision(
        signal_name="buy", confidence=0.5, probability_up=0.7, target_weight=0.12,
        regime=_regime(), gating=_gating(),
        trading_eligible=True, trade_lock_active=False, min_confidence_to_trade=0.12,
        topology={"topology_risk": "normal"},
        liquidity={"recommended_action": "simulate_instead"},
    )
    assert decision.action == "simulate"
    assert "liquidity_thin_market_simulate_instead" in decision.reasons


def test_liquidity_allow_does_not_change_trade_outcome():
    decision = build_market_analysis_decision(
        signal_name="buy", confidence=0.5, probability_up=0.7, target_weight=0.12,
        regime=_regime(), gating=_gating(),
        trading_eligible=True, trade_lock_active=False, min_confidence_to_trade=0.12,
        topology={"topology_risk": "normal"},
        liquidity={"recommended_action": "allow"},
    )
    assert decision.action == "trade"
    assert decision.target_weight == 0.12


def test_liquidity_absent_degrades_gracefully():
    decision = build_market_analysis_decision(
        signal_name="buy", confidence=0.5, probability_up=0.7, target_weight=0.12,
        regime=_regime(), gating=_gating(),
        trading_eligible=True, trade_lock_active=False, min_confidence_to_trade=0.12,
        liquidity=None,
    )
    assert decision.liquidity_considered is False
    assert decision.action == "trade"


# --- compute_signal_quality_score() pure-function tests ---


def test_signal_quality_score_always_bounded_01():
    score, _ = compute_signal_quality_score(
        confidence=5.0, regime_confidence=-3.0, topology={"correlation_strength": 10.0}, liquidity={"participation_rate": -2.0}
    )
    assert 0.0 <= score <= 1.0


def test_signal_quality_score_increases_monotonically_with_confidence():
    low, _ = compute_signal_quality_score(0.1, 0.5, {"topology_risk": "normal", "correlation_strength": 0.5}, {"participation_rate": 0.2})
    high, _ = compute_signal_quality_score(0.9, 0.5, {"topology_risk": "normal", "correlation_strength": 0.5}, {"participation_rate": 0.2})
    assert high > low


def test_signal_quality_score_penalizes_isolated_and_elevated_topology():
    normal, _ = compute_signal_quality_score(0.5, 0.5, {"topology_risk": "normal", "correlation_strength": 0.8}, {})
    isolated, _ = compute_signal_quality_score(0.5, 0.5, {"topology_risk": "isolated", "correlation_strength": 0.8}, {})
    elevated, _ = compute_signal_quality_score(0.5, 0.5, {"topology_risk": "elevated", "correlation_strength": 0.8}, {})
    assert isolated < normal
    assert elevated < normal
    assert isolated < elevated


def test_signal_quality_score_decreases_with_higher_participation_rate():
    thin, _ = compute_signal_quality_score(0.5, 0.5, {}, {"participation_rate": 0.05})
    thick, _ = compute_signal_quality_score(0.5, 0.5, {}, {"participation_rate": 0.9})
    assert thick < thin


def test_signal_quality_score_empty_topology_falls_back_to_regime_component():
    score, breakdown = compute_signal_quality_score(0.5, 0.7, {}, {})
    assert breakdown["topology_component"] == breakdown["regime_component"] == 0.7


def test_signal_quality_score_empty_liquidity_defaults_to_full_liquidity_component():
    _, breakdown = compute_signal_quality_score(0.5, 0.5, {}, {})
    assert breakdown["liquidity_component"] == 1.0


def test_signal_quality_score_breakdown_includes_weights():
    _, breakdown = compute_signal_quality_score(0.5, 0.5, {}, {})
    assert set(breakdown["weights"].keys()) == {"confidence", "regime", "topology", "liquidity"}
    assert sum(breakdown["weights"].values()) == 1.0


# --- signal_quality_score is always populated on the decision itself ---


def test_decision_always_carries_signal_quality_score_even_when_flag_is_off():
    decision = build_market_analysis_decision(
        signal_name="buy", confidence=0.5, probability_up=0.7, target_weight=0.12,
        regime=_regime(), gating=_gating(),
        trading_eligible=True, trade_lock_active=False,
    )
    assert 0.0 <= decision.signal_quality_score <= 1.0
    assert "weights" in decision.signal_quality_breakdown


# --- use_composite_signal_score: additive, off by default, byte-identical
# routing until explicitly enabled ---


def test_composite_score_flag_off_by_default_uses_raw_confidence():
    kwargs = dict(
        signal_name="buy", confidence=0.5, probability_up=0.7, target_weight=0.12,
        regime=_regime(confidence=0.5), gating=_gating(),
        trading_eligible=True, trade_lock_active=False, min_confidence_to_trade=0.4,
        topology={"topology_risk": "normal", "correlation_strength": 0.0},
        liquidity={"recommended_action": "allow", "participation_rate": 1.0},
    )
    without_flag = build_market_analysis_decision(**kwargs)
    with_flag_explicitly_false = build_market_analysis_decision(**kwargs, use_composite_signal_score=False)

    assert without_flag.action == "trade"  # raw confidence 0.5 >= 0.4
    assert without_flag.action == with_flag_explicitly_false.action == "trade"


def test_composite_score_enabled_can_downgrade_trade_to_simulate():
    # Raw confidence alone clears the threshold, but weak topology/liquidity
    # support drags the composite score below it - only the flag-enabled
    # run should downgrade trade -> simulate.
    kwargs = dict(
        signal_name="buy", confidence=0.5, probability_up=0.7, target_weight=0.12,
        regime=_regime(confidence=0.5), gating=_gating(),
        trading_eligible=True, trade_lock_active=False, min_confidence_to_trade=0.4,
        topology={"topology_risk": "normal", "correlation_strength": 0.0},
        liquidity={"recommended_action": "allow", "participation_rate": 1.0},
    )
    off = build_market_analysis_decision(**kwargs, use_composite_signal_score=False)
    on = build_market_analysis_decision(**kwargs, use_composite_signal_score=True)

    assert off.action == "trade"
    assert on.action == "simulate"
    assert on.signal_quality_score < 0.4 <= off.confidence


def test_composite_score_enabled_can_upgrade_simulate_to_trade():
    # Raw confidence alone misses the threshold, but strong regime/topology/
    # liquidity support lifts the composite score above it - only the
    # flag-enabled run should upgrade simulate -> trade.
    kwargs = dict(
        signal_name="buy", confidence=0.2, probability_up=0.6, target_weight=0.1,
        regime=_regime(confidence=1.0), gating=_gating(),
        trading_eligible=True, trade_lock_active=False, min_confidence_to_trade=0.3,
        topology={"topology_risk": "normal", "correlation_strength": 1.0},
        liquidity={"recommended_action": "allow", "participation_rate": 0.0},
    )
    off = build_market_analysis_decision(**kwargs, use_composite_signal_score=False)
    on = build_market_analysis_decision(**kwargs, use_composite_signal_score=True)

    assert off.action == "simulate"
    assert on.action == "trade"
    assert on.signal_quality_score >= 0.3 > off.confidence
