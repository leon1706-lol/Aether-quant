"""Tests for performance.trigger_worker — V2-16.

Conventions: no test classes, module-level helpers, _pg_conn constructor
injection mirroring PostgresWorker's test style.
"""

from unittest.mock import MagicMock

from performance.trigger_worker import TriggerWorker

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


def _make_conn_mock():
    conn_mock = MagicMock()
    cur_mock = MagicMock()
    conn_mock.cursor.return_value.__enter__.return_value = cur_mock
    conn_mock.cursor.return_value.__exit__.return_value = False
    return conn_mock, cur_mock


def test_run_once_persists_triggers_and_advances_watermark():
    events = [_sample_event(created_at=f"2026-07-02T12:{i:02d}:00+00:00") for i in range(100)]
    conn_mock, cur_mock = _make_conn_mock()
    # fetchone(): 1st call is get_watermark -> None, subsequent calls are
    # per-trigger suppression checks -> None (not suppressed).
    cur_mock.fetchone.side_effect = [None] + [None] * 5
    cur_mock.fetchall.return_value = [(event,) for event in events]

    worker = TriggerWorker(config=_CONFIG, _pg_conn=conn_mock)
    inserted = worker.run_once()

    assert inserted >= 1  # the 100-count observation trigger fires at minimum
    set_watermark_calls = [
        call for call in cur_mock.execute.call_args_list if "performance_trigger_watermark" in call.args[0]
    ]
    assert len(set_watermark_calls) >= 1
    assert set_watermark_calls[-1].args[1]["ts"] == events[-1]["created_at"]


def test_run_once_returns_zero_when_no_new_events():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchone.return_value = None
    cur_mock.fetchall.return_value = []

    worker = TriggerWorker(config=_CONFIG, _pg_conn=conn_mock)
    inserted = worker.run_once()

    assert inserted == 0
