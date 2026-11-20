"""portfolio/book_optimizer.no_trade_band against its Lean 4 model (formal/AetherFormal/NoTradeBand.lean), V6.6.10."""

from __future__ import annotations

import pytest

from aether_quant.formal import load_cases, to_float
from portfolio.book_optimizer import no_trade_band


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("no_trade_band")["cases"]):
        given = case["input"]
        current = {name: to_float(value) for name, value in given["current"]}
        target = {name: to_float(value) for name, value in given["target"]}
        out = no_trade_band(current, target, band=to_float(given["band"]))
        expected = [(name, to_float(value)) for name, value in case["expected"]["row"]]
        assert list(out) == [name for name, _ in expected], index
        assert [out[name] for name, _ in expected] == pytest.approx([value for _, value in expected], abs=1e-12), index
        assert no_trade_band(current, out, band=to_float(given["band"])) == out, "banding twice is banding once (bandRow_idem)"
