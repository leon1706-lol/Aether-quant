"""Tests for notifications.telegram_worker — V2-19.

Conventions: no test classes, module-level helpers, _pg_conn/_telegram_client
constructor injection mirroring performance/trigger_worker.py's test style.
"""

import json
from unittest.mock import MagicMock

from notifications.telegram_worker import TelegramWorker

_CONFIG = {"enabled": True, "min_severity_for_trigger_alert": "warning", "session_summary_enabled": True}

_TRIGGER_COLUMNS = (
    "trigger_id",
    "created_at",
    "trigger_type",
    "severity",
    "mode",
    "scope",
    "metric_value",
    "threshold",
    "message",
    "recommended_action",
    "retrain_candidate",
)


def _sample_trigger(**overrides) -> dict:
    defaults = {
        "trigger_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "created_at": "2026-07-02T12:00:00+00:00",
        "trigger_type": "drawdown_trigger",
        "severity": "critical",
        "mode": "observation",
        "scope": "portfolio",
        "metric_value": -0.15,
        "threshold": -0.10,
        "message": "simulated drawdown reached -15.00%.",
        "recommended_action": "reduce_exposure",
        "retrain_candidate": True,
    }
    defaults.update(overrides)
    return defaults


def _sample_session_summary(**overrides) -> dict:
    defaults = {
        "event_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "event_type": "session_summary",
        "created_at": "2026-07-02T00:00:00Z",
        "mode": "observation",
        "session_date": "2026-07-01",
        "session_start_equity": 100_000.0,
        "session_end_equity": 101_000.0,
        "session_return": 0.01,
        "observation_summary": {"count_observations": 10},
    }
    defaults.update(overrides)
    return defaults


class _FakeTelegramClient:
    def __init__(self, should_succeed=True):
        self.sent: list[str] = []
        self.should_succeed = should_succeed

    def send_message(self, text: str) -> bool:
        self.sent.append(text)
        return self.should_succeed


def _make_conn_mock(*, watermark_by_channel=None, triggers=None, session_summaries=None):
    """Routes fetchone()/fetchall() by inspecting the last execute() call's
    SQL text (and, for the shared watermark table, its params — both
    channels reuse the same table/SQL, differentiated only by the
    "channel" parameter)."""
    watermark_by_channel = watermark_by_channel or {}
    triggers = triggers or []
    session_summaries = session_summaries or []

    conn_mock = MagicMock()
    cur_mock = MagicMock()
    conn_mock.cursor.return_value.__enter__.return_value = cur_mock
    conn_mock.cursor.return_value.__exit__.return_value = False

    state = {"last_sql": "", "last_params": None}

    def _execute(sql, params=None):
        state["last_sql"] = sql
        state["last_params"] = params

    def _fetchone():
        sql = state["last_sql"]
        params = state["last_params"] or {}
        if "telegram_alert_watermark" in sql:
            channel = params.get("channel")
            ts = watermark_by_channel.get(channel)
            return (ts,) if ts is not None else None
        return None

    def _fetchall():
        sql = state["last_sql"]
        if "FROM performance_triggers" in sql:
            return [tuple(trigger.get(col) for col in _TRIGGER_COLUMNS) for trigger in triggers]
        if "FROM experience_events" in sql:
            return [(json.dumps(event),) for event in session_summaries]
        return []

    cur_mock.execute.side_effect = _execute
    cur_mock.fetchone.side_effect = _fetchone
    cur_mock.fetchall.side_effect = _fetchall
    return conn_mock, cur_mock


def test_run_once_no_ops_when_disabled():
    conn_mock, _ = _make_conn_mock()
    client = _FakeTelegramClient()
    worker = TelegramWorker(config={"enabled": False}, _pg_conn=conn_mock, _telegram_client=client)

    result = worker.run_once()

    assert result == {"trigger_alerts_sent": 0, "session_summary_alerts_sent": 0}
    assert client.sent == []


def test_run_once_sends_only_triggers_at_or_above_min_severity():
    triggers = [
        _sample_trigger(trigger_id="1", severity="info", created_at="2026-07-02T12:00:00+00:00"),
        _sample_trigger(trigger_id="2", severity="critical", created_at="2026-07-02T12:01:00+00:00"),
    ]
    conn_mock, cur_mock = _make_conn_mock(triggers=triggers, session_summaries=[])
    client = _FakeTelegramClient()
    worker = TelegramWorker(config=_CONFIG, _pg_conn=conn_mock, _telegram_client=client)

    result = worker.run_once()

    assert result["trigger_alerts_sent"] == 1
    assert len(client.sent) == 1
    assert "drawdown_trigger" in client.sent[0]

    watermark_calls = [
        call for call in cur_mock.execute.call_args_list
        if "telegram_alert_watermark" in call.args[0] and "INSERT" in call.args[0]
    ]
    assert watermark_calls
    assert watermark_calls[-1].args[1]["ts"] == triggers[-1]["created_at"]
    assert watermark_calls[-1].args[1]["channel"] == "triggers"


def test_run_once_sends_session_summary_alerts():
    summary = _sample_session_summary()
    conn_mock, cur_mock = _make_conn_mock(triggers=[], session_summaries=[summary])
    client = _FakeTelegramClient()
    worker = TelegramWorker(config=_CONFIG, _pg_conn=conn_mock, _telegram_client=client)

    result = worker.run_once()

    assert result["session_summary_alerts_sent"] == 1
    assert any("2026-07-01" in text for text in client.sent)


def test_run_once_skips_session_summaries_when_disabled_in_config():
    summary = _sample_session_summary()
    conn_mock, _ = _make_conn_mock(triggers=[], session_summaries=[summary])
    client = _FakeTelegramClient()
    config = dict(_CONFIG, session_summary_enabled=False)
    worker = TelegramWorker(config=config, _pg_conn=conn_mock, _telegram_client=client)

    result = worker.run_once()

    assert result["session_summary_alerts_sent"] == 0
    assert client.sent == []


def test_watermark_advances_even_when_send_fails():
    triggers = [_sample_trigger()]
    conn_mock, cur_mock = _make_conn_mock(triggers=triggers, session_summaries=[])
    client = _FakeTelegramClient(should_succeed=False)
    worker = TelegramWorker(config=_CONFIG, _pg_conn=conn_mock, _telegram_client=client)

    result = worker.run_once()

    assert result["trigger_alerts_sent"] == 0
    watermark_calls = [
        call for call in cur_mock.execute.call_args_list
        if "telegram_alert_watermark" in call.args[0] and "INSERT" in call.args[0]
    ]
    assert watermark_calls, "watermark must advance even when every send fails"


def test_run_once_returns_zero_when_no_new_rows():
    conn_mock, _ = _make_conn_mock(triggers=[], session_summaries=[])
    client = _FakeTelegramClient()
    worker = TelegramWorker(config=_CONFIG, _pg_conn=conn_mock, _telegram_client=client)

    result = worker.run_once()

    assert result == {"trigger_alerts_sent": 0, "session_summary_alerts_sent": 0}
