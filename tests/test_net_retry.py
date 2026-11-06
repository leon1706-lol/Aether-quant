"""data_pipeline/net_retry.py: a failed fetch must never read as a file that doesn't exist."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from data_pipeline.net_retry import NetworkOutage, fetch


def _response(code):
    return SimpleNamespace(status_code=code, ok=200 <= code < 300, content=b"x")


def _sequence(*events):
    items = list(events)

    def get(url, timeout=None, **kwargs):
        event = items.pop(0)
        if isinstance(event, Exception):
            raise event
        return _response(event)

    return get


def test_a_dropped_connection_waits_and_then_succeeds():
    waits = []
    response = fetch("u", get=_sequence(OSError("wlan"), OSError("wlan"), 200), sleep=waits.append)
    assert response.content == b"x" and waits == [5.0, 10.0]


def test_only_the_servers_own_answer_means_absent():
    assert fetch("u", get=_sequence(404), sleep=lambda s: None) is None
    assert fetch("u", get=_sequence(403), absent_codes=(403, 404), sleep=lambda s: None) is None


def test_a_server_error_is_not_an_absence():
    assert fetch("u", get=_sequence(503, 200), sleep=lambda s: None).ok


def test_an_outage_past_the_wait_stops_the_run_rather_than_recording_a_hole():
    with pytest.raises(NetworkOutage):
        fetch("u", get=lambda url, timeout=None: (_ for _ in ()).throw(OSError("down")), max_wait_seconds=30.0, sleep=lambda s: None)


def test_a_403_is_a_failure_where_it_is_not_declared_absent():
    with pytest.raises(NetworkOutage):
        fetch("u", get=lambda url, timeout=None: _response(403), max_wait_seconds=10.0, sleep=lambda s: None)
