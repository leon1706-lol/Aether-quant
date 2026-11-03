"""features/cross_sectional_norm.py (V6.4.3)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from features.cross_sectional_norm import cross_sectional_rank


def test_ranks_are_per_date_and_centred():
    frame = pd.DataFrame({"date": ["a", "a", "a", "b", "b"], "x": [1.0, 2.0, 3.0, 10.0, -10.0]})
    ranked = cross_sectional_rank(frame, ["x"])
    assert ranked["x"].tolist() == [1 / 3 - 0.5, 2 / 3 - 0.5, 0.5, 0.5, 0.0]


def test_nan_stays_nan_and_ties_average():
    frame = pd.DataFrame({"date": ["a"] * 4, "x": [1.0, 1.0, np.nan, 2.0]})
    ranked = cross_sectional_rank(frame, ["x"])["x"]
    assert np.isnan(ranked.iloc[2])
    assert ranked.iloc[0] == ranked.iloc[1]


def test_group_column_ranks_within_groups():
    frame = pd.DataFrame({"date": ["a"] * 4, "cls": ["e", "e", "c", "c"], "x": [1.0, 2.0, 100.0, 200.0]})
    ranked = cross_sectional_rank(frame, ["x"], group_column="cls")["x"]
    assert ranked.tolist() == [0.0, 0.5, 0.0, 0.5]


def test_empty_frame_returns_empty_columns():
    out = cross_sectional_rank(pd.DataFrame({"date": [], "x": []}), ["x"])
    assert list(out.columns) == ["x"] and out.empty
