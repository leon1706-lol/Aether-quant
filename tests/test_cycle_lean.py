"""scripts/cycle_lean.py: the clauses of R-BLEND1, and a blend at share 1.0 of the installed file hashing to the same bytes."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from cycle_lean import PIN_FILLS, PINNED_SHA, blended_identity, r_blend1, r_blend2  # noqa: E402

GOOD = {"correlation": 0.995, "annual_gap_bps": 50.0, "fees_within_2pct": True}
ORDERS = {"equal": True, "fills_first": PIN_FILLS}


def test_a_blend_at_share_one_is_the_installed_file_byte_for_byte(tmp_path):
    source = ROOT / "ml" / "target_weights.csv"
    if not source.exists() or hashlib.sha256(source.read_bytes()).hexdigest() != PINNED_SHA:
        pytest.skip("this checkout doesn't hold the pinned bytes: git on Windows may write the file with CRLF")
    report = blended_identity(tmp_path / "identity.csv")
    assert report["sha256"] == PINNED_SHA


def test_every_clause_is_needed():
    assert r_blend1(GOOD, ORDERS, PINNED_SHA)["passed"] is True
    assert r_blend1({**GOOD, "correlation": 0.98}, ORDERS, PINNED_SHA)["passed"] is False
    assert r_blend1({**GOOD, "annual_gap_bps": 101.0}, ORDERS, PINNED_SHA)["passed"] is False
    assert r_blend1({**GOOD, "fees_within_2pct": False}, ORDERS, PINNED_SHA)["passed"] is False
    assert r_blend1(GOOD, {**ORDERS, "equal": False}, PINNED_SHA)["passed"] is False
    assert r_blend1(GOOD, {**ORDERS, "fills_first": 1011}, PINNED_SHA)["passed"] is False
    assert r_blend1(GOOD, ORDERS, "other")["passed"] is False


def test_r_blend2_needs_three_generations_at_once():
    assert r_blend2(GOOD, 5)["passed"] is True
    assert r_blend2(GOOD, 0)["passed"] is False, "a clean run of two generations proves nothing about three"
    assert r_blend2({**GOOD, "correlation": 0.98}, 5)["passed"] is False
    assert r_blend2({}, 5)["passed"] is False


def test_a_missing_figure_fails():
    assert r_blend1({}, {}, "")["passed"] is False
    assert r_blend1({**GOOD, "correlation": None}, ORDERS, PINNED_SHA)["passed"] is False
    assert r_blend1({**GOOD, "fees_within_2pct": None}, ORDERS, PINNED_SHA)["passed"] is False
