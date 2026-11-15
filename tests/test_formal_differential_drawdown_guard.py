"""evaluation/generation_ledger.py's drawdown guard against its Lean 4 model (formal/AetherFormal/DrawdownGuard.lean)."""

from __future__ import annotations

import math

import pytest

from aether_quant.formal import load_cases, to_float
from evaluation.generation_ledger import _max_drawdown


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("drawdown_guard")["cases"]):
        returns = [math.nan if value is None else to_float(value) for value in case["input"]["returns"]]
        assert _max_drawdown(returns) == pytest.approx(to_float(case["expected"]["drawdown"]), abs=1e-9), index
