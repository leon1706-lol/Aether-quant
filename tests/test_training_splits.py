"""features/training_splits.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

import pandas as pd

from features.training_splits import assign_split


def test_a_date_falls_in_its_window_or_none():
    windows = {"training": {"start": "2020-01-01", "end": "2021-12-31"}, "validation": {"start": "2022-01-01", "end": "2022-12-31"},
               "backtest": {"start": "2023-01-01", "end": "2023-12-31"}}
    assert assign_split(pd.Timestamp("2021-06-01"), windows) == "train"
    assert assign_split(pd.Timestamp("2022-06-01"), windows) == "validation"
    assert assign_split(pd.Timestamp("2019-06-01"), windows) is None
