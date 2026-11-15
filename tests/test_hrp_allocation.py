"""portfolio/hrp_allocation.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from portfolio.hrp_allocation import compute_hrp_weights


def test_hrp_weights_are_positive_and_sum_to_one():
    returns = pd.DataFrame(np.random.default_rng(5).normal(0, 0.01, (200, 4)), columns=list("ABCD"))
    weights = compute_hrp_weights(returns)
    assert abs(float(weights.sum()) - 1.0) < 1e-9 and (weights > 0).all()
