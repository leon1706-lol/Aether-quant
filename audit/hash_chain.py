"""Pure tamper-evidence logic for the audit log (development/Problems.md #42).

Each row's hash covers its own content plus the previous row's hash, so
altering or deleting any historical row breaks every hash after it - the
same construction git commits / blockchains use, just for one linear table
instead of a DAG. No I/O here on purpose: audit/postgres_worker.py computes
each new row's hash at insert time (fetching the current chain tail first),
and audit/postgres_audit.py's callers (the CLI's --verify, the API route)
re-verify an already-fetched list of rows through verify_chain() below.
"""

from __future__ import annotations

import datetime
import hashlib
import json

# The hash of the very first entry in the chain (no predecessor to link to) -
# a fixed, well-known genesis value rather than None/empty-string, so an
# empty prev_hash column can never be confused with "chain not yet verified".
GENESIS_HASH = "0" * 64


def canonical_timestamp(value) -> str:
    """The text a row's timestamp is hashed as, and read back as (Problems #339). Postgres stores `created_at` in a TIMESTAMPTZ column and returns a `datetime`, while the hash was taken over
    the producer's string, so a chain read back from a real database could not be verified: `verify_chain` raised on the datetime, and would have mismatched on the offset's spelling even if
    it had not. A datetime, or an ISO 8601 string that parses, is written in UTC as `YYYY-MM-DDTHH:MM:SSZ` (with microseconds only when there are some); anything else is returned as it is.
    `build_audit_event` already writes that form, so rows hashed before this existed verify unchanged."""
    moment = value
    if isinstance(value, str):
        try:
            moment = datetime.datetime.fromisoformat(value.replace("Z", "+00:00") if value.endswith("Z") else value)
        except ValueError:
            return value
    if not isinstance(moment, datetime.datetime):
        return str(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    moment = moment.astimezone(datetime.timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ") if moment.microsecond else moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_entry_hash(prev_hash: str, event_type: str, created_at: str, payload: dict) -> str:
    """sha256(prev_hash || event_type || created_at || canonical-JSON payload).

    `created_at` must be a string (ISO 8601), not a datetime - callers own
    formatting so this stays pure and independent of any particular
    Postgres driver's timestamp type. `payload` is serialized with sorted
    keys and no extra whitespace so the same logical event always hashes
    identically regardless of dict insertion order.
    """
    canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest_input = "|".join([prev_hash, event_type, created_at, canonical_payload])
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()


def verify_chain(rows: list[dict], expected_tail_hash: str | None = None) -> tuple[bool, int | None]:
    """Walks `rows` (each needing prev_hash/hash/event_type/created_at/payload
    keys, oldest-first) recomputing every hash and comparing. Returns
    (all_valid, first_broken_index) - first_broken_index is None when
    all_valid is True, else the 0-based index of the first row whose
    prev_hash doesn't match the prior row's hash, or whose own hash doesn't
    match its recomputed value. An empty list is trivially valid.

    Deleting the newest rows leaves a valid chain: every prefix of a valid chain is valid
    (formal/AetherFormal/HashChain.lean, `truncation_undetected`). `expected_tail_hash`, the latest hash recorded
    somewhere else, closes that gap: a chain that does not end on it reports index len(rows)."""
    expected_prev = GENESIS_HASH
    for index, row in enumerate(rows):
        if row["prev_hash"] != expected_prev:
            return False, index
        recomputed = compute_entry_hash(row["prev_hash"], row["event_type"], row["created_at"], row["payload"])
        if recomputed != row["hash"]:
            return False, index
        expected_prev = row["hash"]
    if expected_tail_hash is not None and expected_prev != expected_tail_hash:
        return False, len(rows)
    return True, None
