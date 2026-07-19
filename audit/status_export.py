"""Dashboard/monitoring JSON export for the audit log (development/Problems.md
#42). Same reason as retraining/status_export.py: main.py never connects to
Postgres, only Redis, so monitoring/api_server.py can't query audit_log
directly - this module is the sole writer of
visualization/grafana/audit_log.json, refreshed by audit/postgres_worker.py
after every batch it persists (real-time-ish, not a periodic cron export,
since a stale audit trail defeats its own purpose).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .hash_chain import verify_chain
from .postgres_audit import fetch_all_events_ordered, fetch_recent_events

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_STATUS_PATH = ROOT_DIR / "visualization" / "grafana" / "audit_log.json"

# Dashboard snapshot only ever shows the most recent N entries (unlike
# `aq audit-log`'s CLI, which can page further back) - the webui panel is
# "what's happened recently," not a full audit browser.
_DASHBOARD_ENTRY_LIMIT = 50


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def build_audit_status_view(conn) -> dict:
    """{generated_at, recent_events, chain_valid, total_entries}. Chain
    verification runs over the FULL table (fetch_all_events_ordered), not
    just the dashboard's recent-N slice - a tampered OLD entry must still
    surface as chain_valid=False even if it's scrolled off the recent list."""
    recent = fetch_recent_events(conn, limit=_DASHBOARD_ENTRY_LIMIT)
    all_rows = fetch_all_events_ordered(conn)
    chain_valid, broken_index = verify_chain(all_rows)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_entries": len(all_rows),
        "chain_valid": chain_valid,
        "chain_broken_at_event_id": all_rows[broken_index]["event_id"] if broken_index is not None else None,
        "recent_events": [_json_safe(event) for event in recent],
    }


def write_status_file(status: dict, path: Path = DEFAULT_STATUS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, indent=2), encoding="utf-8")
