"""PostgreSQL I/O layer for the retraining job registry and model version
registry (V2-17).

Mirrors performance/postgres_triggers.py's design: embedded DDL (no Alembic,
no migration files), ensure_schema() idempotent at startup, ON CONFLICT DO
NOTHING for safe idempotent re-delivery. Both tables live in one file because
every retraining_events row references a model_versions row and the two are
always read/written together by the orchestrator/worker.

Row-shaping helpers (*_to_row) and fetch helpers stay pure/thin — no
business logic here. UUIDs (retraining_id, model_version_id) are generated
by the caller (retraining/worker.py, retraining/orchestrator.py), not this
module, matching performance/triggers.py's trigger_id convention.
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

_CREATE_MODEL_VERSIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS model_versions (
    id                    BIGSERIAL PRIMARY KEY,
    model_version_id      UUID        UNIQUE NOT NULL,
    status                VARCHAR(20) NOT NULL DEFAULT 'candidate',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    git_commit            VARCHAR(64),
    aether_vault_commit   VARCHAR(64),
    artifact_paths        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    artifact_hashes       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    training_window       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    validation_window     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    backtest_window       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    metrics               JSONB       NOT NULL DEFAULT '{}'::jsonb
);
"""

_CREATE_MODEL_VERSIONS_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS ix_model_versions_status     ON model_versions (status);",
    "CREATE INDEX IF NOT EXISTS ix_model_versions_created_at ON model_versions (created_at);",
    "CREATE INDEX IF NOT EXISTS ix_model_versions_metrics    ON model_versions USING GIN (metrics);",
    # Enforces "exactly one active model" at the DB level.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_model_versions_single_active "
    "ON model_versions ((status)) WHERE status = 'active';",
]

_CREATE_RETRAINING_EVENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS retraining_events (
    id                    BIGSERIAL PRIMARY KEY,
    retraining_id         UUID        UNIQUE NOT NULL,
    source_trigger_id     UUID,
    candidate_version_id  UUID,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status                VARCHAR(20) NOT NULL DEFAULT 'planned',
    reason                TEXT        NOT NULL,
    metrics               JSONB       NOT NULL DEFAULT '{}'::jsonb,
    notes                 JSONB       NOT NULL DEFAULT '[]'::jsonb
);
"""

_CREATE_RETRAINING_EVENTS_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS ix_retraining_events_status        ON retraining_events (status);",
    "CREATE INDEX IF NOT EXISTS ix_retraining_events_created_at    ON retraining_events (created_at);",
    "CREATE INDEX IF NOT EXISTS ix_retraining_events_candidate_ver ON retraining_events (candidate_version_id);",
    "CREATE INDEX IF NOT EXISTS ix_retraining_events_metrics       ON retraining_events USING GIN (metrics);",
]

_INSERT_MODEL_VERSION_SQL = """
INSERT INTO model_versions
    (model_version_id, status, git_commit, aether_vault_commit, artifact_paths,
     artifact_hashes, training_window, validation_window, backtest_window, metrics)
VALUES
    (%(model_version_id)s, %(status)s, %(git_commit)s, %(aether_vault_commit)s, %(artifact_paths)s,
     %(artifact_hashes)s, %(training_window)s, %(validation_window)s, %(backtest_window)s, %(metrics)s)
ON CONFLICT (model_version_id) DO NOTHING;
"""

_INSERT_RETRAINING_EVENT_SQL = """
INSERT INTO retraining_events
    (retraining_id, source_trigger_id, candidate_version_id, status, reason, metrics, notes)
VALUES
    (%(retraining_id)s, %(source_trigger_id)s, %(candidate_version_id)s, %(status)s,
     %(reason)s, %(metrics)s, %(notes)s)
