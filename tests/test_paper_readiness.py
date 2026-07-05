from execution import (
    evaluate_broker_config,
    evaluate_live_broker_config,
    evaluate_live_risk_posture,
    evaluate_observation_readiness,
    evaluate_paper_broker_config,
)


def _confirmed_paper_config(**overrides) -> dict:
    config = {
        "brokerage": "lean_paper_brokerage",
        "live_data_provider_configured": True,
        "manual_review_confirmed": True,
    }
    config.update(overrides)
    return config


def test_evaluate_paper_broker_config_passes_when_all_confirmed():
    allowed, reason = evaluate_paper_broker_config(_confirmed_paper_config())

    assert allowed is True
    assert reason == "paper_broker_config_confirmed"


def test_evaluate_paper_broker_config_blocks_on_missing_brokerage():
    allowed, reason = evaluate_paper_broker_config(_confirmed_paper_config(brokerage=""))

    assert allowed is False
    assert reason == "paper_broker_config_missing_brokerage"


def test_evaluate_paper_broker_config_blocks_on_missing_data_provider():
    allowed, reason = evaluate_paper_broker_config(_confirmed_paper_config(live_data_provider_configured=False))

    assert allowed is False
    assert reason == "paper_broker_config_missing_live_data_provider"


def test_evaluate_paper_broker_config_blocks_on_missing_manual_review():
    allowed, reason = evaluate_paper_broker_config(_confirmed_paper_config(manual_review_confirmed=False))

    assert allowed is False
    assert reason == "paper_broker_config_missing_manual_review"


def test_evaluate_paper_broker_config_defaults_to_blocked_on_empty_config():
    allowed, reason = evaluate_paper_broker_config({})

    assert allowed is False
    assert reason == "paper_broker_config_missing_brokerage"


def _safe_risk_config(**overrides) -> dict:
    config = {
        "max_daily_drawdown_pct": 0.03,
        "max_total_drawdown_pct": 0.12,
        "liquidate_on_risk_breach": True,
    }
    config.update(overrides)
    return config


def _live_config(**overrides) -> dict:
    config = {
        "max_allowed_daily_drawdown_pct": 0.05,
        "max_allowed_total_drawdown_pct": 0.15,
    }
    config.update(overrides)
    return config


def test_evaluate_live_risk_posture_passes_within_ceilings():
    allowed, reason = evaluate_live_risk_posture(_safe_risk_config(), _live_config())

    assert allowed is True
    assert reason == "live_broker_config_confirmed"


def test_evaluate_live_risk_posture_blocks_when_daily_ceiling_exceeded():
    allowed, reason = evaluate_live_risk_posture(
        _safe_risk_config(max_daily_drawdown_pct=0.10), _live_config()
    )

    assert allowed is False
    assert reason == "live_broker_config_risk_posture_unsafe"


def test_evaluate_live_risk_posture_blocks_when_total_ceiling_exceeded():
    allowed, reason = evaluate_live_risk_posture(
        _safe_risk_config(max_total_drawdown_pct=0.30), _live_config()
    )

    assert allowed is False
    assert reason == "live_broker_config_risk_posture_unsafe"


def test_evaluate_live_risk_posture_blocks_when_liquidate_on_breach_disabled():
    allowed, reason = evaluate_live_risk_posture(
        _safe_risk_config(liquidate_on_risk_breach=False), _live_config()
    )

    assert allowed is False
    assert reason == "live_broker_config_risk_posture_unsafe"


def test_evaluate_live_broker_config_requires_paper_corridor_ready():
    allowed, reason = evaluate_live_broker_config(
        paper_trading_config={},
        live_credentials_present=True,
    )

    assert allowed is False
    assert reason == "live_broker_config_paper_corridor_not_ready"


def test_evaluate_live_broker_config_requires_credentials():
    allowed, reason = evaluate_live_broker_config(
        paper_trading_config=_confirmed_paper_config(),
        live_credentials_present=False,
    )

    assert allowed is False
    assert reason == "live_broker_config_missing_credentials"


