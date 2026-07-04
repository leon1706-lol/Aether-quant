"""Tests for performance.triggers — V2-16.

Conventions: no test classes, module-level helpers, plain list[dict] fixtures
(same shape whether sourced from Redis/in-memory logs or Postgres JSONB rows).
"""

from performance.triggers import (
    SEVERITIES,
    TRIGGER_TYPES,
    cluster_drift_trigger,
    confidence_decay_trigger,
    drawdown_trigger,
    evaluate_all_triggers,
    executed_trade_count_trigger,
    liquidity_warning_trigger,
    model_topology_disagreement_trigger,
    observation_count_trigger,
    regime_shift_trigger,
    risk_lock_trigger,
    sharpe_degradation_trigger,
    sustained_drawdown_trigger,
    topology_regime_mismatch_trigger,
    topology_uncertainty_trigger,
    trigger_frequency_spike,
    win_rate_trigger,
)

_DEFAULT_CONFIG = {
    "enabled": True,
    "observation_interval": 100,
    "trade_count_interval": 100,
    "max_drawdown_threshold": -0.10,
    "sustained_drawdown_days": 2,
    "min_sharpe": 0.3,
    "min_win_rate": 0.45,
    "max_liquidity_rejection_rate": 0.25,
    "regime_shift_sensitivity": 0.6,
    "confidence_decay_ratio_threshold": 0.5,
    "confidence_instability_std_threshold": 0.25,
    "max_consecutive_locked_events": 20,
    "rolling_window": 100,
    "suppression_minutes": 60,
}


def _sample_event(**overrides) -> dict:
    defaults = {
        "event_id": "00000000-0000-0000-0000-000000000001",
        "mode": "observation",
        "symbol": "AAPL R735QTJ8XC9X",
        "ticker": "AAPL",
        "signal": "buy",
        "action": "trade",
        "execution_note": "entered_long",
        "probability_up": 0.61,
        "confidence": 0.5,
        "target_weight": 0.12,
        "regime": {"primary_regime": "uptrend_low_vol"},
        "liquidity": {"recommended_action": "allow"},
        "market_analysis": {"action": "trade", "reasons": []},
        "portfolio": {
            "total_value": 100_000.0,
            "cash": 50_000.0,
            "current_drawdown": 0.0,
            "simulated": True,
            "trade_lock_active": False,
        },
    }
    defaults.update(overrides)
    return defaults


def _healthy_events(count: int = 50) -> list[dict]:
    """A fully healthy synthetic event stream: no trigger should fire on this."""
    events = []
    equity = 100_000.0
    for i in range(count):
        equity *= 1.001  # steady, small gains -> good Sharpe, no drawdown
        events.append(
            _sample_event(
                confidence=0.55,
                regime={"primary_regime": "uptrend_low_vol"},
                liquidity={"recommended_action": "allow"},
                portfolio={
                    "total_value": equity,
                    "cash": 50_000.0,
                    "current_drawdown": 0.0,
                    "simulated": True,
                    "trade_lock_active": False,
                    "last_realized_pnl": 10.0 if i % 2 == 0 else None,
                },
            )
        )
    return events


def test_observation_count_trigger_fires_at_exact_multiple_of_interval():
    events = [_sample_event() for _ in range(100)]

    assert len(observation_count_trigger(events, interval=100)) == 1
    assert len(observation_count_trigger(events[:99], interval=100)) == 0
    assert len(observation_count_trigger([_sample_event() for _ in range(150)], interval=100)) == 0


def test_observation_count_trigger_respects_configured_interval():
    assert len(observation_count_trigger([_sample_event() for _ in range(50)], interval=50)) == 1
    assert len(observation_count_trigger([_sample_event() for _ in range(25)], interval=50)) == 0


def test_observation_count_trigger_schema_and_severity():
    triggers = observation_count_trigger([_sample_event() for _ in range(100)], interval=100)

    assert triggers[0]["trigger_type"] == "observation_count_trigger"
    assert triggers[0]["severity"] == "info"
    assert triggers[0]["retrain_candidate"] is False


def test_executed_trade_count_trigger_only_counts_trade_actions():
    trades = [_sample_event(action="trade") for _ in range(100)]
    holds = [_sample_event(action="hold") for _ in range(500)]  # should never count

    assert len(executed_trade_count_trigger(trades, interval=100)) == 1
    assert len(executed_trade_count_trigger(holds, interval=100)) == 0
    assert len(executed_trade_count_trigger(trades + holds, interval=100)) == 1


