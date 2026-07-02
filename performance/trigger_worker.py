"""Standalone worker that keeps performance_triggers current (V2-16).

Mirrors experience/postgres_worker.py's shape: sync-only, DSN resolution via
AETHER_POSTGRES_DSN, --once CLI flag, _pg_conn constructor injection for
tests. Unlike postgres_worker.py, this worker reads config.json directly —
the 11 threshold keys are strategy config, not infra config, and there is
no Lean/main.py context here to inherit them from.

This is the durable system of record for trigger history: main.py's
in-memory _build_performance_triggers_view() is a fast current-run
visualization only and is never the source Phase 17 should read from.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

from performance.postgres_triggers import (
    ensure_schema,
    fetch_events_since,
    get_watermark,
    insert_triggers,
    set_watermark,
)
from performance.triggers import evaluate_all_triggers

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def _load_performance_triggers_config(config_path: Path = _CONFIG_PATH) -> dict:
    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)
    return config.get("phase_v2", {}).get("performance_triggers", {})


class TriggerWorker:
    """Evaluates performance triggers over new experience_events rows.

    Parameters
    ----------
    postgres_dsn  : psycopg3 DSN (overridden by AETHER_POSTGRES_DSN env)
    config        : phase_v2.performance_triggers config dict
    poll_interval : seconds to sleep between polls in run()
    batch_limit   : max experience_events rows fetched per run_once() call
    _pg_conn      : injected psycopg3 connection (skips real connection — tests only)
    """

    def __init__(
        self,
        *,
        postgres_dsn: str = "",
        config: dict,
        poll_interval: int = 30,
        batch_limit: int = 10_000,
        _pg_conn=None,
    ) -> None:
        self.config = config
        self.poll_interval = poll_interval
        self.batch_limit = batch_limit

        if _pg_conn is not None:
            self._conn = _pg_conn
        else:
            import psycopg

            dsn = os.environ.get("AETHER_POSTGRES_DSN", postgres_dsn)
            self._conn = psycopg.connect(dsn, autocommit=False)
            logger.info("TriggerWorker: PostgreSQL connected.")

        ensure_schema(self._conn)

    def run_once(self) -> int:
        """Fetch new events since the watermark, evaluate, persist.

        Returns count of NEW trigger rows inserted (post-suppression).
        """
        since = get_watermark(self._conn)
        events = fetch_events_since(self._conn, since, limit=self.batch_limit)
        if not events:
            return 0

        report = evaluate_all_triggers(events, self.config)
        inserted = insert_triggers(
            self._conn,
            report["triggers"],
            suppression_minutes=int(self.config.get("suppression_minutes", 60)),
        )
        set_watermark(self._conn, events[-1]["created_at"])
        logger.info(
            "TriggerWorker: evaluated %d events, inserted %d new trigger rows.",
            len(events),
            inserted,
        )
        return inserted

    def run(self) -> None:
        logger.info("TriggerWorker: entering run loop.")
        while True:
            try:
                self.run_once()
                time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                logger.info("TriggerWorker: shutdown requested.")
                break
            except Exception as exc:
                logger.error("TriggerWorker error — %s. Retrying in %ds.", exc, self.poll_interval)
                time.sleep(self.poll_interval)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    parser = argparse.ArgumentParser(description="Aether Quant performance trigger worker")
    parser.add_argument("--once", action="store_true", help="Evaluate one batch and exit")
    parser.add_argument("--poll-interval", type=int, default=30)
    args = parser.parse_args()

    postgres_dsn = os.environ.get("AETHER_POSTGRES_DSN", "")
    config = _load_performance_triggers_config()

    worker = TriggerWorker(postgres_dsn=postgres_dsn, config=config, poll_interval=args.poll_interval)
    try:
        if args.once:
            count = worker.run_once()
            logger.info("--once: inserted %d new trigger rows.", count)
        else:
            worker.run()
    finally:
        worker.close()


if __name__ == "__main__":
    main()
