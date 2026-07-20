# audit

Owns the **tamper-evident audit log** — a hash-chained record of
security-relevant events (credential loads, live-mode transitions, and the
per-bar order-placement path), added in V2-18 (see
`development/Problems.md` #42, hardened further in #48).

This package is a deliberate structural mirror of `experience/`: same
Redis-Stream → async-worker → PostgreSQL pipeline, same fire-and-forget
publish contract, so audit events can be emitted from `main.py`'s hot path
and from `execution/`'s credential/live-mode call sites without ever risking
a real trade or blocking a live process on a Postgres round-trip. What makes
it *audit* rather than *experience* is the hash chain: each row's hash covers
its own content plus the previous row's hash, so altering or deleting any
historical row breaks every hash after it (the same construction git commits
and blockchains use, applied to one linear table).

Members:

- `hash_chain.py` — pure tamper-evidence logic, no I/O. `compute_entry_hash()`
  (`sha256(prev_hash || event_type || created_at || canonical-JSON payload)`)
  and `verify_chain()`. `GENESIS_HASH` is a fixed all-zero value so an empty
  `prev_hash` can never be confused with "not yet verified".
- `redis_queue.py` — the fire-and-forget Redis Stream publisher (`aether:audit`),
  mirroring `experience/redis_queue.py`'s never-raises contract exactly.
- `postgres_worker.py` — drains the Redis Stream via `XREADGROUP` consumer-group
  semantics and batch-inserts into the `audit_log` table, computing each row's
  hash-chain link **at durable-write order** (not push order), so out-of-order
  Redis delivery can never produce a chain that disagrees with on-disk row
  order. Idempotent embedded DDL (`ensure_schema()`), no Alembic — same design
  as `experience/postgres_worker.py`.
- `postgres_audit.py` — read-only query helpers over `audit_log`, shared by the
  `aq audit-log` CLI and `monitoring/api_server.py`'s `GET /api/audit-log`
  route so the CLI and webui can never drift on row shape. Never inserts.
- `status_export.py` — sole writer of `visualization/grafana/audit_log.json`,
  refreshed by `postgres_worker.py` after every persisted batch (real-time-ish,
  not a periodic cron export — a stale audit trail defeats its own purpose),
  since `main.py` only ever connects to Redis, not Postgres.

Verify the chain end-to-end with `aq audit-log --verify` (re-hashes every row
and reports the first break, if any). See `development/infrastructure.md`'s
audit section for the worker's Compose service and `development/Problems.md`
#42/#48 for the full design rationale and the reconciliation/`init: true`
hardening.