def test_executed_trade_count_trigger_fires_at_exact_multiple():
    events = [_sample_event(action="trade") for _ in range(100)]

    assert len(executed_trade_count_trigger(events, interval=100)) == 1
    assert len(executed_trade_count_trigger(events[:99], interval=100)) == 0
    assert len(executed_trade_count_trigger([_sample_event(action="trade") for _ in range(150)], interval=100)) == 0


def test_executed_trade_count_trigger_schema_and_severity():
    triggers = executed_trade_count_trigger([_sample_event(action="trade") for _ in range(100)], interval=100)

    assert triggers[0]["trigger_type"] == "executed_trade_count_trigger"
    assert triggers[0]["severity"] == "warning"
    assert triggers[0]["retrain_candidate"] is True


def test_drawdown_trigger_fires_when_simulated_drawdown_breaches_threshold():
    equities = [100_000.0, 110_000.0, 85_000.0]  # ~-22.7% drawdown
    events = [_sample_event(portfolio={"total_value": v, "simulated": True, "current_drawdown": 0.0}) for v in equities]

    triggers = drawdown_trigger(events, max_drawdown_threshold=-0.10)

    assert len(triggers) == 1
    assert triggers[0]["scope"] == "portfolio"
    assert triggers[0]["metric_value"] < -0.10


def test_drawdown_trigger_fires_on_real_portfolio_current_drawdown():
    events = [_sample_event(portfolio={"total_value": 100_000.0, "simulated": True, "current_drawdown": -0.15})]

    triggers = drawdown_trigger(events, max_drawdown_threshold=-0.10)

    assert len(triggers) == 1
    assert triggers[0]["metric_value"] == -0.15


def test_drawdown_trigger_does_not_fire_when_within_threshold():
    events = [_sample_event(portfolio={"total_value": v, "simulated": True, "current_drawdown": -0.01}) for v in (100_000.0, 99_500.0)]

    assert drawdown_trigger(events, max_drawdown_threshold=-0.10) == []


def test_sustained_drawdown_trigger_fires_on_consecutive_bad_days():
    events = [
        _sample_event(created_at="2026-01-01T16:00:00Z", portfolio={"current_drawdown": -0.12}),
        _sample_event(created_at="2026-01-02T16:00:00Z", portfolio={"current_drawdown": -0.15}),
    ]

    triggers = sustained_drawdown_trigger(events, max_drawdown_threshold=-0.10, consecutive_days=2)

    assert len(triggers) == 1
    assert triggers[0]["trigger_type"] == "sustained_drawdown_trigger"
    assert triggers[0]["metric_value"] == -0.15


def test_sustained_drawdown_trigger_does_not_fire_when_only_one_of_two_days_breaches():
    events = [
        _sample_event(created_at="2026-01-01T16:00:00Z", portfolio={"current_drawdown": -0.02}),  # healthy day
        _sample_event(created_at="2026-01-02T16:00:00Z", portfolio={"current_drawdown": -0.15}),  # bad day
    ]

    assert sustained_drawdown_trigger(events, max_drawdown_threshold=-0.10, consecutive_days=2) == []


def test_sustained_drawdown_trigger_does_not_fire_with_fewer_days_than_required():
    events = [_sample_event(created_at="2026-01-01T16:00:00Z", portfolio={"current_drawdown": -0.15})]

    assert sustained_drawdown_trigger(events, max_drawdown_threshold=-0.10, consecutive_days=2) == []


def test_sustained_drawdown_trigger_severity_scales_with_breach_ratio():
    mild = [
        _sample_event(created_at="2026-01-01T16:00:00Z", portfolio={"current_drawdown": -0.11}),
        _sample_event(created_at="2026-01-02T16:00:00Z", portfolio={"current_drawdown": -0.11}),
    ]
    severe = [
        _sample_event(created_at="2026-01-01T16:00:00Z", portfolio={"current_drawdown": -0.30}),
        _sample_event(created_at="2026-01-02T16:00:00Z", portfolio={"current_drawdown": -0.30}),
    ]

    mild_triggers = sustained_drawdown_trigger(mild, max_drawdown_threshold=-0.10, consecutive_days=2)
    severe_triggers = sustained_drawdown_trigger(severe, max_drawdown_threshold=-0.10, consecutive_days=2)

    assert mild_triggers[0]["severity"] == "warning"
    assert severe_triggers[0]["severity"] == "critical"


