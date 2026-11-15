"""risk/forex_risk.py's cap_forex_target_to_book_weight against its Lean 4 model (formal/AetherFormal/ForexCap.lean)."""

from __future__ import annotations

import math

import pytest

from aether_quant.formal import load_cases, to_float
from risk.forex_risk import cap_forex_target_to_book_weight


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("forex_cap")["cases"]):
        given = case["input"]
        target, book = (math.nan if given[key] is None else to_float(given[key]) for key in ("target", "book"))
        assert cap_forex_target_to_book_weight(target, book) == pytest.approx(to_float(case["expected"]["weight"]), abs=1e-12), index
