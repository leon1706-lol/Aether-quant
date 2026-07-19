"""PostgreSQL persistence worker for the audit log (development/Problems.md #42).

Reads from the Redis Stream ``aether:audit`` via XREADGROUP consumer group
semantics (identical mechanics to experience/postgres_worker.py) and
batch-inserts each event into the ``audit_log`` table, computing each row's
hash-chain link (audit/hash_chain.py) at insert time - chaining happens in
durable-write order, not push order, so out-of-order Redis delivery can
never produce a chain that doesn't match on-disk row order.

Design decisions (mirrors experience/postgres_worker.py exactly):
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

from .hash_chain import GENESIS_HASH, compute_entry_hash
from .status_export import build_audit_status_view, write_status_file

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema DDL — embedded constant, no migration files
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS audit_log (
    id            BIGSERIAL PRIMARY KEY,
    event_id      UUID        UNIQUE NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type    VARCHAR(30) NOT NULL,
    actor         VARCHAR(30) NOT NULL,
    prev_hash     CHAR(64)    NOT NULL,
    hash          CHAR(64)    NOT NULL,
    payload       JSONB       NOT NULL
);
"""

_CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS ix_audit_created_at ON audit_log (created_at);",
    "CREATE INDEX IF NOT EXISTS ix_audit_event_type ON audit_log (event_type);",
    "CREATE INDEX IF NOT EXISTS ix_audit_payload    ON audit_log USING GIN (payload);",
]

_INSERT_SQL = """
INSERT INTO audit_log
    (event_id, created_at, event_type, actor, prev_hash, hash, payload)
VALUES
    (%(event_id)s, %(created_at)s, %(event_type)s, %(actor)s,
     %(prev_hash)s, %(hash)s, %(payload)s)
ON CONFLICT (event_id) DO NOTHING;
"""

_LATEST_HASH_SQL = "SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1;"

# ---------------------------------------------------------------------------
# Pure transformation — testable without any I/O
# ---------------------------------------------------------------------------


def event_to_row(event: dict, prev_hash: str) -> dict[str, Any]:
    """Extract INSERT params from an audit event dict plus the chain-tail
    hash it links to. Pure function - computes this row's own hash via
    audit.hash_chain.compute_entry_hash(), never mutates `event`."""
    entry_hash = compute_entry_hash(prev_hash, event["event_type"], event["created_at"], event["payload"])
    return {
        "event_id": event["event_id"],
        "created_at": event["created_at"],
        "event_type": event["event_type"],
        "actor": event.get("actor", "system"),
        "prev_hash": prev_hash,
        "hash": entry_hash,
        "payload": json.dumps(event["payload"]),
    }


# ---------------------------------------------------------------------------
# Schema helper
# ---------------------------------------------------------------------------


def ensure_schema(conn) -> None:
    """Create audit_log table and indexes if they do not exist. Idempotent."""
    with conn.cursor() as cur:
        cur.execute(_CREATE_TABLE_SQL)
        for idx_sql in _CREATE_INDEXES_SQL:
            cur.execute(idx_sql)
    conn.commit()
    logger.info("ensure_schema: audit_log ready.")


