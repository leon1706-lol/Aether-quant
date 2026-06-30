from analyzer import build_market_analysis_decision


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
