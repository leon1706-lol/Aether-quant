"""PostgreSQL persistence worker for Aether Quant experience events (V2-14).

Reads from the Redis Stream ``aether:experience`` via XREADGROUP consumer
group semantics and batch-inserts each event permanently into the
``experience_events`` PostgreSQL table.

Design decisions:
- Sync-only: no asyncio; event volume does not justify async complexity.
- Embedded DDL: no Alembic; ensure_schema() is idempotent and called on startup.
- ON CONFLICT (event_id) DO NOTHING: safe idempotent re-delivery.
- Messages are NOT acked until PG commit succeeds — safe at-least-once delivery.
- Malformed JSON → dead-letter stream, immediate XACK, log WARNING.
- _redis_client and _pg_conn constructor params for test injection.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema DDL — embedded constant, no migration files
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS experience_events (
    id            BIGSERIAL PRIMARY KEY,
    event_id      UUID        UNIQUE NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    mode          VARCHAR(20) NOT NULL,
    ticker        VARCHAR(20) NOT NULL,
    symbol        VARCHAR(100) NOT NULL,
    signal        VARCHAR(10) NOT NULL,
    action        VARCHAR(30) NOT NULL,
    confidence    DOUBLE PRECISION,
    target_weight DOUBLE PRECISION,
    payload       JSONB NOT NULL
);
"""

_CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS ix_exp_created_at ON experience_events (created_at);",
    "CREATE INDEX IF NOT EXISTS ix_exp_ticker     ON experience_events (ticker);",
    "CREATE INDEX IF NOT EXISTS ix_exp_mode       ON experience_events (mode);",
    "CREATE INDEX IF NOT EXISTS ix_exp_action     ON experience_events (action);",
    "CREATE INDEX IF NOT EXISTS ix_exp_payload    ON experience_events USING GIN (payload);",
]

_INSERT_SQL = """
INSERT INTO experience_events
    (event_id, created_at, mode, ticker, symbol, signal, action,
     confidence, target_weight, payload)
VALUES
    (%(event_id)s, %(created_at)s, %(mode)s, %(ticker)s, %(symbol)s,
     %(signal)s, %(action)s, %(confidence)s, %(target_weight)s, %(payload)s)
ON CONFLICT (event_id) DO NOTHING;
"""

# ---------------------------------------------------------------------------
# Pure transformation — testable without any I/O
# ---------------------------------------------------------------------------


def event_to_row(event: dict) -> dict[str, Any]:
    """Extract scalar columns + serialised payload from an experience event dict.

    Pure function — no side effects. The returned dict matches _INSERT_SQL
    parameter names and is ready for cur.executemany().
    """
    return {
        "event_id": event["event_id"],
        "created_at": event["created_at"],
        "mode": event["mode"],
        "ticker": event["ticker"],
        "symbol": event["symbol"],
        "signal": event["signal"],
        "action": event["action"],
        "confidence": event.get("confidence"),
        "target_weight": event.get("target_weight"),
        "payload": json.dumps(event),
    }


# ---------------------------------------------------------------------------
# Schema helper
# ---------------------------------------------------------------------------


