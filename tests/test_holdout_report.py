"""scripts/holdout_report.py (V6.1.0): the one-look report scores the holdout window, never the backtest split."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("holdout_report", ROOT / "scripts" / "holdout_report.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)

HOLDOUT = {"start": "2025-07-01", "end": "2026-09-30"}


def _frame(rows):
    return pd.DataFrame(rows, columns=["date", "ticker", "split", "training_eligible"])


def test_a_four_split_dataset_returns_only_its_holdout_rows():
    frame = _frame([
        ("2024-03-01", "A", "backtest", True),
        ("2025-07-01", "A", "holdout", True),
        ("2026-09-30", "B", "holdout", True),
        ("2026-01-05", "C", "holdout", False),
    ])
    selected, split = report.select_holdout_rows(frame, HOLDOUT)
    assert split == "holdout"
    assert list(selected["date"]) == ["2025-07-01", "2026-09-30"]


def test_a_legacy_standalone_file_labels_the_holdout_window_backtest():
    frame = _frame([("2025-06-30", "A", "backtest", True), ("2025-08-01", "A", "backtest", True)])
    selected, split = report.select_holdout_rows(frame, HOLDOUT)
    assert split == "backtest"
    assert list(selected["date"]) == ["2025-08-01"]


def test_no_holdout_rows_fails_loudly_instead_of_scoring_another_split():
    frame = _frame([("2024-03-01", "A", "backtest", True)])
    with pytest.raises(ValueError, match="no training-eligible holdout rows"):
        report.select_holdout_rows(frame, HOLDOUT)
