"""Tests for notifications.telegram_alerts — V2-19.

Conventions: no test classes, module-level helpers, no network.
"""

from notifications.telegram_alerts import format_session_summary_alert, format_trigger_alert, should_alert_trigger


def _sample_trigger(**overrides) -> dict:
    defaults = {
        "trigger_id": "11111111-1111-1111-1111-111111111111",
        "created_at": "2026-07-02T12:00:00+00:00",
        "trigger_type": "drawdown_trigger",
        "severity": "critical",
        "mode": "observation",
        "scope": "portfolio",
        "metric_value": -0.15,
        "threshold": -0.10,
        "message": "simulated drawdown reached -15.00% (threshold -10.00%).",
        "recommended_action": "reduce_exposure",
        "retrain_candidate": True,
    }
    defaults.update(overrides)
    return defaults


def _sample_session_summary_event(**overrides) -> dict:
    defaults = {
        "event_id": "22222222-2222-2222-2222-222222222222",
        "event_type": "session_summary",
        "created_at": "2026-07-02T00:00:00Z",
        "mode": "observation",
        "session_date": "2026-07-01",
        "session_start_equity": 100_000.0,
        "session_end_equity": 101_500.0,
        "session_return": 0.015,
        "observation_summary": {
            "count_observations": 42,
            "signal_distribution": {"buy": 10, "sell": 5, "hold": 27},
            "action_distribution": {"observe": 20, "simulate": 15, "trade": 7, "reduce_risk": 0, "retrain_candidate": 0},
            "rejected_by_reason": {},
            "simulated_win_loss": {"wins": 5, "losses": 2, "win_rate": 5 / 7},
            "simulated_sharpe": 1.23,
            "simulated_max_drawdown": -0.04,
        },
    }
    defaults.update(overrides)
    return defaults


def test_should_alert_trigger_gates_by_severity():
    assert should_alert_trigger(_sample_trigger(severity="critical"), min_severity="warning") is True
    assert should_alert_trigger(_sample_trigger(severity="warning"), min_severity="warning") is True
    assert should_alert_trigger(_sample_trigger(severity="info"), min_severity="warning") is False


def test_should_alert_trigger_min_severity_critical_blocks_warning():
    assert should_alert_trigger(_sample_trigger(severity="warning"), min_severity="critical") is False
    assert should_alert_trigger(_sample_trigger(severity="critical"), min_severity="critical") is True


def test_format_trigger_alert_includes_message_scope_and_action():
    text = format_trigger_alert(_sample_trigger())
    assert "drawdown_trigger" in text
    assert "simulated drawdown reached -15.00%" in text
    assert "portfolio" in text
    assert "reduce_exposure" in text


def test_format_session_summary_alert_includes_key_stats():
    text = format_session_summary_alert(_sample_session_summary_event())
    assert "2026-07-01" in text
    assert "100,000.00" in text
    assert "101,500.00" in text
    assert "+1.50%" in text
    assert "42" in text
    assert "1.23" in text
