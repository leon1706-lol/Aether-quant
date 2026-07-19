"""Redis Stream publisher for the audit log (development/Problems.md #42).

Mirrors experience/redis_queue.py exactly - same fire-and-forget, never-raises
publish contract, so audit logging can be called from main.py's hot per-bar
order-placement path (and from execution/'s credential-load/live-mode-transition
call sites) without ever risking a real trade or a live process on a Postgres
round-trip. All Redis failures are caught and logged; nothing downstream of
this queue is ever blocking.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# The three event categories development/Problems.md #42 named as needing a
# tamper-evident trail before real capital. Kept as a closed set (not
# free-form strings) so a typo at a call site fails loudly in tests rather
# than silently creating a new, unqueryable event_type.
ORDER_PLACEMENT = "order_placement"
CREDENTIAL_LOAD = "credential_load"
LIVE_MODE_TRANSITION = "live_mode_transition"
EVENT_TYPES = (ORDER_PLACEMENT, CREDENTIAL_LOAD, LIVE_MODE_TRANSITION)


def build_audit_event(event_type: str, payload: dict, actor: str = "system") -> dict[str, Any]:
    """Construct a standardised audit event dict. Pure - no I/O.

    `payload` should never contain a raw secret value - callers logging a
    credential-load event pass field NAMES that were populated (see
    execution/lean_config_render.py's own "never the values" convention),
    never the credential itself. `actor` defaults to "system" (an automated
    call site, e.g. main.py's order placement) - execution/'s CLI-driven
    call sites (aq render-lean-config) pass "cli" instead."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown audit event_type: {event_type!r} (expected one of {EVENT_TYPES})")
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "created_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "actor": actor,
        "payload": payload,
    }


class AuditQueue:
    """Fire-and-forget Redis Stream publisher for audit events.

    Identical shape/contract to experience.redis_queue.ExperienceQueue -
    all failures (connection errors, XADD errors, missing package) are
    caught and logged at WARNING level. push() never raises.

    Parameters
    ----------
    enabled     : kill switch - if False, push() is always a no-op
    redis_url   : connection URL; overridden by AETHER_REDIS_URL env var
    stream_name : Redis key for XADD (default: "aether:audit")
    maxlen      : approximate cap on stream length (MAXLEN ~)
    _client     : pre-built Redis client for test injection
    """

    def __init__(
        self,
        enabled: bool = True,
        redis_url: str = "redis://localhost:6380/0",
        stream_name: str = "aether:audit",
        maxlen: int = 500_000,
        _client=None,
    ) -> None:
        self.enabled = enabled
        self.stream_name = stream_name
        self.maxlen = maxlen
        self._client = None

        if not enabled:
            return

        if _client is not None:
            self._client = _client
            return

        url = os.environ.get("AETHER_REDIS_URL", redis_url) or "redis://localhost:6380/0"
        try:
            import redis as redis_lib  # deferred — not always installed in Lean environments

            client = redis_lib.from_url(url, socket_connect_timeout=2, socket_timeout=2)
            client.ping()
            self._client = client
            logger.info(
                "AuditQueue connected to %s (stream=%s, maxlen=%d)",
                url,
                stream_name,
                maxlen,
            )
        except Exception as exc:
            logger.warning(
                "AuditQueue: Redis unavailable at %s — audit events will be skipped. (%s)",
                url,
                exc,
            )

    def push(self, event: dict) -> bool:
        """Publish one event dict to the Redis Stream. Returns True on
        success, False on any failure. Never raises."""
        if not self.enabled or self._client is None:
            return False
        try:
            self._client.xadd(
                self.stream_name,
                {"payload": json.dumps(event)},
                maxlen=self.maxlen,
                approximate=True,
            )
            return True
        except Exception as exc:
            logger.warning("AuditQueue.push failed: %s", exc)
            return False
