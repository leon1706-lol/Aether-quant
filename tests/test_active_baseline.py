"""scripts/active_baseline.py (V6.6.6): the as-live and idealized books of one split, from a stand-in harness."""

from __future__ import annotations

import json

from script_loader import load_script


def test_both_books_are_summarised_and_written(tmp_path, monkeypatch, capsys):
    module = load_script("active_baseline")

    class Harness:
        def __init__(self, split, use_cache, dataset_path):
            self.frame = [1, 2, 3]
            self.use_cache = use_cache

        def as_live(self):
            return 0.4

        def idealized(self):
            return 0.9

    monkeypatch.setattr(module, "AsLiveHarness", Harness)
    monkeypatch.setattr(module, "summarize", lambda result: {"net_sharpe": result})
    out = tmp_path / "baseline.json"
    monkeypatch.setattr(module.sys, "argv", ["x", "--split", "backtest", "--dataset", "d.csv", "--out", str(out), "--no-cache"])
    assert module.main() == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report == {"split": "backtest", "dataset": "d.csv", "rows": 3, "as_live": {"net_sharpe": 0.4}, "idealized": {"net_sharpe": 0.9}}
    assert json.loads(capsys.readouterr().out) == {"as_live": 0.4, "idealized": 0.9}
