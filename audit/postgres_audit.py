"""Read-only query helpers over the audit_log table (development/Problems.md #42).

Shared by `aq audit-log` (aq_cli.py) and monitoring/api_server.py's
`GET /api/audit-log` route - one place owns the SELECT shape so the CLI and
the webui can never drift apart on what a row looks like. Write path lives
in audit/postgres_worker.py (the Redis-Stream-draining worker); this module
never inserts anything.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_COLUMNS = (
    "event_id",
    "created_at",
    "event_type",
    "actor",
    "prev_hash",
    "hash",
    "payload",
)


def _row_to_dict(row: tuple) -> dict[str, Any]:
    return dict(zip(_COLUMNS, row))


def fetch_recent_events(
    conn,
    event_type: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
) -> list[dict]:
    """Newest-first page of audit_log rows, optionally filtered. `since`
    defaults to the Unix epoch (no filter) rather than requiring callers to
    special-case None, matching retraining/postgres_registry.py's
    fetch_recent_retraining_events() convention."""
    if since is None:
        since = datetime.fromtimestamp(0, tz=timezone.utc)
    query = f"SELECT {', '.join(_COLUMNS)} FROM audit_log WHERE created_at > %(since)s"
    params: dict[str, Any] = {"since": since, "limit": limit}
    if event_type is not None:
        query += " AND event_type = %(event_type)s"
        params["event_type"] = event_type
    query += " ORDER BY id DESC LIMIT %(limit)s;"
    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    return [_row_to_dict(row) for row in rows]


def fetch_all_events_ordered(conn) -> list[dict]:
    """Every audit_log row, oldest-first - the shape audit.hash_chain.verify_chain()
    expects. Only ever used by `aq audit-log --verify`; not paginated
    (verification is meaningless over a partial chain)."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(_COLUMNS)} FROM audit_log ORDER BY id ASC;")
        rows = cur.fetchall()
    return [_row_to_dict(row) for row in rows]
