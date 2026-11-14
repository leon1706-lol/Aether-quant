"""scripts/v664_table_smoke.py (V6.6.6): builds each trial's table on a free cell and reports coverage; a locked cell is refused."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from script_loader import load_script, run_script


def _draft(tmp_path, cell="CS"):
    draft = {
        "name": "r", "cell": cell, "side": "A", "bar": "b", "rule": "R", "out_dir": "o", "ledger": "l.jsonl", "track": "W",
        "min_live_names": 5, "min_ic_names": 3, "trials": {"t1": {"rebalance_every": 2}, "t2": {}, "t3": {"start": "2020-01-03"}},
    }
    path = tmp_path / "draft.json"
    path.write_text(json.dumps(draft), encoding="utf-8")
    return path


def test_smoke_reports_built_unbuilt_and_empty_tables(tmp_path, monkeypatch):
    module = load_script("v664_table_smoke")
    index = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"]).strftime("%Y-%m-%d")
    tables = {
        "t1": pd.DataFrame({"A": [np.nan, 1.0, 2.0], "B": [np.nan, np.nan, 3.0]}, index=index),
        "t2": None,
        "t3": pd.DataFrame({"A": [np.nan, np.nan, np.nan]}, index=index),
    }
    monkeypatch.setattr(module, "load_cell", lambda spec, root: SimpleNamespace(cell=SimpleNamespace(start="2020-01-01")))
    monkeypatch.setattr(module, "trial_table", lambda spec, trial, cell, built, score_dir: tables[trial])
    monkeypatch.setattr(module, "live_rows", lambda table, entry: table)
    monkeypatch.setattr(module, "live_names_per_rebalance", lambda rows, every: {"median": 1.0, "minimum": 0.0})
    spec = SimpleNamespace(cell="CS", trials={"t1": {"rebalance_every": 2}, "t2": {}, "t3": {"start": "2020-01-03"}})
    lines = []
    report = module.smoke(spec, tmp_path, emit=lines.append)
    assert report["t1"] == {"built": True, "median_live_names": 1.0, "min_live_names": 0.0, "first": "2020-01-02", "last": "2020-01-03"}
    assert report["t2"] == {"built": False} and report["t3"]["first"] is None and report["t3"]["last"] is None
    assert any("not built" in line for line in lines)


def test_main_builds_the_spec_from_the_draft(tmp_path, monkeypatch):
    module = load_script("v664_table_smoke")
    seen = {}
    monkeypatch.setattr(module, "smoke", lambda spec, score_dir: seen.update(spec=spec, score_dir=score_dir))
    monkeypatch.setattr(module.sys, "argv", ["x", str(_draft(tmp_path))])
    assert module.main() == 0
    assert seen["spec"].min_live_names == 5 and seen["spec"].no_ic_clause == () and seen["score_dir"] == module.ROOT / "o" / "scores"


def test_a_locked_cell_is_refused_even_when_run_as_a_script(tmp_path, monkeypatch):
    with pytest.raises(PermissionError, match="free cells only"):
        run_script("v664_table_smoke", [str(_draft(tmp_path, cell="V1"))], monkeypatch)
