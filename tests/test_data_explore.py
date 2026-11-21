"""lab/data_explore.py: a close table read from a wide or long file, its coverage, and the one-file exploration page."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lab import data_explore as de
from lab_world import planted_closes


def test_wide_long_and_parquet_tables_read_the_same(tmp_path):
    closes = planted_closes(rows=40, names=3)
    closes.to_csv(tmp_path / "wide.csv", index_label="date")
    long = closes.stack().rename("close").reset_index()
    long.columns = ["Date", "Ticker", "Close"]
    long.to_csv(tmp_path / "long.csv", index=False)
    wide = de.read_closes(tmp_path / "wide.csv")
    pd.testing.assert_frame_equal(wide, de.read_closes(tmp_path / "long.csv"), check_names=False)
    assert wide.index[0] == "2020-01-02" and list(wide.columns) == ["C0", "C1", "C2"]
    pytest.importorskip("pyarrow")
    closes.to_parquet(tmp_path / "c.parquet")
    assert de.read_closes(tmp_path / "c.parquet").shape == (40, 3)


def test_info_reports_spans_missing_shares_and_gaps():
    closes = planted_closes(rows=30, names=3)
    closes.iloc[:5, 0] = np.nan
    closes.iloc[10:15, 1] = np.nan
    closes.iloc[:, 2] = np.nan
    report = de.info(closes)
    rows = report["per_ticker"]
    assert rows["C0"]["first"] == closes.index[5] and rows["C0"]["missing"] == 0.0 and rows["C0"]["longest_gap"] == 0
    assert rows["C1"]["longest_gap"] == 5 and report["gaps_over_3"] == ["C1"] and rows["C2"]["missing"] == 1.0
    assert report["calendar"] == "weekdays" and "longest gap 5" in de.render_info(report) and "gaps over 3 rows: C1" in de.render_info(report)
    assert de.info(closes.iloc[0:0])["start"] is None
    assert de.calendar_kind(pd.Index([str(day.date()) for day in pd.date_range("2024-01-01", periods=7)])) == "7-day"


def test_the_exploration_page_is_self_contained():
    closes = planted_closes(rows=120, names=4)
    data = de.explore(closes, title="Demo")
    assert set(data["moments"]) == set(closes.columns) and data["correlation"].shape == (4, 4) and data["periods"] == 252.0
    page = de.render_explore_html(data)
    assert page.startswith("<!doctype html>") and "<script" not in page and page.count("<svg") >= 5 and "Correlation of daily returns" in page
    assert de.explore(closes.iloc[:2])["moments"] == {}
