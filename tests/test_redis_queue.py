"""audit/redis_queue.py and experience/redis_queue.py: the pure event builders (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

from audit.redis_queue import build_audit_event
from experience.redis_queue import build_session_summary_event


def test_an_audit_event_carries_its_type_payload_and_actor_and_refuses_an_unknown_type():
    import pytest

    from audit.redis_queue import ORDER_PLACEMENT

    event = build_audit_event(ORDER_PLACEMENT, {"ticker": "SPY"}, actor="cli")
    assert event["event_type"] == ORDER_PLACEMENT and event["payload"] == {"ticker": "SPY"} and event["actor"] == "cli"
    assert build_audit_event(ORDER_PLACEMENT, {})["actor"] == "system"
    with pytest.raises(ValueError, match="Unknown audit event_type"):
        build_audit_event("made_up", {})


def test_a_session_summary_reports_the_session():
    event = build_session_summary_event(mode="paper", session_date="2026-11-14", session_start_equity=100.0, session_end_equity=101.0, events=[])
    assert event["mode"] == "paper"
    assert "2026-11-14" in str(event)
