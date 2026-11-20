"""evaluation/model_book_round.inverse_vol_share against its Lean 4 model (formal/AetherFormal/InverseVolShare.lean), V6.6.10."""

from __future__ import annotations

import pytest

from aether_quant.formal import load_cases, to_float
from evaluation.model_book_round import inverse_vol_share


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("inverse_vol_share")["cases"]):
        given = case["input"]
        got = inverse_vol_share(to_float(given["model_volatility"]), to_float(given["crypto_volatility"]))
        assert got == pytest.approx(to_float(case["expected"]["share"]), abs=1e-12, rel=1e-9), index
