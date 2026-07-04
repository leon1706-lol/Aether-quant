"""PostgreSQL I/O layer for Telegram alerting (V2-19).

Mirrors performance/postgres_triggers.py's design: embedded DDL (no
Alembic, no migration files), ensure_schema() idempotent at startup. This
module does NOT reimplement trigger fetching — notifications/telegram_worker.py
imports fetch_triggers_since() directly from performance.postgres_triggers,
since that table is already the durable system of record for triggers.
This module only owns: the watermark table shared by both alert channels,
and a defensive read of experience_events (owned by
experience/postgres_worker.py) for session_summary events.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema DDL — embedded constant, no migration files
# ---------------------------------------------------------------------------

_CREATE_WATERMARK_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS telegram_alert_watermark (
    channel         VARCHAR(30) PRIMARY KEY,
    last_created_at TIMESTAMPTZ
);
"""


def ensure_schema(conn) -> None:
    """Create telegram_alert_watermark if missing. Idempotent."""
    with conn.cursor() as cur:
        cur.execute(_CREATE_WATERMARK_TABLE_SQL)
    conn.commit()
    logger.info("ensure_schema: telegram_alert_watermark ready.")


# ---------------------------------------------------------------------------
# Watermark bookkeeping — one row per channel ("triggers", "session_summary")
# ---------------------------------------------------------------------------


def get_watermark(conn, channel: str) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_created_at FROM telegram_alert_watermark WHERE channel = %(channel)s;",
            {"channel": channel},
        )
        row = cur.fetchone()
    return row[0] if row else None


def set_watermark(conn, channel: str, last_created_at) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO telegram_alert_watermark (channel, last_created_at) VALUES (%(channel)s, %(ts)s) "
            "ON CONFLICT (channel) DO UPDATE SET last_created_at = EXCLUDED.last_created_at;",
            {"channel": channel, "ts": last_created_at},
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Reading experience_events (owned by experience/postgres_worker.py)
# ---------------------------------------------------------------------------


def fetch_session_summaries_since(conn, since: datetime | None, limit: int = 500) -> list[dict]:
    """Fetch session_summary experience events newer than `since`, oldest first.

    Never raises — experience_events may be unavailable in a
    telegram-worker-only deployment (experience/postgres_worker.py owns that
    table's schema, not this module), mirroring
    performance/postgres_triggers.py::fetch_last_retraining_at()'s
    defensiveness for cross-package reads.
    """
    if since is None:
        since = datetime.fromtimestamp(0, tz=timezone.utc)

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM experience_events "
                "WHERE payload->>'event_type' = 'session_summary' AND created_at > %(since)s "
                "ORDER BY created_at ASC LIMIT %(limit)s;",
                {"since": since, "limit": limit},
            )
            rows = cur.fetchall()
        return [json.loads(row[0]) if isinstance(row[0], str) else row[0] for row in rows]
    except Exception:
        logger.debug("fetch_session_summaries_since: experience_events unavailable, returning [].")
        try:
            conn.rollback()
        except Exception:
            pass
        return []