def fetch_latest_hash(conn) -> str:
    """The chain tail: the most recently inserted row's hash, or GENESIS_HASH
    if the table is empty. Callers hold this fixed across one run_once()
    batch and thread it forward row-by-row (see PostgresWorker.run_once())
    so a batch of N events chains correctly among themselves before any of
    them are committed."""
    with conn.cursor() as cur:
        cur.execute(_LATEST_HASH_SQL)
        row = cur.fetchone()
    return row[0] if row else GENESIS_HASH


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class PostgresWorker:
    """Drains aether:audit Redis Stream into PostgreSQL audit_log.

    Parameters — identical shape to experience.postgres_worker.PostgresWorker;
    see that class's docstring for the full parameter list. Differs only in
    stream_name/group_name defaults and in computing+persisting the
    hash-chain link for every row (see event_to_row()/fetch_latest_hash()).
    """

    def __init__(
        self,
        *,
        redis_url: str = "redis://localhost:6380/0",
        postgres_dsn: str,
        stream_name: str = "aether:audit",
        group_name: str = "aether-audit-workers",
        consumer_name: str = "worker-1",
        batch_size: int = 100,
        deadletter_stream: str = "aether:audit:deadletter",
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
            logger.info("AuditPostgresWorker: Redis connected at %s", url)

        if _pg_conn is not None:
            self._conn = _pg_conn
        else:
            import psycopg
            dsn = os.environ.get("AETHER_POSTGRES_DSN", postgres_dsn)
            self._conn = psycopg.connect(dsn, autocommit=False)
            logger.info("AuditPostgresWorker: PostgreSQL connected.")

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
        logger.info("AuditPostgresWorker: PostgreSQL reconnected.")

    def run_once(self) -> int:
        """Read one batch, hash-chain it, persist, ack. Returns count of
        events persisted. Raises on PostgreSQL failure — messages stay
        pending for re-delivery."""
        results = self._redis.xreadgroup(
            self.group_name,
            self.consumer_name,
            {self.stream_name: ">"},
            count=self.batch_size,
            # block omitted (not 0 - that means "block forever" in Redis,
            # not "don't block") so this returns immediately; run() provides
            # the idle sleep.
        )
        if not results:
            return 0

        _, messages = results[0]
        rows: list[dict] = []
        ids_good: list = []
        ids_deadletter: list = []
        running_hash = fetch_latest_hash(self._conn)

        for msg_id, fields in messages:
            raw = fields.get(b"payload") or fields.get("payload", b"")
            try:
                event = json.loads(raw)
                row = event_to_row(event, running_hash)
                rows.append(row)
                running_hash = row["hash"]  # chain the NEXT event in this batch to THIS one
                ids_good.append(msg_id)
            except Exception as exc:
                logger.warning("Malformed message %s → dead-letter. Error: %s", msg_id, exc)
                self._redis.xadd(
                    self.deadletter_stream,
                    {"payload": raw, "error": str(exc), "original_id": str(msg_id)},
                )
                ids_deadletter.append(msg_id)

        if ids_deadletter:
            self._redis.xack(self.stream_name, self.group_name, *ids_deadletter)

        if rows:
            with self._conn.cursor() as cur:
                cur.executemany(_INSERT_SQL, rows)
            self._conn.commit()
            self._redis.xack(self.stream_name, self.group_name, *ids_good)
            logger.info("AuditPostgresWorker: persisted %d events.", len(rows))
            # Refresh the webui/API dashboard snapshot right after a real
            # persist (not on every idle poll) - a stale audit trail
            # defeats its own purpose, so this stays close to real-time
            # rather than a periodic cron export. Best-effort: a dashboard
            # export failure must never lose already-committed audit rows.
            try:
                write_status_file(build_audit_status_view(self._conn))
            except Exception as exc:
                logger.warning("AuditPostgresWorker: dashboard export failed: %s", exc)

        return len(rows)

    def run(self, postgres_dsn: str = "") -> None:
        """Continuous loop with exponential backoff on errors."""
        backoff = 1
        logger.info("AuditPostgresWorker: entering run loop.")
        while True:
            try:
                count = self.run_once()
                if count == 0:
                    time.sleep(1)  # idle poll interval
                else:
                    backoff = 1
            except KeyboardInterrupt:
                logger.info("AuditPostgresWorker: shutdown requested.")
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
    parser = argparse.ArgumentParser(description="Aether Quant audit-log persistence worker")
    parser.add_argument("--once", action="store_true", help="Read one batch and exit")
    parser.add_argument(
        "--stream",
        default=os.environ.get("AETHER_AUDIT_STREAM", "aether:audit"),
    )
    parser.add_argument(
        "--group",
        default=os.environ.get("AETHER_AUDIT_GROUP", "aether-audit-workers"),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(os.environ.get("AETHER_AUDIT_BATCH_SIZE", "100")),
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
