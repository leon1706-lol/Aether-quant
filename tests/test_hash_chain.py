"""Tests for audit.hash_chain — the tamper-evidence logic behind the audit
log (development/Problems.md #42). Pure functions, no I/O.
"""

from audit.hash_chain import GENESIS_HASH, compute_entry_hash, verify_chain


def test_compute_entry_hash_is_deterministic():
    h1 = compute_entry_hash(GENESIS_HASH, "order_placement", "2026-07-17T12:00:00Z", {"symbol": "AAPL"})
    h2 = compute_entry_hash(GENESIS_HASH, "order_placement", "2026-07-17T12:00:00Z", {"symbol": "AAPL"})
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex digest


def test_compute_entry_hash_independent_of_payload_key_order():
    h1 = compute_entry_hash(GENESIS_HASH, "order_placement", "2026-07-17T12:00:00Z", {"a": 1, "b": 2})
    h2 = compute_entry_hash(GENESIS_HASH, "order_placement", "2026-07-17T12:00:00Z", {"b": 2, "a": 1})
    assert h1 == h2


def test_compute_entry_hash_changes_with_any_input():
    base = compute_entry_hash(GENESIS_HASH, "order_placement", "2026-07-17T12:00:00Z", {"symbol": "AAPL"})
    assert base != compute_entry_hash("f" * 64, "order_placement", "2026-07-17T12:00:00Z", {"symbol": "AAPL"})
    assert base != compute_entry_hash(GENESIS_HASH, "credential_load", "2026-07-17T12:00:00Z", {"symbol": "AAPL"})
    assert base != compute_entry_hash(GENESIS_HASH, "order_placement", "2026-07-17T12:00:01Z", {"symbol": "AAPL"})
    assert base != compute_entry_hash(GENESIS_HASH, "order_placement", "2026-07-17T12:00:00Z", {"symbol": "MSFT"})


def _chain(*payloads: dict) -> list[dict]:
    """Build a genuinely-valid chain of rows for the given payloads, oldest first."""
    rows = []
    prev = GENESIS_HASH
    for i, payload in enumerate(payloads):
        created_at = f"2026-07-17T12:00:{i:02d}Z"
        event_type = "order_placement"
        entry_hash = compute_entry_hash(prev, event_type, created_at, payload)
        rows.append(
            {"event_type": event_type, "created_at": created_at, "payload": payload, "prev_hash": prev, "hash": entry_hash}
        )
        prev = entry_hash
    return rows


def test_verify_chain_empty_is_valid():
    assert verify_chain([]) == (True, None)


def test_verify_chain_valid_single_entry():
    rows = _chain({"symbol": "AAPL"})
    assert verify_chain(rows) == (True, None)


def test_verify_chain_valid_multi_entry():
    rows = _chain({"symbol": "AAPL"}, {"symbol": "MSFT"}, {"symbol": "TSLA"})
    assert verify_chain(rows) == (True, None)


def test_verify_chain_detects_tampered_payload():
    rows = _chain({"symbol": "AAPL"}, {"symbol": "MSFT"}, {"symbol": "TSLA"})
    rows[1]["payload"] = {"symbol": "TAMPERED"}  # hash no longer matches recomputed value

    valid, broken_index = verify_chain(rows)

    assert valid is False
    assert broken_index == 1


def test_verify_chain_detects_deleted_middle_row():
    rows = _chain({"symbol": "AAPL"}, {"symbol": "MSFT"}, {"symbol": "TSLA"})
    del rows[1]  # row[2]'s prev_hash no longer matches row[0]'s hash

    valid, broken_index = verify_chain(rows)

    assert valid is False
    assert broken_index == 1


def test_verify_chain_detects_wrong_first_prev_hash():
    rows = _chain({"symbol": "AAPL"})
    rows[0]["prev_hash"] = "1" * 64  # should be GENESIS_HASH

    valid, broken_index = verify_chain(rows)

    assert valid is False
    assert broken_index == 0
