"""Standalone worker that sends Telegram alerts (Phase V2-19).

Mirrors performance/trigger_worker.py's TriggerWorker shape: Postgres-only,
--once CLI flag, _pg_conn/_telegram_client constructor injection for tests,
config read from config.json directly. Two independent, watermark-gated
channels:

- "triggers": polls performance_triggers (owned by performance/postgres_triggers.py)
  for new rows at or above config["min_severity_for_trigger_alert"]. Because
  this polls every trigger type performance/triggers.py already produces
  (not just drawdown_trigger), risk-lock/regime-shift/liquidity/Sharpe/
  win-rate/confidence-decay/topology alerts all come for free.
- "session_summary": polls experience_events for new event_type="session_summary"
  rows (pushed by main.py at each session rollover, see
  experience/redis_queue.py::build_session_summary_event()).

Never reimplements drawdown/trigger detection or session-summary computation
— both are already durably written elsewhere; this worker only formats and
sends.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

from performance.postgres_triggers import ensure_schema as ensure_performance_schema
from performance.postgres_triggers import fetch_triggers_since

from notifications.postgres_telegram import (
    ensure_schema,
    fetch_session_summaries_since,
    get_watermark,
    set_watermark,
)
from notifications.telegram_alerts import format_session_summary_alert, format_trigger_alert, should_alert_trigger
from notifications.telegram_client import TelegramClient

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def _load_telegram_config(config_path: Path = _CONFIG_PATH) -> dict:
    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)
    return config.get("phase_v2", {}).get("telegram", {})


class TelegramWorker:
    """Polls performance_triggers/experience_events and sends Telegram alerts.

    Parameters
    ----------
    postgres_dsn     : psycopg3 DSN (overridden by AETHER_POSTGRES_DSN env)
    config           : phase_v2.telegram config dict
    poll_interval    : seconds to sleep between polls in run()
    batch_limit      : max rows fetched per channel per run_once() call
    _pg_conn         : injected psycopg3 connection (skips real connection — tests only)
    _telegram_client : injected TelegramClient-like object (skips real HTTP — tests only)
    """

    def __init__(
        self,
        *,
        postgres_dsn: str = "",
        config: dict,
        poll_interval: int = 30,
        batch_limit: int = 200,
        _pg_conn=None,
        _telegram_client=None,
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
            logger.info("TelegramWorker: PostgreSQL connected.")

        self._client = _telegram_client if _telegram_client is not None else TelegramClient()

        ensure_schema(self._conn)
        ensure_performance_schema(self._conn)

    def run_once(self) -> dict:
        """Send any new trigger/session-summary alerts. Returns counts sent.

        No-ops (all zero) if config["enabled"] is False — the master toggle.
        """
        result = {"trigger_alerts_sent": 0, "session_summary_alerts_sent": 0}
        if not self.config.get("enabled", True):
            return result

        result["trigger_alerts_sent"] = self._process_triggers()
        if self.config.get("session_summary_enabled", True):
            result["session_summary_alerts_sent"] = self._process_session_summaries()
        return result

    def _process_triggers(self) -> int:
        since = get_watermark(self._conn, "triggers")
        triggers = fetch_triggers_since(self._conn, since, limit=self.batch_limit)
        if not triggers:
            return 0

        min_severity = str(self.config.get("min_severity_for_trigger_alert", "warning"))
        sent = 0
        for trigger in triggers:
            if not should_alert_trigger(trigger, min_severity=min_severity):
                continue
            if self._client.send_message(format_trigger_alert(trigger)):
                sent += 1
            else:
                logger.warning("TelegramWorker: failed to send trigger alert %s", trigger.get("trigger_id"))

        # Advance the watermark regardless of individual send failures — an
        # unreachable Telegram API must never cause infinite re-alerting.
        set_watermark(self._conn, "triggers", triggers[-1]["created_at"])
        return sent

    def _process_session_summaries(self) -> int:
        since = get_watermark(self._conn, "session_summary")
        summaries = fetch_session_summaries_since(self._conn, since, limit=self.batch_limit)
        if not summaries:
            return 0

        sent = 0
        for summary_event in summaries:
            if self._client.send_message(format_session_summary_alert(summary_event)):
                sent += 1
            else:
                logger.warning(
                    "TelegramWorker: failed to send session summary alert for %s",
                    summary_event.get("session_date"),
                )

        set_watermark(self._conn, "session_summary", summaries[-1]["created_at"])
        return sent

    def run(self) -> None:
        logger.info("TelegramWorker: entering run loop.")
        while True:
            try:
                result = self.run_once()
                logger.info("TelegramWorker: cycle result - %s", result)
                time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                logger.info("TelegramWorker: shutdown requested.")
                break
            except Exception as exc:
                logger.error("TelegramWorker error — %s. Retrying in %ds.", exc, self.poll_interval)
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
    parser = argparse.ArgumentParser(description="Aether Quant Telegram alert worker")
    parser.add_argument("--once", action="store_true", help="Evaluate one batch and exit")
    parser.add_argument(
        "--poll-interval", type=int, default=None, help="Overrides phase_v2.telegram.worker.poll_interval_seconds"
    )
    args = parser.parse_args()

    postgres_dsn = os.environ.get("AETHER_POSTGRES_DSN", "")
    config = _load_telegram_config()
    poll_interval = args.poll_interval
    if poll_interval is None:
        poll_interval = int(config.get("worker", {}).get("poll_interval_seconds", 30))
    batch_size = int(config.get("worker", {}).get("batch_size", 200))

    worker = TelegramWorker(
        postgres_dsn=postgres_dsn, config=config, poll_interval=poll_interval, batch_limit=batch_size
    )
    try:
        if args.once:
            result = worker.run_once()
            logger.info("--once: %s", result)
        else:
            worker.run()
    finally:
        worker.close()


if __name__ == "__main__":
    main()
