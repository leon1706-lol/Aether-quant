"""portfolio/premia_signals.py's cap stage against its Lean 4 model (formal/AetherFormal/PremiaCaps.lean)."""

from __future__ import annotations

import pandas as pd
import pytest

from aether_quant.formal import load_cases, to_float
from portfolio.premia_signals import WeightSettings, _apply_weight_caps


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("premia_caps")["cases"]):
        given = case["input"]
        tickers = [f"t{i}" for i in range(len(given["weights"]))]
        asset_class = {ticker: f"c{cls}" for ticker, cls in zip(tickers, given["classes"])}
        settings = WeightSettings(
            target_vol=0.07, gross_cap=to_float(given["gross_cap"]), name_cap=to_float(given["default_name_cap"]),
            class_caps={f"c{item['class']}": to_float(item["cap"]) for item in given["class_caps"]},
            name_cap_by_class={"c0": to_float(given["name_cap_by_class"][0]), "c1": to_float(given["name_cap_by_class"][1])},
        )
        out = _apply_weight_caps(pd.Series([to_float(w) for w in given["weights"]], index=tickers), asset_class, settings)
        expected = {ticker: to_float(w) for ticker, w in zip(tickers, case["expected"]["weights"]) if to_float(w) != 0.0}
        assert set(out) == set(expected), index
        for ticker, weight in expected.items():
            assert out[ticker] == pytest.approx(weight, abs=1e-9), (index, ticker)
