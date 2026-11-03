"""portfolio/sleeve_guard.py against its Lean 4 model (formal/AetherFormal/SleeveGuard.lean)."""

from __future__ import annotations

import pytest

from aether_quant.formal import load_cases, to_float
from portfolio.sleeve_guard import trailing_drawdown


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("sleeve_guard")["cases"]):
        given = case["input"]
        actual = trailing_drawdown([to_float(x) for x in given["pnl_increments"]], given["lookback_bars"])
        assert actual == pytest.approx(to_float(case["expected"]["drawdown"]), abs=1e-9), index
