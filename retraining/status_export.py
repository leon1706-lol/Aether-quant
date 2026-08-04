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
from retraining.auto_rollback import select_rollback_target
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


def _load_auto_rollback_config() -> dict:
    """V5.1 Phase 6 (production safety) - deliberately duplicates
    retraining.orchestrator::_load_retraining_config()'s ~4-line body
    rather than importing it: orchestrator.py already imports
    build_status_view/write_status_file FROM this module, so importing
    back would be circular. Same "small, documented duplication over a
    heavy circular import" precedent as evaluation/rank_book_simulator.py's
    own torch-free bootstrap duplication."""
    config_path = ROOT_DIR / "config.json"
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)
    return config.get("phase_v2", {}).get("retraining", {})


def _hours_since(timestamp) -> float | None:
    if timestamp is None:
        return None
    now = datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return (now - timestamp).total_seconds() / 3600.0


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

    # V5.1 Phase 6 (production safety) - a read-only diagnostic snapshot,
    # reusing active/rollback_candidates already fetched above. Never
    # itself triggers a rollback - retraining/worker.py::RetrainingWorker.
    # check_auto_rollback() is the actual enforcement path, running on its
    # own poll loop with REAL live degradation signals (state.json +
    # recent Postgres triggers). kill_switch_tripped/net_sharpe_decay/
    # rank_ic_decay are always reported False HERE specifically because
    # this exporter (unlike check_auto_rollback()) has no live-signal
    # input wired in - a documented limitation, not a bug: this section
    # exists to show WHEN a rollback could become eligible (runway/
    # cooldown), not to duplicate the real trigger evaluation.
    auto_rollback_config = _load_auto_rollback_config().get("auto_rollback", {})
    bars_since_promotion = _hours_since(active.get("updated_at")) if active else None
    last_rolled_back = next((v for v in rollback_candidates if v.get("status") == "rolled_back"), None)
    bars_since_last_rollback = _hours_since(last_rolled_back.get("updated_at")) if last_rolled_back else None
    degradation_signals = {
        "kill_switch_tripped": False,
        "net_sharpe_decay": False,
        "rank_ic_decay": False,
        "bars_since_promotion": bars_since_promotion,
        "bars_since_last_rollback": bars_since_last_rollback,
    }
    auto_rollback_decision = select_rollback_target(active or {}, rollback_candidates, degradation_signals, auto_rollback_config)

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
        "auto_rollback": _json_safe(
            {
                "config": auto_rollback_config,
                "degradation_signals": degradation_signals,
                "decision": auto_rollback_decision,
            }
        ),
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
