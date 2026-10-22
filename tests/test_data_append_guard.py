"""scripts/data_append_guard.py + scripts/data_append_refresh.py (V6.4.0, Problems.md #215): the refresh may only add rows."""

from __future__ import annotations

import importlib.util
import zipfile
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    sys.path.insert(0, str(ROOT))
    spec.loader.exec_module(module)
    return module


guard = _load("data_append_guard")


def _write_zip(path: Path, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{path.stem}.csv", "\n".join(rows) + "\n")


def _tree(tmp_path, rows):
    _write_zip(tmp_path / "equity" / "usa" / "daily" / "aaa.zip", rows)
    fred = tmp_path / "reference" / "fred_series" / "rate.csv"
    fred.parent.mkdir(parents=True, exist_ok=True)
    fred.write_text("2026-09-29,2.35\n2026-09-30,2.36\n", encoding="utf-8")
    return tmp_path


OLD = ["20260929 00:00,1000000,1010000,990000,1000000,100", "20260930 00:00,1000000,1020000,995000,1010000,120"]


def test_row_date_reads_lean_and_fred_rows():
    assert guard.row_date("20260930 00:00,1,2,3,4,5") == "2026-09-30"
    assert guard.row_date("2026-09-30,2.36") == "2026-09-30"
    assert guard.row_date("date,value") is None


def test_an_appended_row_passes_and_a_revised_row_fails(tmp_path):
    data = _tree(tmp_path, OLD)
    before = guard.snapshot(data, "2026-09-30")
    _write_zip(data / "equity" / "usa" / "daily" / "aaa.zip", OLD + ["20261001 00:00,1010000,1030000,1000000,1020000,90"])
    after = guard.snapshot(data, "2026-09-30")
    assert guard.verify(before, after) == []
    assert after["equity/usa/daily/aaa.zip"]["last"] == "2026-10-01" and after["equity/usa/daily/aaa.zip"]["rows"] == 2
    _write_zip(data / "equity" / "usa" / "daily" / "aaa.zip", [OLD[0], "20260930 00:00,1000000,1020000,995000,1011000,120"])
    problems = guard.verify(before, guard.snapshot(data, "2026-09-30"))
    assert problems == [{"path": "equity/usa/daily/aaa.zip", "reason": "rows_up_to_the_cutoff_changed", "rows_before": 2, "rows_after": 2}]


def test_a_vanished_file_is_a_violation_and_a_new_file_is_not(tmp_path):
    data = _tree(tmp_path, OLD)
    before = guard.snapshot(data, "2026-09-30")
    (data / "reference" / "fred_series" / "rate.csv").unlink()
    _write_zip(data / "equity" / "usa" / "daily" / "bbb.zip", OLD)
    assert guard.verify(before, guard.snapshot(data, "2026-09-30")) == [
        {"path": "reference/fred_series/rate.csv", "reason": "missing_after_refresh"}]


def test_splice_ratio_uses_the_latest_common_date_and_defaults_to_one():
    ratio, anchor = guard.splice_ratio({"2026-09-29": 100.0, "2026-09-30": 101.0}, {"2026-09-30": 100.495, "2026-10-01": 102.0})
    assert anchor == "2026-09-30" and ratio == pytest.approx(101.0 / 100.495)
    assert guard.splice_ratio({"2026-09-30": 50.0}, {"2026-09-30": 50.0}) == (1.0, "2026-09-30")
    assert guard.splice_ratio({"2026-09-30": 50.0}, {"2026-10-01": 50.0}) == (1.0, None)


def test_scale_new_rows_keeps_volume_and_drops_old_rows():
    rows = [{"date": date(2026, 9, 30), "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0},
            {"date": date(2026, 10, 1), "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}]
    scaled = guard.scale_new_rows(rows, 2.0, "2026-09-30")
    assert len(scaled) == 1 and scaled[0]["close"] == 3.0 and scaled[0]["high"] == 4.0 and scaled[0]["volume"] == 10.0


def test_merge_csv_keeps_stored_values_up_to_the_cutoff():
    old = "2026-09-29,2.35\n2026-09-30,2.36\n"
    new = "2026-09-29,2.40\n2026-09-30,2.50\n2026-10-01,2.37\n"  # the fetch revised two stored days
    assert guard.merge_csv_append_only(old, new, "2026-09-30") == "2026-09-29,2.35\n2026-09-30,2.36\n2026-10-01,2.37\n"
    assert guard.merge_csv_append_only(old, "", "2026-09-30") == old


def test_merge_csv_does_not_add_a_late_published_date_before_the_cutoff():
    old = "2026-09-01,2.30\n2026-09-30,2.36\n"
    new = "2026-09-01,2.30\n2026-09-15,2.33\n2026-09-30,2.36\n2026-10-01,2.37\n"
    assert guard.merge_csv_append_only(old, new, "2026-09-30") == "2026-09-01,2.30\n2026-09-30,2.36\n2026-10-01,2.37\n"