def test_sharpe_degradation_trigger_fires_below_min_sharpe():
    equities = [100_000.0, 99_000.0, 98_500.0, 97_000.0, 96_000.0]
    events = [_sample_event(portfolio={"total_value": v, "simulated": True}) for v in equities]

    triggers = sharpe_degradation_trigger(events, min_sharpe=0.3, window=100)

    assert len(triggers) == 1
    assert triggers[0]["trigger_type"] == "sharpe_degradation_trigger"


def test_sharpe_degradation_trigger_no_false_fire_on_short_warmup_window():
    events = [_sample_event(portfolio={"total_value": 100_000.0, "simulated": True})]

    assert sharpe_degradation_trigger(events, min_sharpe=0.3) == []


def test_win_rate_trigger_fires_when_win_rate_below_minimum():
    events = [
        _sample_event(portfolio={"total_value": 100_000.0, "simulated": True, "last_realized_pnl": pnl})
        for pnl in (-10.0, -10.0, -10.0, -10.0, 10.0)
    ]

    triggers = win_rate_trigger(events, min_win_rate=0.45, window=100)

    assert len(triggers) == 1
    assert triggers[0]["metric_value"] == 0.2


def test_win_rate_trigger_does_not_fire_with_insufficient_sample_size():
    events = [_sample_event(portfolio={"total_value": 100_000.0, "simulated": True, "last_realized_pnl": -10.0})]

    assert win_rate_trigger(events, min_win_rate=0.45) == []


def test_confidence_decay_trigger_fires_on_mean_drop():
    events = [_sample_event(confidence=0.8) for _ in range(10)] + [_sample_event(confidence=0.3) for _ in range(10)]

    triggers = confidence_decay_trigger(events, window=10, decay_ratio_threshold=0.5)

    assert any("decayed" in t["message"] for t in triggers)


def test_confidence_decay_trigger_fires_on_instability():
    prior = [_sample_event(confidence=0.5) for _ in range(10)]
    recent = [_sample_event(confidence=0.9 if i % 2 == 0 else 0.1) for i in range(10)]
    events = prior + recent

    triggers = confidence_decay_trigger(events, window=10, instability_std_threshold=0.25)

    assert any("unstable" in t["message"] for t in triggers)


def test_confidence_decay_trigger_no_false_fire_on_stable_confidence():
    events = [_sample_event(confidence=0.55) for _ in range(40)]

    assert confidence_decay_trigger(events, window=10) == []


def test_regime_shift_trigger_fires_on_strong_dominant_regime_change():
    prior = [_sample_event(regime={"primary_regime": "uptrend_low_vol"}) for _ in range(20)]
    recent = [_sample_event(regime={"primary_regime": "downtrend_high_vol"}) for _ in range(20)]
    events = prior + recent

    triggers = regime_shift_trigger(events, window=20, sensitivity=0.6)

    assert len(triggers) == 1
    assert triggers[0]["metric_value"] == 1.0


def test_regime_shift_trigger_no_false_fire_on_noise_within_same_regime():
    prior = [_sample_event(regime={"primary_regime": "uptrend_low_vol"}) for _ in range(20)]
    recent = [_sample_event(regime={"primary_regime": "uptrend_low_vol"}) for _ in range(18)] + [
        _sample_event(regime={"primary_regime": "downtrend_high_vol"}) for _ in range(2)
    ]
    events = prior + recent

    assert regime_shift_trigger(events, window=20, sensitivity=0.6) == []


def test_liquidity_warning_trigger_fires_on_high_rejection_rate():
    events = [_sample_event(liquidity={"recommended_action": "block"}, ticker="AAPL") for _ in range(30)] + [
        _sample_event(liquidity={"recommended_action": "allow"}, ticker="AAPL") for _ in range(70)
    ]

    triggers = liquidity_warning_trigger(events, max_liquidity_rejection_rate=0.25, window=100)

    assert any(t["scope"] == "portfolio" for t in triggers)


def test_liquidity_warning_trigger_ignores_simulate_instead_as_non_rejection():
    events = [_sample_event(liquidity={"recommended_action": "simulate_instead"}) for _ in range(100)]

    assert liquidity_warning_trigger(events, max_liquidity_rejection_rate=0.25) == []


def test_liquidity_warning_trigger_surfaces_per_ticker_breakdown():
    events = (
        [_sample_event(liquidity={"recommended_action": "block"}, ticker="LTCUSD") for _ in range(30)]
        + [_sample_event(liquidity={"recommended_action": "allow"}, ticker="AAPL") for _ in range(35)]
        + [_sample_event(liquidity={"recommended_action": "allow"}, ticker="BTCUSD") for _ in range(35)]
    )

    triggers = liquidity_warning_trigger(events, max_liquidity_rejection_rate=0.25, window=100)

    assert any(t["scope"] == "LTCUSD" for t in triggers)


