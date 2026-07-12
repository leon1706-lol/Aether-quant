"""Scheduled paper-trading readiness reporting (Phase 7 of the 5/10 -> 9/10
roadmap).

execution/paper_readiness_report.py's evaluation logic and dashboard wiring
(monitoring/api_server.py already merges visualization/grafana/
paper_readiness_report.json into /api/state, with a dedicated
get_paper_readiness() endpoint) were already correct and already
dashboard-visible before this module existed - the one real gap this
closes is CADENCE: previously the report only regenerated when a human ran
`aq paper-readiness` by hand, so the dashboard tile could silently go
stale between manual runs. This wraps the exact same
build_paper_readiness_view()/write_paper_readiness_file() calls in a
periodic loop, mirroring performance/trigger_worker.py::TriggerWorker's
shape (sync-only, DSN resolution via AETHER_POSTGRES_DSN, --once CLI flag,
_pg_conn constructor injection for tests) - purely additive reporting.

Hard boundary (Phase 7's scope, per the user's explicit instruction): this
module NEVER touches phase_v2.paper_trading's config flags
(live_data_provider_configured/manual_review_confirmed) and never changes
main.py's actual order-routing behavior - it only keeps the readiness
REPORT fresh. See execution/README.md's "Activating real paper-trading
fills — manual step" section for what a human must still do to actually
go live.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

from execution.paper_readiness_report import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_REPORT_PATH,
    build_paper_readiness_view,
    write_paper_readiness_file,
)

logger = logging.getLogger(__name__)


class PaperReadinessScheduler:
    """Periodically regenerates paper_readiness_report.json.

    Parameters
    ----------
    postgres_dsn   : psycopg3 DSN (overridden by AETHER_POSTGRES_DSN env)
    config         : full config.json dict (build_paper_readiness_view()
                     reads phase_v2.paper_trading from it directly)
    poll_interval  : seconds to sleep between regenerations in run()
    report_path    : where to write the report (test injection point)
    _pg_conn       : injected psycopg3 connection (skips real connection — tests only)
    """

    def __init__(
        self,
        *,
        postgres_dsn: str = "",
        config: dict,
        poll_interval: int = 3600,
        report_path: Path = DEFAULT_REPORT_PATH,
        _pg_conn=None,
    ) -> None:
        self.config = config
        self.poll_interval = poll_interval
        self.report_path = report_path

        if _pg_conn is not None:
            self._conn = _pg_conn
            self._owns_connection = False
        else:
            import psycopg

            dsn = os.environ.get("AETHER_POSTGRES_DSN", postgres_dsn)
            self._conn = psycopg.connect(dsn, autocommit=False)
            self._owns_connection = True
            logger.info("PaperReadinessScheduler: PostgreSQL connected.")

    def run_once(self) -> dict:
        """Regenerates the report once. Returns the written view dict."""
        view = build_paper_readiness_view(self._conn, self.config)
        write_paper_readiness_file(view, path=self.report_path)
        logger.info(
            "PaperReadinessScheduler: report regenerated - ready=%s, blocking_reasons=%s.",
            view["ready"],
            view["blocking_reasons"],
        )
        return view

    def run(self) -> None:
        logger.info("PaperReadinessScheduler: entering run loop (interval=%ds).", self.poll_interval)
        while True:
            try:
                self.run_once()
                time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                logger.info("PaperReadinessScheduler: shutdown requested.")
                break
            except Exception as exc:
                logger.error("PaperReadinessScheduler error — %s. Retrying in %ds.", exc, self.poll_interval)
                time.sleep(self.poll_interval)

    def close(self) -> None:
        if not self._owns_connection:
            return
        try:
            self._conn.close()
        except Exception:
            pass


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
    parser = argparse.ArgumentParser(description="Aether Quant paper-trading readiness scheduler")
    parser.add_argument("--once", action="store_true", help="Regenerate the report once and exit")
    parser.add_argument("--poll-interval", type=int, default=3600, help="Seconds between regenerations")
    args = parser.parse_args()

    with DEFAULT_CONFIG_PATH.open("r", encoding="utf-8") as f:
        config = json.load(f)

    postgres_dsn = os.environ.get("AETHER_POSTGRES_DSN", "")
    scheduler = PaperReadinessScheduler(postgres_dsn=postgres_dsn, config=config, poll_interval=args.poll_interval)
    try:
        if args.once:
            scheduler.run_once()
        else:
            scheduler.run()
    finally:
        scheduler.close()


if __name__ == "__main__":
    main()
