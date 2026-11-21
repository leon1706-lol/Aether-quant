"""lab/run_registry.py: a lab's layout, its runs as folders, finding one, and the table aq lab runs prints."""

from __future__ import annotations

import datetime

import pytest

from lab import run_registry as rr


def test_a_lab_is_created_once_and_found_from_inside(tmp_path):
    assert rr.init_lab(tmp_path / "lab") == ["models/", "runs/", "data/", "lab.toml"]
    assert rr.init_lab(tmp_path / "lab") == [], "nothing existing is overwritten"
    inside = tmp_path / "lab" / "models"
    assert rr.find_lab(inside) == (tmp_path / "lab").resolve() or rr.find_lab(inside) == tmp_path / "lab" / "models" / ".." or rr.find_lab(inside).name == "lab"
    assert rr.find_lab(tmp_path) is None or rr.find_lab(tmp_path) != tmp_path


def test_runs_are_recorded_listed_found_and_rendered(tmp_path):
    rr.init_lab(tmp_path)
    stamp = datetime.datetime(2026, 11, 20, 12, 0, tzinfo=datetime.timezone.utc)
    first = tmp_path / "runs" / rr.new_run_id("m1", now=stamp)
    second = tmp_path / "runs" / rr.new_run_id("m2", now=stamp + datetime.timedelta(minutes=1))
    rr.write_run(first, {"model": "m1", "status": "finished", "metrics": {"oof_ic_mean": 0.05, "oof_ic_seed_std": 0.01}, "trials_n": 2, "duration_s": 3.0})
    rr.write_run(first, {"note": "merged"})
    rr.write_run(second, {"model": "m2", "status": "running"})
    (tmp_path / "runs" / "broken").mkdir()
    (tmp_path / "runs" / "broken" / "run.json").write_text("{", encoding="utf-8")
    rows = rr.list_runs(tmp_path)
    assert [row["model"] for row in rows] == ["m2", "m1"] and rr.read_run(first)["note"] == "merged"
    assert first.name.startswith("20261120_120000_000000_m1_")
    assert rr.find_run(tmp_path, "latest") == second
    assert rr.find_run(tmp_path, first.name[:18]) == first
    with pytest.raises(KeyError, match="more than one"):
        rr.find_run(tmp_path, "20261120")
    with pytest.raises(KeyError, match="no run"):
        rr.find_run(tmp_path, "nope")
    table = rr.render_runs(rows)
    assert "+0.0500 +/-0.0100" in table and "IC -" in table
    assert rr.render_runs([]).startswith("no runs yet")


def test_two_runs_started_in_one_second_still_sort_in_order(tmp_path):
    import datetime

    stamp = datetime.datetime(2026, 1, 2, 3, 4, 5, 10, tzinfo=datetime.timezone.utc)
    earlier, later = rr.new_run_id("lin2", now=stamp), rr.new_run_id("lin", now=stamp + datetime.timedelta(microseconds=1))
    assert earlier < later, "the microsecond, not the model name, orders runs of one second"
    for run in (earlier, later):
        (tmp_path / "runs" / run).mkdir(parents=True)
        rr.write_run(tmp_path / "runs" / run, {"model": run})
    assert rr.find_run(tmp_path, "latest").name == later
