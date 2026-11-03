"""audit/hash_chain.py against its Lean 4 model (formal/AetherFormal/HashChain.lean). Lean verifies an abstract hash
(a toy one in the cases); here the same tampering is applied to a real sha256 chain."""

from __future__ import annotations

from aether_quant.formal import load_cases
from audit.hash_chain import GENESIS_HASH, compute_entry_hash, verify_chain


def _chain(length: int) -> list[dict]:
    rows, prev = [], GENESIS_HASH
    for index in range(length):
        row = {"prev_hash": prev, "event_type": "e", "created_at": f"t{index}", "payload": {"i": index}}
        row["hash"] = compute_entry_hash(prev, "e", f"t{index}", row["payload"])
        rows.append(row)
        prev = row["hash"]
    return rows


def _tamper(rows: list[dict], kind: str, index: int) -> list[dict]:
    if not rows:
        return rows
    rows = [dict(row) for row in rows]
    if kind == "payload":
        rows[index]["payload"] = {"i": rows[index]["payload"]["i"], "x": 1}
    elif kind == "prev":
        rows[index]["prev_hash"] = "f" * 64
    elif kind == "hash":
        rows[index]["hash"] = "e" * 64
    elif kind == "delete":
        del rows[index]
    elif kind == "truncate":
        rows = rows[:index]
    return rows


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("hash_chain")["cases"]):
        given, expected = case["input"], case["expected"]
        rows = _tamper(_chain(given["length"]), given["tamper"], given["index"])
        assert verify_chain(rows) == (expected["valid"], expected["first_broken_index"]), index
