"""Tests for performance.trigger_worker — V2-16 / V2-17.5.

Conventions: no test classes, module-level helpers, _pg_conn constructor
injection mirroring PostgresWorker's test style.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from performance.trigger_worker import TriggerWorker
from performance.triggers import evaluate_all_triggers

_CONFIG = {"enabled": True, "observation_interval": 100, "suppression_minutes": 60}


def _sample_event(**overrides) -> dict:
    defaults = {
        "mode": "observation",
        "ticker": "AAPL",
        "signal": "hold",
        "action": "observe",
        "confidence": 0.5,
        "created_at": "2026-07-02T12:00:00+00:00",
        "regime": {"primary_regime": "uptrend_low_vol"},
        "liquidity": {"recommended_action": "allow"},
        "market_analysis": {"action": "observe", "reasons": []},
        "portfolio": {
            "total_value": 100_000.0,
            "current_drawdown": 0.0,
            "simulated": True,
            "trade_lock_active": False,
        },
    }
    defaults.update(overrides)
    return defaults


def _make_conn_mock(*, new_events=None, window_events=None, trigger_rows=None, watermark=None, last_retrain_at=None):
    """Routes fetchone()/fetchall() results by inspecting the SQL text of
    the last execute() call, since run_once() now issues several distinct
    queries per call (watermark lookup, last-retrain lookup, rolling-window
    events, trigger-frequency baseline, per-trigger suppression checks,
    insert, watermark advance) instead of just one fetch."""
    new_events = new_events or []
    window_events = new_events if window_events is None else window_events
    trigger_rows = trigger_rows or []

    conn_mock = MagicMock()
    cur_mock = MagicMock()
    conn_mock.cursor.return_value.__enter__.return_value = cur_mock
    conn_mock.cursor.return_value.__exit__.return_value = False

    state = {"last_sql": ""}

    def _execute(sql, params=None):
        state["last_sql"] = sql

    def _fetchone():
        sql = state["last_sql"]
        if "performance_trigger_watermark" in sql:
            return (watermark,) if watermark is not None else None
        if "retraining_events" in sql:
            return (last_retrain_at,)
        return None  # suppression checks: never suppressed by default

    def _fetchall():
        sql = state["last_sql"]
        if "FROM experience_events" in sql:
            if "ORDER BY created_at DESC" in sql:
                return [(event,) for event in list(reversed(window_events))]
            return [(event,) for event in new_events]
        if "FROM performance_triggers" in sql:
            return [
                (
                    trigger.get("trigger_id"),
                    trigger.get("created_at"),
                    trigger.get("trigger_type"),
                    trigger.get("severity"),
                    trigger.get("mode"),
                    trigger.get("scope"),
                    trigger.get("metric_value"),
                    trigger.get("threshold"),
                    trigger.get("message"),
                    trigger.get("recommended_action"),
                    trigger.get("retrain_candidate"),
                )
                for trigger in trigger_rows
            ]
        return []

    cur_mock.execute.side_effect = _execute
    cur_mock.fetchone.side_effect = _fetchone
    cur_mock.fetchall.side_effect = _fetchall
    return conn_mock, cur_mock


def test_run_once_persists_triggers_and_advances_watermark():
    base = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)
    events = [_sample_event(created_at=(base + timedelta(minutes=i)).isoformat()) for i in range(100)]
    conn_mock, cur_mock = _make_conn_mock(new_events=events, window_events=events)

    worker = TriggerWorker(config=_CONFIG, _pg_conn=conn_mock)
    inserted = worker.run_once()

    assert inserted >= 1  # the 100-count observation trigger fires at minimum
    set_watermark_calls = [
        call for call in cur_mock.execute.call_args_list if "performance_trigger_watermark" in call.args[0]
    ]
    assert len(set_watermark_calls) >= 1
    assert set_watermark_calls[-1].args[1]["ts"] == events[-1]["created_at"]


def test_run_once_returns_zero_when_no_new_events():
    conn_mock, cur_mock = _make_conn_mock(new_events=[], window_events=[])

    worker = TriggerWorker(config=_CONFIG, _pg_conn=conn_mock)
    inserted = worker.run_once()

    assert inserted == 0


def test_run_once_evaluates_rolling_window_not_just_incremental_batch():
    """The V2-16 limitation this phase fixes: a tiny incremental batch
    (just 1 new event since the watermark) must not be all that gets
    evaluated — run_once() should pull the larger durable rolling window
    from Postgres and evaluate against that instead."""
    new_events = [_sample_event(created_at="2026-07-02T12:00:00+00:00")]
    window_events = [_sample_event(created_at=f"2026-07-02T11:{i:02d}:00+00:00") for i in range(59)] + new_events
    conn_mock, cur_mock = _make_conn_mock(new_events=new_events, window_events=window_events)

    worker = TriggerWorker(config=_CONFIG, _pg_conn=conn_mock)
    with patch("performance.trigger_worker.evaluate_all_triggers", wraps=evaluate_all_triggers) as spy:
        worker.run_once()

    called_events = spy.call_args.args[0]
    assert len(called_events) == len(window_events)
    assert len(called_events) > len(new_events)


def test_run_once_uses_since_last_retrain_when_more_recent_than_default_lookback():
    new_events = [_sample_event(created_at="2026-07-02T12:00:00+00:00")]
    last_retrain_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    conn_mock, cur_mock = _make_conn_mock(
        new_events=new_events, window_events=new_events, last_retrain_at=last_retrain_at
    )

    worker = TriggerWorker(config=_CONFIG, _pg_conn=conn_mock)
    worker.run_once()

    recent_events_calls = [
        call
        for call in cur_mock.execute.call_args_list
        if "FROM experience_events" in call.args[0] and "ORDER BY created_at DESC" in call.args[0]
    ]
    assert recent_events_calls, "fetch_recent_events should have been called for the rolling window"
    assert recent_events_calls[-1].args[1]["since"] == last_retrain_at


def test_run_once_passes_recent_triggers_for_frequency_spike_baseline():
    new_events = [_sample_event(created_at="2026-07-02T12:00:00+00:00")]
    trigger_rows = [
        {
            "trigger_id": "id",
            "created_at": "2026-07-02T11:00:00+00:00",
            "trigger_type": "drawdown_trigger",
            "severity": "warning",
            "mode": "observation",
            "scope": "portfolio",
            "metric_value": -0.2,
            "threshold": -0.1,
            "message": "msg",
            "recommended_action": "reduce_exposure",
            "retrain_candidate": True,
        }
    ]
    conn_mock, cur_mock = _make_conn_mock(new_events=new_events, window_events=new_events, trigger_rows=trigger_rows)

    worker = TriggerWorker(config=_CONFIG, _pg_conn=conn_mock)
    with patch("performance.trigger_worker.evaluate_all_triggers", wraps=evaluate_all_triggers) as spy:
        worker.run_once()

    assert spy.call_args.kwargs["recent_triggers"] == trigger_rows
