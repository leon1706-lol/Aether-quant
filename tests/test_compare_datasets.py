"""scripts/compare_datasets.py (V6.1.0): two dataset builds compared cell by cell."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("compare_datasets", ROOT / "scripts" / "compare_datasets.py")
compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare)


def _frame(rows):
    return pd.DataFrame(rows, columns=["date", "ticker", "split", "x", "y"]).set_index(["date", "ticker"]).sort_index()


def test_differences_are_counted_per_column_and_ticker():
    reference = _frame([("d1", "A", "train", 1.0, 2.0), ("d1", "B", "train", 1.0, np.nan), ("d2", "A", "train", 3.0, 4.0)])
    candidate = _frame([("d1", "A", "train", 1.0, 2.0), ("d1", "B", "validation", 1.5, 0.0), ("d3", "A", "train", 3.0, 4.0)])
    report = compare.compare_frames(reference, candidate)
    assert report["num_only_reference"] == 1 and report["num_only_candidate"] == 1
    assert report["columns_differing"] == {"x": {"max": 0.5, "rows_over": 1}, "y": {"max": 0.0, "rows_over": 1}}
    assert report["differing_cells_by_ticker"] == {"B": 2}
    assert report["split_mismatch_rows"] == 1


def test_identical_frames_report_nothing():
    frame = _frame([("d1", "A", "train", 1.0, np.nan)])
    report = compare.compare_frames(frame, frame.copy())
    assert report["columns_differing"] == {} and report["split_mismatch_rows"] == 0
