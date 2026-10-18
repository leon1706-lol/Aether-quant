"""scripts/refresh_lean_interest_rate.py (V6.2.0): FRED change points appended after Lean's risk-free file, never over it."""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("refresh_lean_interest_rate", ROOT / "scripts" / "refresh_lean_interest_rate.py")
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


def test_only_changes_after_the_last_row_are_appended():
    existing = [(date(2022, 12, 15), 4.5), (date(2023, 7, 27), 5.5)]
    fred = [(date(2023, 7, 26), 5.25), (date(2023, 7, 27), 5.5), (date(2024, 9, 18), 5.5), (date(2024, 9, 19), 5.0),
            (date(2024, 9, 20), 5.0), (date(2024, 11, 8), 4.75)]
    with pytest.raises(ValueError):  # 2023-07-26: the file holds 4.5 (filled forward), FRED 5.25
        refresh.merge_rate_changes(existing, fred)
    fred[0] = (date(2023, 7, 26), 4.5)
    assert refresh.merge_rate_changes(existing, fred) == [(date(2024, 9, 19), 5.0), (date(2024, 11, 8), 4.75)]


def test_history_before_the_check_date_is_not_compared_and_nothing_new_appends_nothing():
    existing = [(date(2003, 6, 26), 2.0), (date(2023, 7, 27), 5.5)]
    fred = [(date(2003, 6, 25), 2.0), (date(2023, 7, 28), 5.5)]
    assert refresh.merge_rate_changes(existing, fred) == []


def test_change_points_and_the_file_reader(tmp_path):
    assert refresh.change_points([(date(2024, 1, 2), 1.0), (date(2024, 1, 1), 1.0), (date(2024, 1, 3), 2.0)]) == [
        (date(2024, 1, 1), 1.0), (date(2024, 1, 3), 2.0)]
    path = tmp_path / "r.csv"
    path.write_text("DATE,PCREDIT8\n2023-07-27,5.5\n\n", encoding="utf-8")
    header, rows, raw = refresh.read_rate_file(path)
    assert header == "DATE,PCREDIT8" and rows == [(date(2023, 7, 27), 5.5)] and raw == ["2023-07-27,5.5"]
