"""Offline paper-trading readiness report (Phase V2-21).

main.py cannot compute this itself - it never opens its own Postgres
connection (same invariant retraining/status_export.py's docstring
describes). This module is the sole writer of
visualization/grafana/paper_readiness_report.json; monitoring/api_server.py
merges that file into /api/state server-side, and `aq paper-readiness`
(aq_cli.py) runs this as a human-invoked gate before flipping
phase_v2.runtime.mode to "paper".
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from execution.paper_readiness import evaluate_observation_readiness, evaluate_paper_broker_config
from execution.paper_readiness_io import fetch_observation_mode_events
from experience.observation_metrics import compute_observation_summary

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT_DIR / "config.json"
DEFAULT_REPORT_PATH = ROOT_DIR / "visualization" / "grafana" / "paper_readiness_report.json"


def build_paper_readiness_view(conn, config: dict) -> dict:
    """Returns the full paper_readiness_report.json payload.

    {generated_at, ready, checks, blocking_reasons, broker_config_present,
     broker_config_reason, observation_summary}
    """
    paper_trading_config = config.get("phase_v2", {}).get("paper_trading", {})
    thresholds = paper_trading_config.get("readiness_thresholds", {})

    events = fetch_observation_mode_events(conn)
    summary = compute_observation_summary(events)
    observation_readiness = evaluate_observation_readiness(summary, thresholds)
    broker_config_present, broker_config_reason = evaluate_paper_broker_config(paper_trading_config)

    blocking_reasons = list(observation_readiness["blocking_reasons"])
    if not broker_config_present:
        blocking_reasons.append(broker_config_reason)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ready": observation_readiness["ready"] and broker_config_present,
        "checks": observation_readiness["checks"],
        "blocking_reasons": blocking_reasons,
        "broker_config_present": broker_config_present,
        "broker_config_reason": broker_config_reason,
        "observation_summary": summary,
    }


def write_paper_readiness_file(view: dict, path: Path = DEFAULT_REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(view, indent=2), encoding="utf-8")


def _print_summary(view: dict) -> None:
    status = "READY" if view["ready"] else "NOT READY"
    print(f"Paper trading readiness: {status}")
    for name, check in view["checks"].items():
        mark = "PASS" if check["pass"] else "FAIL"
        print(f"  [{mark}] {name}: value={check['value']} threshold={check['threshold']}")
    broker_mark = "PASS" if view["broker_config_present"] else "FAIL"
    print(f"  [{broker_mark}] broker_config: {view['broker_config_reason']}")
    if view["blocking_reasons"]:
        print("Blocking reasons: " + ", ".join(view["blocking_reasons"]))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")

    with DEFAULT_CONFIG_PATH.open("r", encoding="utf-8") as f:
        config = json.load(f)

    import psycopg

    dsn = os.environ.get("AETHER_POSTGRES_DSN", "")
    conn = psycopg.connect(dsn, autocommit=False)
    try:
        view = build_paper_readiness_view(conn, config)
    finally:
        conn.close()

    write_paper_readiness_file(view)
    _print_summary(view)
    return 0 if view["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
