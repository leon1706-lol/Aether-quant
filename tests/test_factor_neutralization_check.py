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


def test_constant_book_returns_explain_nothing_however_the_floats_round():
    index = pd.date_range("2026-01-01", periods=120)
    market = pd.Series(np.random.default_rng(5).normal(0, 0.01, 120), index=index)
    report = compute_factor_exposure(pd.Series(0.1 + 0.2, index=index), market)
    assert report["r_squared"] == 0.0


def test_sector_factors_load_and_a_singular_design_reports_an_error():
    index = pd.date_range("2026-01-01", periods=120)
    rng = np.random.default_rng(7)
    market = pd.Series(rng.normal(0, 0.01, 120), index=index)
    tech = pd.Series(rng.normal(0, 0.01, 120), index=index)
    report = compute_factor_exposure(market + 0.5 * tech, market, sector_returns={"tech": tech, "short": tech.iloc[:10]})
    assert "sector_tech" in report["loadings"] and "sector_short" not in report["loadings"]
    singular = compute_factor_exposure(market, market, sector_returns={"copy": market})
    assert singular == {"error": "singular design matrix", "n_obs": 120}