ON CONFLICT (retraining_id) DO NOTHING;
"""

_MODEL_VERSION_COLUMNS = (
    "model_version_id",
    "status",
    "created_at",
    "updated_at",
    "git_commit",
    "aether_vault_commit",
    "artifact_paths",
    "artifact_hashes",
    "training_window",
    "validation_window",
    "backtest_window",
    "metrics",
)

_RETRAINING_EVENT_COLUMNS = (
    "retraining_id",
    "source_trigger_id",
    "candidate_version_id",
    "created_at",
    "updated_at",
    "status",
    "reason",
    "metrics",
    "notes",
)


def _jsonb(value: Any) -> str:
    return json.dumps(value if value is not None else {})


def _row_to_dict(row: tuple, columns: tuple[str, ...]) -> dict:
    return dict(zip(columns, row))


def model_version_to_row(version: dict) -> dict[str, Any]:
    """Extract INSERT params for _INSERT_MODEL_VERSION_SQL from a version dict."""
    return {
        "model_version_id": version["model_version_id"],
        "status": version.get("status", "candidate"),
        "git_commit": version.get("git_commit"),
        "aether_vault_commit": version.get("aether_vault_commit"),
        "artifact_paths": _jsonb(version.get("artifact_paths")),
        "artifact_hashes": _jsonb(version.get("artifact_hashes")),
        "training_window": _jsonb(version.get("training_window")),
        "validation_window": _jsonb(version.get("validation_window")),
        "backtest_window": _jsonb(version.get("backtest_window")),
        "metrics": _jsonb(version.get("metrics")),
    }


def retraining_event_to_row(event: dict) -> dict[str, Any]:
    """Extract INSERT params for _INSERT_RETRAINING_EVENT_SQL from an event dict."""
    return {
        "retraining_id": event["retraining_id"],
        "source_trigger_id": event.get("source_trigger_id"),
        "candidate_version_id": event.get("candidate_version_id"),
        "status": event.get("status", "planned"),
        "reason": event["reason"],
        "metrics": _jsonb(event.get("metrics")),
        "notes": json.dumps(event.get("notes") or []),
    }


# ---------------------------------------------------------------------------
# Schema helper
# ---------------------------------------------------------------------------


def ensure_schema(conn) -> None:
    """Create model_versions/retraining_events tables and indexes if missing.

    Idempotent — safe to call on every worker/orchestrator startup.
    """
    with conn.cursor() as cur:
        cur.execute(_CREATE_MODEL_VERSIONS_TABLE_SQL)
        for idx_sql in _CREATE_MODEL_VERSIONS_INDEXES_SQL:
            cur.execute(idx_sql)
        cur.execute(_CREATE_RETRAINING_EVENTS_TABLE_SQL)
        for idx_sql in _CREATE_RETRAINING_EVENTS_INDEXES_SQL:
            cur.execute(idx_sql)
    conn.commit()
    logger.info("ensure_schema: model_versions/retraining_events ready.")


def count_experience_events(conn) -> int:
    """Total experience_events row count - feeds planning.min_observations_satisfied().

    A plain COUNT(*), not a since-watermark query: "minimum observations
    before retraining starts" is meant as a lifetime floor (enough history
    ever exists to trust a retrain), not a since-last-retrain count.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM experience_events;")
        row = cur.fetchone()
    return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# model_versions
# ---------------------------------------------------------------------------


def insert_model_version(conn, version: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(_INSERT_MODEL_VERSION_SQL, model_version_to_row(version))
    conn.commit()


def update_model_version_status(conn, model_version_id: str, status: str, **fields: Any) -> None:
    """Update status plus any of git_commit/aether_vault_commit/artifact_paths/
    artifact_hashes/training_window/validation_window/backtest_window/metrics."""
    assignments = ["status = %(status)s", "updated_at = NOW()"]
    params: dict[str, Any] = {"model_version_id": model_version_id, "status": status}

    jsonb_fields = (
        "artifact_paths",
        "artifact_hashes",
        "training_window",
        "validation_window",
        "backtest_window",
        "metrics",
    )
    scalar_fields = ("git_commit", "aether_vault_commit")

    for key, value in fields.items():
        if key in jsonb_fields:
            assignments.append(f"{key} = %({key})s")
            params[key] = _jsonb(value)
        elif key in scalar_fields:
            assignments.append(f"{key} = %({key})s")
            params[key] = value

    sql = f"UPDATE model_versions SET {', '.join(assignments)} WHERE model_version_id = %(model_version_id)s;"
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


def fetch_model_version(conn, model_version_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(_MODEL_VERSION_COLUMNS)} FROM model_versions "
            "WHERE model_version_id = %(model_version_id)s;",
            {"model_version_id": model_version_id},
        )
        row = cur.fetchone()
    return _row_to_dict(row, _MODEL_VERSION_COLUMNS) if row else None


