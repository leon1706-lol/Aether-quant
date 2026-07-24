"""Tests for experience.redis_queue — V2-13.

Follows project test conventions: no test classes, direct imports,
no mocking beyond fakeredis injection via _client parameter.
"""

import json
from datetime import date

import fakeredis

from experience import (
    ExperienceQueue,
    build_experience_event,
    build_option_strategy_outcome_event,
    build_session_summary_event,
)


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
    """build_experience_event returns all 19 required schema keys."""
    event = _minimal_event()
    required = {
        "event_id", "event_type", "created_at", "mode", "symbol", "ticker",
        "signal", "action", "execution_note", "probability_up", "confidence",
        "target_weight", "regime", "moe_gating", "topology", "liquidity",
        "market_analysis", "portfolio", "sequence_model",
    }
    assert required.issubset(event.keys())


def test_event_includes_sequence_model_when_provided():
    """sequence_model (Phase 2 causal-TCN prediction) round-trips through
    build_experience_event unchanged, same as every other optional model
    output dict."""
    prediction = {"direction": 0.55, "magnitude": 0.012, "volatility": 0.021}
    event = _minimal_event(sequence_model=prediction)
    assert event["sequence_model"] == prediction


def test_event_sequence_model_defaults_to_none():
    """Every call site that doesn't pass sequence_model (or a bar where
    _run_sequence_model() returned None) must still produce a valid event
    with the key present but null, never a missing key or a crash."""
    event = _minimal_event()
    assert event["sequence_model"] is None


def test_event_includes_resolved_predicted_rank_20d_and_close_price_when_provided():
    """Phase 6 of the 5/10 -> 9/10 roadmap: main.py's already-resolved
    rank_20d value (preferring the sequence model, falling back to
    multitask's) and this bar's close price round-trip through
    build_experience_event unchanged - performance/rank_ic_monitor.py's
    outcome-resolution job self-joins on these."""
    event = _minimal_event(resolved_predicted_rank_20d=0.83, close_price=142.50)
    assert event["resolved_predicted_rank_20d"] == 0.83
    assert event["close_price"] == 142.50


def test_event_resolved_predicted_rank_20d_and_close_price_default_to_none():
    event = _minimal_event()
    assert event["resolved_predicted_rank_20d"] is None
    assert event["close_price"] is None


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


# ---------------------------------------------------------------------------
# build_session_summary_event — V2-19
# ---------------------------------------------------------------------------


def _sample_session_events() -> list[dict]:
    return [
        _minimal_event(
            action="trade",
            portfolio={"total_value": 100_500.0, "simulated": True, "last_realized_pnl": 500.0},
        ),
        _minimal_event(
            action="observe",
            portfolio={"total_value": 101_000.0, "simulated": True, "last_realized_pnl": None},
        ),
    ]


def test_session_summary_event_has_correct_event_type_and_mode():
    event = build_session_summary_event(
        mode="observation",
        session_date=date(2026, 7, 1),
        session_start_equity=100_000.0,
        session_end_equity=101_000.0,
        events=_sample_session_events(),
    )
    assert event["event_type"] == "session_summary"
    assert event["mode"] == "observation"
    assert event["session_date"] == "2026-07-01"


def test_session_summary_event_computes_session_return():
    event = build_session_summary_event(
        mode="observation",
        session_date=date(2026, 7, 1),
        session_start_equity=100_000.0,
        session_end_equity=101_000.0,
        events=[],
    )
    assert event["session_return"] == 0.01


def test_session_summary_event_handles_zero_start_equity_without_dividing_by_zero():
    event = build_session_summary_event(
        mode="observation",
        session_date=date(2026, 7, 1),
        session_start_equity=0.0,
        session_end_equity=0.0,
        events=[],
    )
    assert event["session_return"] == 0.0


def test_session_summary_event_embeds_observation_summary():
    event = build_session_summary_event(
        mode="observation",
        session_date=date(2026, 7, 1),
        session_start_equity=100_000.0,
        session_end_equity=101_000.0,
        events=_sample_session_events(),
    )
    summary = event["observation_summary"]
    assert summary["count_observations"] == 2
    assert summary["action_distribution"]["trade"] == 1
    assert summary["action_distribution"]["observe"] == 1


def test_session_summary_event_is_json_serializable():
    event = build_session_summary_event(
        mode="observation",
        session_date=date(2026, 7, 1),
        session_start_equity=100_000.0,
        session_end_equity=101_000.0,
        events=_sample_session_events(),
    )
    serialised = json.dumps(event)
    assert isinstance(serialised, str)


# ---------------------------------------------------------------------------
# build_option_strategy_outcome_event — V4.7 (development/Problems.md #29's
# own framing), the learned strategy-selector model's data prerequisite.
# ---------------------------------------------------------------------------


def _sample_option_strategy_outcome_kwargs(**overrides) -> dict:
    defaults = dict(
        mode="observation",
        symbol="AAPL R735QTJ8XC9X",
        ticker="AAPL",
        strategy_name="iron_condor",
        realized_pnl=125.50,
        entry_bar=10,
        exit_bar=25,
        contracts=2,
        entry_net_debit_or_credit=-1.20,
        exit_net_debit_or_credit=0.55,
        regime={"risk_score": 0.3},
        moe_gating={},
        topology={"correlation_strength": 0.4},
        liquidity={},
    )
    defaults.update(overrides)
    return defaults


def test_option_strategy_outcome_event_has_correct_event_type_and_fields():
    event = build_option_strategy_outcome_event(**_sample_option_strategy_outcome_kwargs())
    assert event["event_type"] == "option_strategy_outcome"
    assert event["mode"] == "observation"
    assert event["strategy_name"] == "iron_condor"
    assert event["realized_pnl"] == 125.50
    assert event["entry_bar"] == 10
    assert event["exit_bar"] == 25
    assert event["contracts"] == 2
    assert event["regime"] == {"risk_score": 0.3}
    assert event["topology"] == {"correlation_strength": 0.4}


def test_option_strategy_outcome_event_has_required_envelope_fields():
    event = build_option_strategy_outcome_event(**_sample_option_strategy_outcome_kwargs())
    assert "event_id" in event
    assert "created_at" in event


def test_option_strategy_outcome_event_ids_are_unique():
    event_a = build_option_strategy_outcome_event(**_sample_option_strategy_outcome_kwargs())
    event_b = build_option_strategy_outcome_event(**_sample_option_strategy_outcome_kwargs())
    assert event_a["event_id"] != event_b["event_id"]


def test_option_strategy_outcome_event_is_json_serializable():
    event = build_option_strategy_outcome_event(**_sample_option_strategy_outcome_kwargs())
    serialised = json.dumps(event)
    assert isinstance(serialised, str)
