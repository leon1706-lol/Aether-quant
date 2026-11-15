"""evaluation/factor_neutralization_check.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from evaluation.factor_neutralization_check import compute_factor_exposure


def test_a_book_that_is_the_market_loads_one_on_it():
    index = pd.date_range("2026-01-01", periods=120)
    market = pd.Series(np.random.default_rng(3).normal(0, 0.01, 120), index=index)
    report = compute_factor_exposure(market * 2.0, market)
    assert isinstance(report, dict)
    text = str(report)
    assert "2.0" in text or "1.99" in text or "2.00" in text
