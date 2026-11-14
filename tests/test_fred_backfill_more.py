"""data_pipeline/fred_backfill.py's remaining branches (V6.6.6, #359): blank cache lines, the bounded sort cache, unreadable cache files and the command."""

from __future__ import annotations

import json
import sys
from datetime import date

import pytest

from data_pipeline import fred_backfill as fb


def test_a_cache_with_blank_lines_reads_back():
    assert fb.cache_csv_to_rows("2025-01-02,1.5\n\n2025-01-03,2.5\n") == [{"date": date(2025, 1, 2), "value": 1.5}, {"date": date(2025, 1, 3), "value": 2.5}]


def test_the_sorted_index_cache_is_cleared_when_full(monkeypatch):
    monkeypatch.setattr(fb, "_SORTED_INDEX_CACHE_MAX", 2)
    fb._SORTED_INDEX_CACHE.clear()
    lists = [[{"date": date(2025, 1, 3), "value": 2.0}, {"date": date(2025, 1, 2), "value": 1.0}] for _ in range(3)]
    for rows in lists:
        assert fb._sorted_index(rows)[1] == [1.0, 2.0]
    assert len(fb._SORTED_INDEX_CACHE) == 1


def test_an_unreadable_old_cache_is_replaced_and_an_unreadable_file_is_skipped(tmp_path, caplog):
    (tmp_path / "DGS10.csv").write_text("not,a,row\n", encoding="utf-8")
    fb.write_fred_series_cache(tmp_path, "DGS10", [{"date": date(2025, 1, 2), "value": 4.0}])
    assert fb.cache_csv_to_rows((tmp_path / "DGS10.csv").read_text(encoding="utf-8")) == [{"date": date(2025, 1, 2), "value": 4.0}]
    (tmp_path / "BAD.csv").write_text("nonsense\n", encoding="utf-8")
    with caplog.at_level("WARNING"):
        loaded = fb.load_cached_fred_series(tmp_path)
    assert set(loaded) == {"DGS10"} and "unreadable cache file" in caplog.text
    assert fb.load_cached_fred_series(tmp_path / "nope") == {}


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"phase_v2": {}}), encoding="utf-8")
    return path


def test_the_command_fetches_each_series_and_writes_only_when_asked(tmp_path, monkeypatch, capsys, config):
    monkeypatch.setattr(fb, "reference_series", lambda cfg, group: {"a": "SA", "b": "SB", "c": "SC"})
    answers = {"SA": [{"date": date(2025, 1, 2), "value": 1.0}], "SB": [], "SC": [{"date": date(2025, 1, 2), "value": 2.0}]}
    monkeypatch.setattr(fb, "fetch_fred_series", lambda series_id, start, end: answers[series_id])
    monkeypatch.setattr(sys, "argv", ["fred", "--config-path", str(config), "--cache-dir", str(tmp_path / "cache"), "--series", "a", "b"])
    fb.main()
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "a (SA): dry_run, rows_fetched=1" in out and "b (SB): no_data_returned" in out and "Dry run only" in out and not (tmp_path / "cache").exists()
    monkeypatch.setattr(sys, "argv", ["fred", "--config-path", str(config), "--cache-dir", str(tmp_path / "cache"), "--apply"])
    fb.main()
    assert "c (SC): written" in capsys.readouterr().out and (tmp_path / "cache" / "c.csv").exists() and not (tmp_path / "cache" / "b.csv").exists()


def test_a_refetch_keeps_the_dates_only_the_old_cache_had(tmp_path):
    fb.write_fred_series_cache(tmp_path, "X", [{"date": date(2025, 1, 2), "value": 1.0}])
    fb.write_fred_series_cache(tmp_path, "X", [{"date": date(2025, 1, 3), "value": 2.0}])
    assert [row["value"] for row in fb.cache_csv_to_rows((tmp_path / "X.csv").read_text(encoding="utf-8"))] == [1.0, 2.0]


def test_the_module_runs_as_a_script(monkeypatch):
    import runpy

    monkeypatch.setattr(sys, "argv", ["fred", "--help"])
    monkeypatch.delitem(sys.modules, "data_pipeline.fred_backfill", raising=False)
    with pytest.raises(SystemExit):
        runpy.run_module("data_pipeline.fred_backfill", run_name="__main__")