def test_evaluate_live_broker_config_passes_with_everything_confirmed():
    allowed, reason = evaluate_live_broker_config(
        paper_trading_config=_confirmed_paper_config(),
        live_credentials_present=True,
    )

    assert allowed is True
    assert reason == "live_broker_config_confirmed"


def test_evaluate_live_broker_config_blocks_on_unsafe_risk_posture_when_supplied():
    allowed, reason = evaluate_live_broker_config(
        paper_trading_config=_confirmed_paper_config(),
        live_credentials_present=True,
        risk_config=_safe_risk_config(max_daily_drawdown_pct=0.99),
        live_config=_live_config(),
    )

    assert allowed is False
    assert reason == "live_broker_config_risk_posture_unsafe"


def test_evaluate_broker_config_dispatches_to_paper_for_non_live_modes():
    for mode in ("backtest", "observation", "paper", "banana"):
        allowed, reason = evaluate_broker_config(mode, _confirmed_paper_config(), live_credentials_present=False)
        assert allowed is True
        assert reason == "paper_broker_config_confirmed"


def test_evaluate_broker_config_dispatches_to_live_for_live_mode():
    allowed, reason = evaluate_broker_config(
        "live", _confirmed_paper_config(), live_credentials_present=False
    )

    assert allowed is False
    assert reason == "live_broker_config_missing_credentials"


def _observation_summary(**overrides) -> dict:
    summary = {
        "count_observations": 1000,
        "simulated_sharpe": 0.5,
        "simulated_max_drawdown": -0.05,
        "rejected_by_reason": {"reason_a": 5, "reason_b": 5},
    }
    summary.update(overrides)
    return summary


def _readiness_thresholds(**overrides) -> dict:
    thresholds = {
        "min_observations": 500,
        "min_simulated_sharpe": 0.3,
        "max_simulated_drawdown_floor": -0.15,
        "max_single_rejection_reason_share": 0.5,
    }
    thresholds.update(overrides)
    return thresholds


def test_evaluate_observation_readiness_passes_all_checks():
    result = evaluate_observation_readiness(_observation_summary(), _readiness_thresholds())

    assert result["ready"] is True
    assert result["blocking_reasons"] == []
    assert all(check["pass"] for check in result["checks"].values())


def test_evaluate_observation_readiness_fails_on_insufficient_observation_count():
    result = evaluate_observation_readiness(_observation_summary(count_observations=10), _readiness_thresholds())

    assert result["ready"] is False
    assert "observation_count" in result["blocking_reasons"]


def test_evaluate_observation_readiness_fails_on_low_sharpe():
    result = evaluate_observation_readiness(_observation_summary(simulated_sharpe=0.05), _readiness_thresholds())

    assert result["ready"] is False
    assert "simulated_sharpe" in result["blocking_reasons"]


def test_evaluate_observation_readiness_fails_on_excessive_drawdown():
    result = evaluate_observation_readiness(
        _observation_summary(simulated_max_drawdown=-0.40), _readiness_thresholds()
    )

    assert result["ready"] is False
    assert "simulated_max_drawdown" in result["blocking_reasons"]


def test_evaluate_observation_readiness_fails_on_dominant_rejection_reason():
    result = evaluate_observation_readiness(
        _observation_summary(rejected_by_reason={"liquidity_blocked": 90, "other": 10}),
        _readiness_thresholds(),
    )

    assert result["ready"] is False
    assert "dominant_rejection_reason" in result["blocking_reasons"]


def test_evaluate_observation_readiness_handles_no_rejections():
    result = evaluate_observation_readiness(_observation_summary(rejected_by_reason={}), _readiness_thresholds())

    assert result["checks"]["dominant_rejection_reason"]["pass"] is True
    assert result["checks"]["dominant_rejection_reason"]["value"] == 0.0
