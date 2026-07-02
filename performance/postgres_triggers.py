"""PostgreSQL I/O layer for performance triggers (V2-16).

Mirrors experience/postgres_worker.py's design: embedded DDL (no Alembic,
no migration files), ensure_schema() idempotent at startup, ON CONFLICT DO
NOTHING for safe idempotent re-delivery. Separate from performance/triggers.py
so the pure evaluation logic stays importable with zero DB dependency.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema DDL — embedded constants, no migration files
# ---------------------------------------------------------------------------

_CREATE_TRIGGERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS performance_triggers (
    id                  BIGSERIAL PRIMARY KEY,
    trigger_id          UUID        UNIQUE NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trigger_type        VARCHAR(40) NOT NULL,
    severity            VARCHAR(10) NOT NULL,
    mode                VARCHAR(20) NOT NULL,
    scope               VARCHAR(100) NOT NULL,
    metric_value        DOUBLE PRECISION,
    threshold           DOUBLE PRECISION,
    message             TEXT NOT NULL,
    recommended_action  VARCHAR(40) NOT NULL,
    retrain_candidate   BOOLEAN     NOT NULL DEFAULT FALSE,
    details             JSONB       NOT NULL DEFAULT '{}'::jsonb
);
"""

_CREATE_TRIGGERS_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS ix_trig_created_at        ON performance_triggers (created_at);",
    "CREATE INDEX IF NOT EXISTS ix_trig_type              ON performance_triggers (trigger_type);",
    "CREATE INDEX IF NOT EXISTS ix_trig_severity           ON performance_triggers (severity);",
    "CREATE INDEX IF NOT EXISTS ix_trig_retrain_candidate  ON performance_triggers (retrain_candidate);",
    "CREATE INDEX IF NOT EXISTS ix_trig_scope              ON performance_triggers (scope);",
    "CREATE INDEX IF NOT EXISTS ix_trig_details            ON performance_triggers USING GIN (details);",
]

_CREATE_WATERMARK_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS performance_trigger_watermark (
    id              INT PRIMARY KEY DEFAULT 1,
    last_created_at TIMESTAMPTZ
);
"""

_INSERT_TRIGGER_SQL = """
INSERT INTO performance_triggers
    (trigger_id, created_at, trigger_type, severity, mode, scope,
     metric_value, threshold, message, recommended_action, retrain_candidate, details)
VALUES
    (%(trigger_id)s, %(created_at)s, %(trigger_type)s, %(severity)s, %(mode)s, %(scope)s,
     %(metric_value)s, %(threshold)s, %(message)s, %(recommended_action)s,
     %(retrain_candidate)s, %(details)s)
ON CONFLICT (trigger_id) DO NOTHING;
"""

_SUPPRESSION_CHECK_SQL = """
SELECT 1 FROM performance_triggers
WHERE trigger_type = %(trigger_type)s AND scope = %(scope)s
  AND created_at > NOW() - (%(suppression_minutes)s || ' minutes')::interval
LIMIT 1;
"""

# ---------------------------------------------------------------------------
# Pure transformation — testable without any I/O
# ---------------------------------------------------------------------------


def trigger_to_row(trigger: dict) -> dict[str, Any]:
    """Extract scalar columns + serialised trigger dict for _INSERT_TRIGGER_SQL."""
    return {
        "trigger_id": trigger["trigger_id"],
        "created_at": trigger["created_at"],
        "trigger_type": trigger["trigger_type"],
        "severity": trigger["severity"],
        "mode": trigger["mode"],
        "scope": trigger["scope"],
        "metric_value": trigger.get("metric_value"),
        "threshold": trigger.get("threshold"),
        "message": trigger["message"],
        "recommended_action": trigger["recommended_action"],
        "retrain_candidate": trigger["retrain_candidate"],
        "details": json.dumps(trigger),
    }


# ---------------------------------------------------------------------------
# Schema helper
# ---------------------------------------------------------------------------


def ensure_schema(conn) -> None:
    """Create performance_triggers/watermark tables and indexes if missing.

    Idempotent — safe to call on every worker startup.
    """
    with conn.cursor() as cur:
        cur.execute(_CREATE_TRIGGERS_TABLE_SQL)
        for idx_sql in _CREATE_TRIGGERS_INDEXES_SQL:
            cur.execute(idx_sql)
        cur.execute(_CREATE_WATERMARK_TABLE_SQL)
    conn.commit()
    logger.info("ensure_schema: performance_triggers ready.")


# ---------------------------------------------------------------------------
# Reading experience_events
# ---------------------------------------------------------------------------


def fetch_events_since(conn, since: datetime | None, limit: int = 10_000) -> list[dict]:
    """Fetch experience_events payloads newer than `since`, oldest first.

    `since=None` pulls from the epoch (first-ever run). psycopg3 decodes
    JSONB columns to plain Python dicts by default; the json.loads fallback
    guards against a str being returned by an older/differently-configured
    driver.
    """
    if since is None:
        since = datetime.fromtimestamp(0, tz=timezone.utc)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT payload FROM experience_events WHERE created_at > %(since)s "
            "ORDER BY created_at ASC LIMIT %(limit)s;",
            {"since": since, "limit": limit},
        )
        rows = cur.fetchall()

    return [json.loads(row[0]) if isinstance(row[0], str) else row[0] for row in rows]


# ---------------------------------------------------------------------------
# Watermark bookkeeping
# ---------------------------------------------------------------------------


def get_watermark(conn) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute("SELECT last_created_at FROM performance_trigger_watermark WHERE id = 1;")
        row = cur.fetchone()
    return row[0] if row else None


def set_watermark(conn, last_created_at: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO performance_trigger_watermark (id, last_created_at) VALUES (1, %(ts)s) "
            "ON CONFLICT (id) DO UPDATE SET last_created_at = EXCLUDED.last_created_at;",
            {"ts": last_created_at},
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Writing trigger dicts — suppression-window dedup + insert
# ---------------------------------------------------------------------------


def _is_suppressed(conn, trigger: dict, suppression_minutes: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            _SUPPRESSION_CHECK_SQL,
            {
                "trigger_type": trigger["trigger_type"],
                "scope": trigger["scope"],
                "suppression_minutes": suppression_minutes,
            },
        )
        return cur.fetchone() is not None


def insert_triggers(conn, triggers: list[dict], suppression_minutes: int = 60) -> int:
    """Insert new trigger rows, skipping any within an active suppression window.

    Row-by-row (not executemany) since each insert needs its own suppression
    check — trigger volume per poll cycle is small enough that this is fine,
    unlike experience_events' high-volume batch insert.
    """
    inserted = 0
    for trigger in triggers:
        if _is_suppressed(conn, trigger, suppression_minutes):
            continue
        with conn.cursor() as cur:
            cur.execute(_INSERT_TRIGGER_SQL, trigger_to_row(trigger))
        conn.commit()
        inserted += 1
    return inserted


def fetch_latest_trigger(conn) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT trigger_id, created_at, trigger_type, severity, mode, scope, "
            "metric_value, threshold, message, recommended_action, retrain_candidate "
            "FROM performance_triggers ORDER BY created_at DESC LIMIT 1;"
        )
        row = cur.fetchone()

    if row is None:
        return None

    columns = (
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
    return dict(zip(columns, row))
