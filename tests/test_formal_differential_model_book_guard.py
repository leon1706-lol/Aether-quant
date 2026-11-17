"""`portfolio.model_book.permit_model_book_row` against its Lean model (formal/AetherFormal/ModelBookGuard.lean, V6.6.9 #394): on all eight combinations."""

from __future__ import annotations

from aether_quant.formal import load_cases
from portfolio.model_book import permit_model_book_row


def test_python_matches_the_lean_model():
    cases = load_cases("model_book_guard")["cases"]
    assert len(cases) == 8
    for index, case in enumerate(cases):
        given = case["input"]
        got = permit_model_book_row(given["pins_ok"], given["row_finite"], given["model_age_ok"])
        assert got is case["expected"]["permit"], (index, given)
