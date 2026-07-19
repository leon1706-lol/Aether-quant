"""Tests for audit.redis_queue — the audit-event builder + fire-and-forget
publisher (development/Problems.md #42). Mirrors
tests/test_experience_queue.py's conventions.
"""

import pytest

from audit.redis_queue import (
    CREDENTIAL_LOAD,
    ORDER_PLACEMENT,
    AuditQueue,
    build_audit_event,
)


def test_build_audit_event_has_expected_shape():
    event = build_audit_event(ORDER_PLACEMENT, {"symbol": "AAPL", "signal": "buy"})

    assert event["event_type"] == "order_placement"
    assert event["actor"] == "system"
    assert event["payload"] == {"symbol": "AAPL", "signal": "buy"}
    assert "event_id" in event
    assert "created_at" in event


def test_build_audit_event_custom_actor():
    event = build_audit_event(CREDENTIAL_LOAD, {"filled_fields": ["ib-account"]}, actor="cli")
    assert event["actor"] == "cli"


def test_build_audit_event_rejects_unknown_event_type():
    with pytest.raises(ValueError, match="Unknown audit event_type"):
        build_audit_event("something_else", {})


def test_build_audit_event_never_leaks_secret_values_by_convention():
    # Regression guard for the exact pattern credential-load call sites must
    # follow: field NAMES only, never values (execution/lean_config_render.py's
    # own convention). Nothing here can enforce this at the payload level (the
    # caller decides the payload), but this test documents and pins the
    # expected shape a credential_load event should use.
    event = build_audit_event(CREDENTIAL_LOAD, {"filled_fields": ["ib-account", "ib-password"]})
    payload_str = str(event["payload"])
    assert "hunter2" not in payload_str  # sanity: no accidental secret string


def test_audit_queue_disabled_is_always_a_noop():
    queue = AuditQueue(enabled=False)
    assert queue.push({"event_type": "order_placement"}) is False


def test_audit_queue_push_success():
    class _FakeClient:
        def __init__(self):
            self.pushed = []

        def xadd(self, stream, fields, maxlen=None, approximate=True):
            self.pushed.append((stream, fields))

    client = _FakeClient()
    queue = AuditQueue(stream_name="aether:audit", _client=client)

    result = queue.push({"event_type": "order_placement", "payload": {}})

    assert result is True
    assert len(client.pushed) == 1
    assert client.pushed[0][0] == "aether:audit"


def test_audit_queue_push_failure_never_raises():
    class _FailingClient:
        def xadd(self, *args, **kwargs):
            raise ConnectionError("boom")

    queue = AuditQueue(_client=_FailingClient())

    result = queue.push({"event_type": "order_placement"})

    assert result is False


def test_audit_queue_with_no_client_is_noop():
    queue = AuditQueue(enabled=True, _client=None)
    queue._client = None  # simulate connection failure at construction time
    assert queue.push({"event_type": "order_placement"}) is False
