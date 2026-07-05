"""IO layer for paper/live broker readiness (Phase V2-21/V2-22).

Mirrors risk/manual_override.py's read pattern: a single-key, mtime-gated
config.json reader (see execution/config_cache.py) so a long-running
paper/live process can pick up a config edit at the next session rollover
without a restart. Also provides the one new Postgres query
paper_readiness_report.py needs - observation-mode experience_events, which
performance/postgres_triggers.py's existing fetch_recent_events()/
fetch_events_since() don't filter by mode.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from execution.config_cache import read_cached

_PHASE_V2_KEY = "phase_v2"
_PAPER_TRADING_KEY = "paper_trading"


def read_paper_trading_config(config_path: Path) -> dict:
    """Mtime-gated read of phase_v2.paper_trading. Returns {} if the file or
    key is absent - never raises."""
    return read_cached(config_path, _read_paper_trading_config_uncached)


def _read_paper_trading_config_uncached(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)
    value = config.get(_PHASE_V2_KEY, {}).get(_PAPER_TRADING_KEY, {})
    return value if isinstance(value, dict) else {}


def fetch_observation_mode_events(conn, limit: int = 10_000, since: datetime | None = None) -> list[dict]:
    """Fetch experience_events payloads logged in mode='observation', oldest
    first - feeds evaluate_observation_readiness() via
    experience.observation_metrics.compute_observation_summary()."""
    if since is None:
        since = datetime.fromtimestamp(0, tz=timezone.utc)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT payload FROM experience_events WHERE mode = %(mode)s AND created_at > %(since)s "
            "ORDER BY created_at ASC LIMIT %(limit)s;",
            {"mode": "observation", "since": since, "limit": limit},
        )
        rows = cur.fetchall()

    return [json.loads(row[0]) if isinstance(row[0], str) else row[0] for row in rows]