def test_risk_lock_trigger_fires_on_activation_edge():
    events = [
        _sample_event(portfolio={"total_value": 100_000.0, "simulated": True, "trade_lock_active": False}),
        _sample_event(portfolio={"total_value": 100_000.0, "simulated": True, "trade_lock_active": True}),
    ]

    triggers = risk_lock_trigger(events, max_consecutive_locked_events=20)

    assert len(triggers) == 1
    assert triggers[0]["severity"] == "warning"


def test_risk_lock_trigger_fires_on_sustained_lock():
    events = [_sample_event(portfolio={"total_value": 100_000.0, "simulated": True, "trade_lock_active": True}) for _ in range(25)]

    triggers = risk_lock_trigger(events, max_consecutive_locked_events=20)

    assert len(triggers) == 1
    assert triggers[0]["severity"] == "critical"
    assert triggers[0]["retrain_candidate"] is True


def test_risk_lock_trigger_no_false_fire_when_never_locked():
    events = [_sample_event(portfolio={"total_value": 100_000.0, "simulated": True, "trade_lock_active": False}) for _ in range(25)]

    assert risk_lock_trigger(events, max_consecutive_locked_events=20) == []


def test_evaluate_all_triggers_returns_report_schema():
    events = [_sample_event(portfolio={"total_value": 100_000.0, "simulated": True, "trade_lock_active": True}) for _ in range(25)]

    report = evaluate_all_triggers(events, _DEFAULT_CONFIG)

    for key in ("generated_at", "source_event_count", "enabled", "triggers", "summary"):
        assert key in report
    for key in ("active_trigger_count", "severity_distribution", "retrain_candidate", "latest_trigger", "trigger_type_counts"):
        assert key in report["summary"]
    for trigger in report["triggers"]:
        assert trigger["severity"] in SEVERITIES
        assert trigger["trigger_type"] in TRIGGER_TYPES
        assert isinstance(trigger["retrain_candidate"], bool)


def test_evaluate_all_triggers_no_false_triggers_when_all_metrics_healthy():
    events = _healthy_events(50)

    report = evaluate_all_triggers(events, _DEFAULT_CONFIG)

    assert report["triggers"] == []
    assert report["summary"]["retrain_candidate"] is False


def test_evaluate_all_triggers_respects_enabled_false():
    events = [_sample_event(portfolio={"total_value": 100_000.0, "simulated": True, "trade_lock_active": True}) for _ in range(25)]
    config = dict(_DEFAULT_CONFIG, enabled=False)

    report = evaluate_all_triggers(events, config)

    assert report["triggers"] == []
    assert report["enabled"] is False
    assert report["summary"]["active_trigger_count"] == 0


def _topology_event(**topology_overrides) -> dict:
    topology = {
        "topology_uncertainty": 0.1,
        "neighbor_shift_score": 0.1,
        "topology_disagreement": 0.1,
        "regime_label": "bullish",
        "cluster_dominant_regime_label": "bullish",
    }
    topology.update(topology_overrides)
    return _sample_event(topology=topology)


def test_topology_uncertainty_trigger_fires_above_threshold_when_persistent():
    events = [_topology_event(topology_uncertainty=0.8) for _ in range(20)]

    triggers = topology_uncertainty_trigger(events, window=20, max_avg_uncertainty=0.6, min_persistent_fraction=0.6)

    assert len(triggers) == 1
    assert triggers[0]["trigger_type"] == "topology_uncertainty_trigger"
    assert triggers[0]["retrain_candidate"] is True  # warning + model-quality trigger type


def test_topology_uncertainty_trigger_ignores_single_bar_spike():
    events = [_topology_event(topology_uncertainty=0.1) for _ in range(19)] + [_topology_event(topology_uncertainty=0.95)]

    assert topology_uncertainty_trigger(events, window=20, max_avg_uncertainty=0.6, min_persistent_fraction=0.6) == []


def test_topology_uncertainty_trigger_no_false_fire_below_threshold():
    events = [_topology_event(topology_uncertainty=0.2) for _ in range(20)]

    assert topology_uncertainty_trigger(events, window=20, max_avg_uncertainty=0.6) == []


