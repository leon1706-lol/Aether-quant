"""Tests for experience.redis_queue — V2-13.

Follows project test conventions: no test classes, direct imports,
no mocking beyond fakeredis injection via _client parameter.
"""

import json

import fakeredis

from experience import ExperienceQueue, build_experience_event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_event(**overrides) -> dict:
    """Return a fully populated experience event with sensible defaults."""
    defaults = dict(
        mode="backtest",
        symbol="AAPL R735QTJ8XC9X",
        ticker="AAPL",
        signal="buy",
        action="trade",
        execution_note="entered_long",
        probability_up=0.61,
        confidence=0.22,
        target_weight=0.12,
        regime={"trend_regime": "bullish", "confidence": 0.7},
        moe_gating={"final_probability_up": 0.61},
        topology={},
        liquidity={"recommended_action": "allow"},
        market_analysis={"action": "trade", "signal": "buy"},
        portfolio={"total_value": 105000.0, "cash": 50000.0, "current_drawdown": -0.01},
    )
    defaults.update(overrides)
    return build_experience_event(**defaults)


def _fake_queue(stream_name: str = "aether:experience", maxlen: int = 100_000):
    client = fakeredis.FakeRedis()
    queue = ExperienceQueue(enabled=True, stream_name=stream_name, maxlen=maxlen, _client=client)
    return queue, client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_event_contains_required_fields():
    """build_experience_event returns all 18 required schema keys."""
    event = _minimal_event()
    required = {
        "event_id", "event_type", "created_at", "mode", "symbol", "ticker",
        "signal", "action", "execution_note", "probability_up", "confidence",
        "target_weight", "regime", "moe_gating", "topology", "liquidity",
        "market_analysis", "portfolio",
    }
    assert required.issubset(event.keys())


def test_disabled_queue_does_nothing_safely():
    """ExperienceQueue(enabled=False).push() returns False without crashing."""
    queue = ExperienceQueue(enabled=False)
    assert queue.push(_minimal_event()) is False


def test_redis_unavailable_does_not_crash():
    """Non-reachable URL: constructor logs a warning, push returns False."""
    queue = ExperienceQueue(enabled=True, redis_url="redis://127.0.0.1:19999/0")
    assert queue.push(_minimal_event()) is False


def test_event_serialization_is_json_compatible():
    """json.dumps(event) must succeed; None probability_up becomes JSON null."""
    event = _minimal_event(probability_up=None)
    serialised = json.dumps(event)
    assert isinstance(serialised, str)
    roundtripped = json.loads(serialised)
    assert roundtripped["event_type"] == "market_decision"
    assert roundtripped["probability_up"] is None


def test_stream_name_is_configurable():
    """Injected stream name is used for XADD, not the default stream."""
    custom_stream = "custom:stream:test"
    queue, client = _fake_queue(stream_name=custom_stream)
    queue.push(_minimal_event())
    assert len(client.xrange(custom_stream)) == 1
    assert len(client.xrange("aether:experience")) == 0


def test_mode_present_in_all_valid_modes():
    """All four valid modes produce events with the correct mode field."""
    for mode in ("backtest", "observation", "paper", "live"):
        event = _minimal_event(mode=mode)
        assert event["mode"] == mode


def test_push_writes_to_stream():
    """A successful push appends exactly one entry to the Redis Stream."""
    queue, client = _fake_queue()
    result = queue.push(_minimal_event())
    assert result is True
    entries = client.xrange("aether:experience")
    assert len(entries) == 1
    decoded = json.loads(entries[0][1][b"payload"])
    assert decoded["event_type"] == "market_decision"
    assert decoded["ticker"] == "AAPL"
    assert decoded["action"] == "trade"


def test_event_id_is_unique_per_call():
    """Two calls to build_experience_event produce different event_id values."""
    event_a = _minimal_event()
    event_b = _minimal_event()
    assert event_a["event_id"] != event_b["event_id"]
