"""Dashboard/monitoring JSON export for retraining state (Phase V2-17).

main.py cannot compute this itself the way it approximates
performance_triggers in-memory - main.py never connects to Postgres, only
Redis (see experience/redis_queue.py). This module is the sole writer of
visualization/grafana/retraining_status.json; monitoring/api_server.py
merges that file into /api/state server-side so the webui's existing
single-fetch useRuntimeState() pattern keeps working unchanged.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from performance.postgres_triggers import fetch_latest_trigger
from retraining.postgres_registry import (
    ensure_schema,
    fetch_active_model_version,
    fetch_latest_candidate_version,
    fetch_latest_retraining_event,
    fetch_rollback_candidates,
)

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_STATUS_PATH = ROOT_DIR / "visualization" / "grafana" / "retraining_status.json"


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _version_summary(version: dict | None) -> dict | None:
    if version is None:
        return None
    return _json_safe(
        {
            "model_version_id": version["model_version_id"],
            "status": version.get("status"),
            "created_at": version.get("created_at"),
            "metrics": version.get("metrics"),
            "aether_vault_commit": version.get("aether_vault_commit"),
        }
    )


def build_status_view(conn) -> dict:
    """Returns the full retraining_status.json payload.

    {generated_at, active_model, latest_candidate, last_trigger,
     latest_retraining_event, validation_status, rollback_available,
     rollback_candidates}
    """
    active = fetch_active_model_version(conn)
    latest_candidate = fetch_latest_candidate_version(conn)
    last_trigger = fetch_latest_trigger(conn)
    latest_event = fetch_latest_retraining_event(conn)
    rollback_candidates = fetch_rollback_candidates(conn)

    validation_status = latest_event.get("status", "none") if latest_event else "none"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active_model": _version_summary(active),
        "latest_candidate": _version_summary(latest_candidate),
        "last_trigger": _json_safe(last_trigger) if last_trigger else None,
        "latest_retraining_event": _json_safe(latest_event) if latest_event else None,
        "validation_status": validation_status,
        "rollback_available": len(rollback_candidates) > 0,
        "rollback_candidates": [
            _json_safe({"model_version_id": v["model_version_id"], "created_at": v["created_at"]})
            for v in rollback_candidates
        ],
    }


def write_status_file(status: dict, path: Path = DEFAULT_STATUS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, indent=2), encoding="utf-8")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
    parser = argparse.ArgumentParser(description="Aether Quant retraining status export")
    parser.parse_args()

    import psycopg

    dsn = os.environ.get("AETHER_POSTGRES_DSN", "")
    conn = psycopg.connect(dsn, autocommit=False)
    try:
        ensure_schema(conn)
        status = build_status_view(conn)
        write_status_file(status)
        logger.info("retraining_status.json written.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