def test_topology_regime_mismatch_trigger_fires_on_sustained_mismatch():
    events = [_topology_event(regime_label="bullish", cluster_dominant_regime_label="bearish") for _ in range(20)]

    triggers = topology_regime_mismatch_trigger(events, window=20, mismatch_threshold=0.5)

    assert len(triggers) == 1
    assert triggers[0]["trigger_type"] == "topology_regime_mismatch_trigger"


def test_topology_regime_mismatch_trigger_no_false_fire_on_agreement():
    events = [_topology_event(regime_label="bullish", cluster_dominant_regime_label="bullish") for _ in range(20)]

    assert topology_regime_mismatch_trigger(events, window=20, mismatch_threshold=0.5) == []


def test_cluster_drift_trigger_fires_on_sustained_drift():
    events = [_topology_event(neighbor_shift_score=0.8) for _ in range(20)]

    triggers = cluster_drift_trigger(events, window=20, drift_threshold=0.5, min_persistent_fraction=0.6)

    assert len(triggers) == 1
    assert triggers[0]["trigger_type"] == "cluster_drift_trigger"


def test_cluster_drift_trigger_does_not_fire_on_small_noise():
    events = [_topology_event(neighbor_shift_score=0.1) for _ in range(19)] + [_topology_event(neighbor_shift_score=0.9)]

    assert cluster_drift_trigger(events, window=20, drift_threshold=0.5, min_persistent_fraction=0.6) == []


def test_model_topology_disagreement_trigger_fires_on_sustained_disagreement():
    events = [_topology_event(topology_disagreement=0.9) for _ in range(20)]

    triggers = model_topology_disagreement_trigger(
        events, window=20, disagreement_threshold=0.5, min_persistent_fraction=0.6
    )

    assert len(triggers) == 1
    assert triggers[0]["trigger_type"] == "model_topology_disagreement_trigger"


def test_model_topology_disagreement_trigger_ignores_noise():
    events = [_topology_event(topology_disagreement=0.1) for _ in range(19)] + [_topology_event(topology_disagreement=0.9)]

    assert (
        model_topology_disagreement_trigger(events, window=20, disagreement_threshold=0.5, min_persistent_fraction=0.6)
        == []
    )


def _trigger_row(**overrides) -> dict:
    defaults = {
        "trigger_id": "id",
        "created_at": "2026-07-02T12:00:00+00:00",
        "trigger_type": "drawdown_trigger",
        "severity": "warning",
        "mode": "observation",
        "scope": "portfolio",
    }
    defaults.update(overrides)
    return defaults


def test_trigger_frequency_spike_fires_on_rate_increase():
    baseline = [_trigger_row(created_at=f"2026-07-01T{hour:02d}:00:00+00:00") for hour in range(24)]
    spike = [_trigger_row(created_at=f"2026-07-02T11:{minute:02d}:00+00:00") for minute in range(0, 60, 5)]
    recent_triggers = baseline + spike

    triggers = trigger_frequency_spike(
        recent_triggers, window_minutes=60, baseline_window_minutes=1440, spike_multiplier=3.0, min_recent_count=3
    )

    assert len(triggers) == 1
    assert triggers[0]["trigger_type"] == "trigger_frequency_spike"


def test_trigger_frequency_spike_ignores_low_absolute_count():
    recent_triggers = [
        _trigger_row(created_at="2026-07-02T11:59:00+00:00"),
        _trigger_row(created_at="2026-07-02T11:58:00+00:00"),
    ]

    assert trigger_frequency_spike(recent_triggers, window_minutes=60, min_recent_count=3) == []


def test_trigger_frequency_spike_empty_input_returns_empty():
    assert trigger_frequency_spike([]) == []


def test_evaluate_all_triggers_backward_compatible_without_recent_triggers():
    events = _healthy_events(50)

    report = evaluate_all_triggers(events, _DEFAULT_CONFIG)

    assert report["triggers"] == []


def test_evaluate_all_triggers_includes_topology_triggers_when_persistent():
    events = [_topology_event(topology_uncertainty=0.9) for _ in range(60)]
    config = dict(
        _DEFAULT_CONFIG,
        rolling_window=60,
        topology_uncertainty_threshold=0.6,
        topology_uncertainty_persistent_fraction=0.6,
    )

    report = evaluate_all_triggers(events, config)

    assert any(trigger["trigger_type"] == "topology_uncertainty_trigger" for trigger in report["triggers"])
    assert "topology_uncertainty_trigger" in report["summary"]["trigger_type_counts"]
