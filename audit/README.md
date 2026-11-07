# audit

A tamper-evident, hash-chained log of credential loads, live-mode transitions and order placement (#42, #48). Each row's hash covers its content and the previous hash, so changing or deleting history breaks every later hash.

It mirrors `experience/`: Redis stream, async worker, PostgreSQL, with fire-and-forget publishing so an audit event can never block or stop a trade.

- **`hash_chain.py`:** pure. `compute_entry_hash()`, and `verify_chain(rows, expected_tail_hash=None)`. A prefix of a valid chain is valid, so deleting the newest rows is invisible unless you pass the latest hash recorded elsewhere (proved in `formal/AetherFormal/HashChain.lean`).
- **`redis_queue.py`:** the never-raises publisher to `aether:audit`.
- **`postgres_worker.py`:** drains the stream and links each row at durable-write order, so out-of-order delivery can't disagree with the table. A poison row dead-letters itself and every later row, which would otherwise fork the chain.
- **`postgres_audit.py`:** read-only queries shared by `aq audit-log` and `GET /api/audit-log`.
- **`status_export.py`:** writes `visualization/grafana/audit_log.json` after every batch.

Check it with `aq audit-log --verify`.