def fetch_active_model_version(conn) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(_MODEL_VERSION_COLUMNS)} FROM model_versions "
            "WHERE status = 'active' ORDER BY updated_at DESC LIMIT 1;"
        )
        row = cur.fetchone()
    return _row_to_dict(row, _MODEL_VERSION_COLUMNS) if row else None


def fetch_latest_candidate_version(conn) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(_MODEL_VERSION_COLUMNS)} FROM model_versions "
            "WHERE status = 'candidate' ORDER BY created_at DESC LIMIT 1;"
        )
        row = cur.fetchone()
    return _row_to_dict(row, _MODEL_VERSION_COLUMNS) if row else None


def fetch_rollback_candidates(conn, limit: int = 20) -> list[dict]:
    """Archived/rolled_back versions, newest first — restorable via rollback()."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(_MODEL_VERSION_COLUMNS)} FROM model_versions "
            "WHERE status IN ('archived', 'rolled_back') ORDER BY updated_at DESC LIMIT %(limit)s;",
            {"limit": limit},
        )
        rows = cur.fetchall()
    return [_row_to_dict(row, _MODEL_VERSION_COLUMNS) for row in rows]


def promote_model_version(conn, old_active_id: str | None, new_active_id: str) -> None:
    """Single transaction: old_active_id -> archived, new_active_id -> active.

    Relies on ux_model_versions_single_active to fail loudly on races (two
    concurrent promotions would violate the unique index and raise).
    """
    with conn.cursor() as cur:
        if old_active_id:
            cur.execute(
                "UPDATE model_versions SET status = 'archived', updated_at = NOW() "
                "WHERE model_version_id = %(id)s;",
                {"id": old_active_id},
            )
        cur.execute(
            "UPDATE model_versions SET status = 'active', updated_at = NOW() "
            "WHERE model_version_id = %(id)s;",
            {"id": new_active_id},
        )
    conn.commit()


# ---------------------------------------------------------------------------
# retraining_events
# ---------------------------------------------------------------------------


def insert_retraining_event(conn, event: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(_INSERT_RETRAINING_EVENT_SQL, retraining_event_to_row(event))
    conn.commit()


def update_retraining_event_status(conn, retraining_id: str, status: str, **fields: Any) -> None:
    """Update status plus any of candidate_version_id/reason/metrics/notes."""
    assignments = ["status = %(status)s", "updated_at = NOW()"]
    params: dict[str, Any] = {"retraining_id": retraining_id, "status": status}

    if "candidate_version_id" in fields:
        assignments.append("candidate_version_id = %(candidate_version_id)s")
        params["candidate_version_id"] = fields["candidate_version_id"]
    if "reason" in fields:
        assignments.append("reason = %(reason)s")
        params["reason"] = fields["reason"]
    if "metrics" in fields:
        assignments.append("metrics = %(metrics)s")
        params["metrics"] = _jsonb(fields["metrics"])
    if "notes" in fields:
        assignments.append("notes = %(notes)s")
        params["notes"] = json.dumps(fields["notes"] or [])

    sql = f"UPDATE retraining_events SET {', '.join(assignments)} WHERE retraining_id = %(retraining_id)s;"
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


def fetch_retraining_event(conn, retraining_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(_RETRAINING_EVENT_COLUMNS)} FROM retraining_events "
            "WHERE retraining_id = %(retraining_id)s;",
            {"retraining_id": retraining_id},
        )
        row = cur.fetchone()
    return _row_to_dict(row, _RETRAINING_EVENT_COLUMNS) if row else None


def fetch_recent_retraining_events(conn, since: datetime | None, limit: int = 100) -> list[dict]:
    if since is None:
        since = datetime.fromtimestamp(0, tz=timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(_RETRAINING_EVENT_COLUMNS)} FROM retraining_events "
            "WHERE created_at > %(since)s ORDER BY created_at DESC LIMIT %(limit)s;",
            {"since": since, "limit": limit},
        )
        rows = cur.fetchall()
    return [_row_to_dict(row, _RETRAINING_EVENT_COLUMNS) for row in rows]


def fetch_latest_retraining_event(conn) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(_RETRAINING_EVENT_COLUMNS)} FROM retraining_events "
            "ORDER BY created_at DESC LIMIT 1;"
        )
        row = cur.fetchone()
    return _row_to_dict(row, _RETRAINING_EVENT_COLUMNS) if row else None
