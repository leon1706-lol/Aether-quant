"""scripts/v660_build_panel.py (V6.6.6): a cell's long frame from its start, written as parquet, on a stand-in cell."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from script_loader import load_script, run_script


def test_the_frame_starts_at_the_cell_and_is_written(tmp_path, monkeypatch, capsys):
    module = load_script("v660_build_panel")
    seen = {}

    def equity_cell(root, base, name, *, freeze_path, freeze_digest):
        seen.update(name=name, freeze_path=freeze_path, freeze_digest=freeze_digest)
        return SimpleNamespace(features="f", label="l", sectors="s", member="m", cell=SimpleNamespace(start="2020-01-02"))

    frame = pd.DataFrame({"date": ["2020-01-01", "2020-01-02", "2020-01-03"], "ticker": ["A", "A", "B"], "x": [1.0, 2.0, 3.0]})
    monkeypatch.setattr(module, "equity_cell", equity_cell)
    monkeypatch.setattr(module, "long_frame", lambda features, label, sectors, member: frame)
    out = tmp_path / "panel" / "s.parquet"
    assert module.main(["S", "--out", str(out), "--freeze", str(tmp_path / "f.json"), "--freeze-digest", "abc"]) == 0
    assert list(pd.read_parquet(out)["date"]) == ["2020-01-02", "2020-01-03"]
    assert seen == {"name": "S", "freeze_path": tmp_path / "f.json", "freeze_digest": "abc"} and "2 rows, 2 names" in capsys.readouterr().out
    assert module.main(["S", "--out", str(out)]) == 0 and seen["freeze_path"] is None


def test_help_runs_as_a_script(monkeypatch, capsys):
    assert run_script("v660_build_panel", ["--help"], monkeypatch) == 0
    assert "--freeze-digest" in capsys.readouterr().out
