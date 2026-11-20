"""risk/kelly.kelly_fraction against its Lean 4 model (formal/AetherFormal/Kelly.lean), V6.6.10."""

from __future__ import annotations

import pytest

from aether_quant.formal import load_cases, to_float
from risk.kelly import kelly_fraction


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("kelly")["cases"]):
        given = case["input"]
        got = kelly_fraction(to_float(given["mean"]), to_float(given["variance"]), fraction=to_float(given["fraction"]), cap=to_float(given["cap"]))
        assert got == pytest.approx(to_float(case["expected"]["kelly"]), abs=1e-12, rel=1e-9), index