def ensure_schema(conn) -> None:
    """Create experience_events table and indexes if they do not exist.

    Idempotent — safe to call on every worker startup.
    """
    with conn.cursor() as cur:
        cur.execute(_CREATE_TABLE_SQL)
        for idx_sql in _CREATE_INDEXES_SQL:
            cur.execute(idx_sql)
    conn.commit()
    logger.info("ensure_schema: experience_events ready.")


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class PostgresWorker:
    """Drains aether:experience Redis Stream into PostgreSQL experience_events.

    Parameters
    ----------
    redis_url         : Redis connection URL (overridden by AETHER_REDIS_URL env)
    postgres_dsn      : psycopg3 DSN (overridden by AETHER_POSTGRES_DSN env)
    stream_name       : Redis Stream key to read from
    group_name        : XREADGROUP consumer group name
    consumer_name     : this consumer's name within the group
    batch_size        : max messages per run_once() call
    deadletter_stream : stream key for malformed messages
    backoff_max       : max backoff seconds for run() loop
    _redis_client     : injected Redis client (skips real connection — tests only)
    _pg_conn          : injected psycopg3 connection (skips real connection — tests only)
    """

    def __init__(
        self,
        *,
        redis_url: str = "redis://localhost:6380/0",
        postgres_dsn: str,
        stream_name: str = "aether:experience",
        group_name: str = "aether-workers",
        consumer_name: str = "worker-1",
        batch_size: int = 100,
        deadletter_stream: str = "aether:experience:deadletter",
        backoff_max: int = 60,
        _redis_client=None,
        _pg_conn=None,
    ) -> None:
        self.stream_name = stream_name
        self.group_name = group_name
        self.consumer_name = consumer_name
        self.batch_size = batch_size
        self.deadletter_stream = deadletter_stream
        self.backoff_max = backoff_max

        if _redis_client is not None:
            self._redis = _redis_client
        else:
            import redis as redis_lib
            url = os.environ.get("AETHER_REDIS_URL", redis_url)
            self._redis = redis_lib.from_url(url, socket_connect_timeout=5, socket_timeout=5)
            self._redis.ping()
            logger.info("PostgresWorker: Redis connected at %s", url)

        if _pg_conn is not None:
            self._conn = _pg_conn
        else:
            import psycopg
            dsn = os.environ.get("AETHER_POSTGRES_DSN", postgres_dsn)
            self._conn = psycopg.connect(dsn, autocommit=False)
            logger.info("PostgresWorker: PostgreSQL connected.")

        ensure_schema(self._conn)
        self._ensure_consumer_group()

    def _ensure_consumer_group(self) -> None:
        try:
            self._redis.xgroup_create(
                self.stream_name, self.group_name, id="0", mkstream=True
            )
            logger.info("Consumer group '%s' created on '%s'.", self.group_name, self.stream_name)
        except Exception as exc:
            if "BUSYGROUP" in str(exc):
                logger.debug("Consumer group '%s' already exists.", self.group_name)
            else:
                raise

    def _reconnect_pg(self, postgres_dsn: str) -> None:
        import psycopg
        try:
            self._conn.close()
        except Exception:
            pass
        dsn = os.environ.get("AETHER_POSTGRES_DSN", postgres_dsn)
        self._conn = psycopg.connect(dsn, autocommit=False)
        ensure_schema(self._conn)
        logger.info("PostgresWorker: PostgreSQL reconnected.")

    def run_once(self) -> int:
        """Read one batch, persist, ack. Returns count of events persisted.

        Raises on PostgreSQL failure — messages stay pending for re-delivery.
        """
        results = self._redis.xreadgroup(
            self.group_name,
            self.consumer_name,
            {self.stream_name: ">"},
            count=self.batch_size,
            block=0,  # non-blocking; run() provides the idle sleep
        )
        if not results:
            return 0

        _, messages = results[0]
        rows: list[dict] = []
        ids_good: list = []
        ids_deadletter: list = []

        for msg_id, fields in messages:
            raw = fields.get(b"payload") or fields.get("payload", b"")
            try:
                event = json.loads(raw)
                rows.append(event_to_row(event))
                ids_good.append(msg_id)
            except Exception as exc:
                logger.warning("Malformed message %s → dead-letter. Error: %s", msg_id, exc)
                self._redis.xadd(
                    self.deadletter_stream,
                    {"payload": raw, "error": str(exc), "original_id": str(msg_id)},
                )
                ids_deadletter.append(msg_id)

        # Ack dead-letter messages immediately (they are preserved in deadletter stream)
        if ids_deadletter:
            self._redis.xack(self.stream_name, self.group_name, *ids_deadletter)

        # Persist good rows — only ack after successful commit
        if rows:
            with self._conn.cursor() as cur:
                cur.executemany(_INSERT_SQL, rows)
            self._conn.commit()
            self._redis.xack(self.stream_name, self.group_name, *ids_good)
            logger.info("PostgresWorker: persisted %d events.", len(rows))

        return len(rows)

    def run(self, postgres_dsn: str = "") -> None:
        """Continuous loop with exponential backoff on errors."""
        backoff = 1
        logger.info("PostgresWorker: entering run loop.")
        while True:
            try:
                count = self.run_once()
                if count == 0:
                    time.sleep(1)  # idle poll interval
                else:
                    backoff = 1
            except KeyboardInterrupt:
                logger.info("PostgresWorker: shutdown requested.")
                break
            except Exception as exc:
                logger.error("Worker error — %s. Retrying in %ds.", exc, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, self.backoff_max)
                if postgres_dsn and "connection" in str(exc).lower():
                    try:
                        self._reconnect_pg(postgres_dsn)
                    except Exception as reconn_exc:
                        logger.error("Reconnect failed: %s", reconn_exc)

    def close(self) -> None:
        try:
            self._redis.close()
        except Exception:
            pass
        try:
            self._conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    parser = argparse.ArgumentParser(description="Aether Quant PostgreSQL persistence worker")
    parser.add_argument("--once", action="store_true", help="Read one batch and exit")
    parser.add_argument(
        "--stream",
        default=os.environ.get("AETHER_EXPERIENCE_STREAM", "aether:experience"),
    )
    parser.add_argument(
        "--group",
        default=os.environ.get("AETHER_EXPERIENCE_GROUP", "aether-workers"),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(os.environ.get("AETHER_EXPERIENCE_BATCH_SIZE", "100")),
    )
    args = parser.parse_args()

    redis_url = os.environ.get("AETHER_REDIS_URL", "redis://localhost:6380/0")
    postgres_dsn = os.environ.get("AETHER_POSTGRES_DSN", "")

    worker = PostgresWorker(
        redis_url=redis_url,
        postgres_dsn=postgres_dsn,
        stream_name=args.stream,
        group_name=args.group,
        batch_size=args.batch_size,
    )
    try:
        if args.once:
            count = worker.run_once()
            logger.info("--once: persisted %d events.", count)
        else:
            worker.run(postgres_dsn=postgres_dsn)
    finally:
        worker.close()


if __name__ == "__main__":
    main()
