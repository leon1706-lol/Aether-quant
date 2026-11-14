"""The last unreached lines of experience/ and audit/ queues (V6.6.6, #359)."""

from __future__ import annotations

from unittest.mock import MagicMock

import fakeredis

from audit.hash_chain import canonical_timestamp
from audit.redis_queue import AuditQueue
from experience.redis_queue import ExperienceQueue
from experience.simulated_portfolio import SimulatedPortfolioState


def _redis_module(monkeypatch, client):
    import redis

    monkeypatch.setattr(redis, "from_url", lambda url, socket_connect_timeout, socket_timeout: client)


def test_both_queues_connect_from_the_stored_url_and_keep_the_client(monkeypatch):
    for queue_class in (AuditQueue, ExperienceQueue):
        client = fakeredis.FakeRedis()
        _redis_module(monkeypatch, client)
        queue = queue_class(redis_url="redis://localhost:1/0")
        assert queue._client is client


def test_a_push_that_fails_is_reported_not_raised():
    client = MagicMock()
    client.xadd.side_effect = ConnectionError("redis down")
    queue = ExperienceQueue(_client=client)
    assert queue.push({"event_id": "1"}) is False


def test_the_background_thread_delivers_in_order_and_stops_on_its_sentinel():
    client = fakeredis.FakeRedis()
    queue = ExperienceQueue(_client=client, async_enabled=True)
    for number in range(3):
        queue.push({"event_id": str(number)})
    queue._background_queue.join()
    assert [entry[1][b"payload"] for entry in client.xrange(queue.stream_name)][0].startswith(b"{")
    assert len(client.xrange(queue.stream_name)) == 3


def test_a_portfolio_with_no_equity_or_no_peak_reports_no_exposure_or_drawdown():
    state = SimulatedPortfolioState(0.0)
    assert state._exposure() == 0.0 and state._drawdown(-1.0) == 0.0


def test_a_timestamp_that_is_not_a_date_is_written_as_text():
    assert canonical_timestamp(12345) == "12345" and canonical_timestamp("not a date") == "not a date"


def test_the_background_thread_returns_when_it_is_sent_its_shutdown_sentinel():
    import experience.redis_queue as module

    queue = ExperienceQueue(_client=fakeredis.FakeRedis(), async_enabled=True)
    queue._background_queue.put(module._SHUTDOWN_SENTINEL)
    queue._background_thread.join(timeout=5)
    assert not queue._background_thread.is_alive()
