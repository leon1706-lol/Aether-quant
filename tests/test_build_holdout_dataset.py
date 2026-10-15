"""scripts/build_holdout_dataset.py (V6.0.0 --full-splits): one dataset with all four splits, active scaler."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_holdout_dataset", ROOT / "scripts" / "build_holdout_dataset.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

WINDOWS = {
    "training": {"start": "2014-12-01", "end": "2021-12-31"},
    "validation": {"start": "2022-01-01", "end": "2023-06-30"},
    "backtest": {"start": "2023-07-01", "end": "2025-06-30"},
    "holdout": {"start": "2025-07-01", "end": "2026-09-30"},
}


def test_the_extended_window_runs_from_the_backtest_start_to_the_holdout_end():
    assert builder.full_split_window(WINDOWS) == ("2023-07-01", "2026-09-30")
    with pytest.raises(ValueError):
        builder.full_split_window({key: value for key, value in WINDOWS.items() if key != "holdout"})


def test_only_backtest_rows_from_the_holdout_start_are_relabelled():
    frame = pd.DataFrame(
        {
            "date": ["2021-12-30", "2023-06-30", "2025-06-30", "2025-07-01", "2026-09-29", "2025-07-02"],
            "split": ["train", "validation", "backtest", "backtest", "backtest", None],
        }
    )
    labelled = builder.label_holdout_rows(frame, "2025-07-01")
    # a row outside every window stays unlabelled (None or NaN depending on the pandas version)
    assert labelled["split"].fillna("none").tolist() == ["train", "validation", "backtest", "holdout", "holdout", "none"]
