"""risk/vol_target.py against its Lean 4 model (formal/AetherFormal/VolTarget.lean).

The model takes the risk (the square root) as an input; the covariance here is built so that sqrt(w' Σ w * 252) is it."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from aether_quant.formal import load_cases, to_float
from risk.vol_target import volatility_target_weights


def test_python_matches_the_lean_model():
    for index, case in enumerate(load_cases("vol_target")["cases"]):
        given = case["input"]
        weights = [to_float(w) for w in given["weights"]]
        names = [f"n{i}" for i in range(len(weights))]
        squares = sum(w * w for w in weights)
        risk = to_float(given["risk"])
        if risk is None:
            variance = math.nan
        else:
            variance = 0.0 if squares == 0.0 else risk * risk / (252.0 * squares)
        cov = pd.DataFrame(np.eye(len(names)) * variance, index=names, columns=names)
        out = volatility_target_weights(dict(zip(names, weights, strict=False)), cov, target_annual_vol=to_float(given["target"]), max_leverage=to_float(given["max_leverage"]))
        assert [out[name] for name in names] == pytest.approx([to_float(w) for w in case["expected"]["weights"]], abs=1e-9), index
