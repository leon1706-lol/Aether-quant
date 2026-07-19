"""Tamper-evident audit trail for order placement, credential loads, and
live-mode transitions (development/Problems.md #42's deferred item).

Same three-piece shape as experience/ (the only other Redis-Stream-backed
package here): redis_queue.py (pure event builder + fire-and-forget
publisher, called from main.py/execution/ - never blocks trading),
postgres_worker.py (drains the stream into a durable, hash-chained Postgres
table), postgres_audit.py (read-only query helpers shared by the CLI and the
webui API route). hash_chain.py is the one pure piece unique to this
package - the tamper-evidence logic itself.
"""

from __future__ import annotations

from .hash_chain import GENESIS_HASH, compute_entry_hash, verify_chain
from .postgres_audit import fetch_all_events_ordered, fetch_recent_events
from .postgres_worker import PostgresWorker, ensure_schema, event_to_row
from .redis_queue import CREDENTIAL_LOAD, EVENT_TYPES, LIVE_MODE_TRANSITION, ORDER_PLACEMENT, AuditQueue, build_audit_event
from .status_export import build_audit_status_view, write_status_file

__all__ = [
    "AuditQueue",
    "build_audit_event",
    "CREDENTIAL_LOAD",
    "EVENT_TYPES",
    "LIVE_MODE_TRANSITION",
    "ORDER_PLACEMENT",
    "compute_entry_hash",
    "verify_chain",
    "GENESIS_HASH",
    "ensure_schema",
    "event_to_row",
    "PostgresWorker",
    "fetch_recent_events",
    "fetch_all_events_ordered",
    "build_audit_status_view",
    "write_status_file",
]
