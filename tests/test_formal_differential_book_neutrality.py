"""portfolio/book_neutrality.py against its Lean 4 model (formal/AetherFormal/BookNeutrality.lean)."""

from __future__ import annotations

import pytest

from aether_quant.formal import load_cases, to_float
from portfolio.book_neutrality import apply_book_neutrality


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("book_neutrality")["cases"]):
        given = case["input"]
        raw = {f"N{entry['sym']}": to_float(entry["w"]) for entry in given["weights"]}
        sectors = {f"N{entry['sym']}": f"S{entry['sector']}" for entry in given["weights"]}
        weights, _ = apply_book_neutrality(
            raw, sector_by_symbol=sectors, dollar_neutral=given["dollar_neutral"], sector_neutral=given["sector_neutral"],
            gross_exposure_cap=to_float(given["gross_exposure_cap"]), max_weight_per_name=to_float(given["max_weight_per_name"]),
            sector_max_net_weight=to_float(given["sector_max_net_weight"]),
            reapply_sector_cap_after_dollar_neutral=given["reapply_sector_cap_after_dollar_neutral"],
        )
        expected = {f"N{entry['sym']}": to_float(entry["w"]) for entry in case["expected"]["weights"]}
        assert set(weights) == set(expected), index
        for symbol, value in expected.items():
            assert weights[symbol] == pytest.approx(value, abs=1e-12, rel=1e-9), (index, symbol)
