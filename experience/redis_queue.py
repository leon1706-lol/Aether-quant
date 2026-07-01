"""Redis Stream publisher for Aether Quant experience events (V2-13).

Publishes one market-decision event per asset per bar to a Redis Stream
(XADD) with a bounded maxlen. All Redis failures are caught and logged;
trading is never blocked.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def build_experience_event(
    *,
    mode: str,
    symbol: str,
    ticker: str,
    signal: str,
    action: str,
    execution_note: str,
    probability_up: float | None,
    confidence: float,
    target_weight: float,
    regime: dict,
    moe_gating: dict,
    topology: dict,
    liquidity: dict,
    market_analysis: dict,
    portfolio: dict,
) -> dict[str, Any]:
    """Construct a standardised experience event dict.

    Pure function — no side effects, no I/O. Directly testable without
    any Redis dependency.
    """
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "market_decision",
        "created_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": mode,
        "symbol": symbol,
        "ticker": ticker,
        "signal": signal,
        "action": action,
        "execution_note": execution_note,
        "probability_up": probability_up,
        "confidence": confidence,
        "target_weight": target_weight,
        "regime": regime,
        "moe_gating": moe_gating,
        "topology": topology,
        "liquidity": liquidity,
        "market_analysis": market_analysis,
        "portfolio": portfolio,
    }


class ExperienceQueue:
    """Fire-and-forget Redis Stream publisher.

    All failures (connection errors, XADD errors, missing package) are
    caught and logged at WARNING level. push() never raises; the trading
    loop is never blocked.

    Parameters
    ----------
    enabled     : kill switch — if False, push() is always a no-op
    redis_url   : connection URL; overridden by AETHER_REDIS_URL env var
    stream_name : Redis key for XADD (default: "aether:experience")
    maxlen      : approximate cap on stream length (MAXLEN ~)
    _client     : pre-built Redis client for test injection
    """

    def __init__(
        self,
        enabled: bool = True,
        redis_url: str = "redis://localhost:6379/0",
        stream_name: str = "aether:experience",
        maxlen: int = 100_000,
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

        url = os.environ.get("AETHER_REDIS_URL", redis_url) or "redis://localhost:6379/0"
        try:
            import redis as redis_lib  # deferred — not always installed in Lean environments

            client = redis_lib.from_url(url, socket_connect_timeout=2, socket_timeout=2)
            client.ping()
            self._client = client
            logger.info(
                "ExperienceQueue connected to %s (stream=%s, maxlen=%d)",
                url,
                stream_name,
                maxlen,
            )
        except Exception as exc:
            logger.warning(
                "ExperienceQueue: Redis unavailable at %s — experience events will be skipped. (%s)",
                url,
                exc,
            )

    def push(self, event: dict) -> bool:
        """Publish one event dict to the Redis Stream.

        Returns True on success, False on any failure.  Never raises.
        """
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
            logger.warning("ExperienceQueue.push failed: %s", exc)
            return False
