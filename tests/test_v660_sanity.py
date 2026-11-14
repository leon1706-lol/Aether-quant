"""scripts/v660_sanity.py (V6.6.6): the oracle, its reversal and a random signal go through the scoring path and are written
out. The cell and the scorer are stand-ins, so this checks the script's plumbing, not the research path itself."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd

from script_loader import block_path_writes, run_script


def fake_cell():
    index = [f"2020-01-0{day}" for day in range(1, 6)]
    label = pd.DataFrame(np.arange(10.0).reshape(5, 2), index=index, columns=["A", "B"])
    return SimpleNamespace(
        label=label, member=label.notna(), cell=SimpleNamespace(start="2020-01-01", split="2020-01-03", end="2020-01-05"),
        context=SimpleNamespace(panel=SimpleNamespace(extras={})),
    )


def fake_scoring(monkeypatch, seen):
    def score_sleeve(spec, context, *, start, split, end, signal):
        seen.append((spec.id, spec.params["table"]))
        mean = float(np.nanmean(signal.to_numpy()))
        return {"daily": [], "sharpe": mean, "sharpe_first_half": mean, "sharpe_second_half": mean, "mean_gross": 1.0, "turnover": 0.1}

    import evaluation.premia_research

    monkeypatch.setattr(evaluation.premia_research, "score_sleeve", score_sleeve)


def fake_cell_source(monkeypatch, mean_ic):
    import evaluation.wide_context

    monkeypatch.setattr(evaluation.wide_context, "equity_cell", lambda root, base, name, with_info: fake_cell())
    monkeypatch.setattr(evaluation.wide_context, "signal_ic_t", lambda table, label, start, end: {"mean_ic": mean_ic})


def test_the_three_signals_are_scored_and_written(monkeypatch, capsys):
    seen = []
    fake_scoring(monkeypatch, seen)
    fake_cell_source(monkeypatch, 0.5)
    writes = block_path_writes(monkeypatch)
    assert run_script("v660_sanity", [], monkeypatch) == 0
    assert [name for name, _ in seen] == ["oracle", "reversed_oracle", "random"]
    (written,) = [args for method, path, args in writes if method == "write_text" and path.name == "sanity_wide_path.json"]
    report = json.loads(written[0])
    assert report["oracle"]["sharpe"] == -report["reversed_oracle"]["sharpe"] and report["random"]["mean_ic"] == 0.5
    assert "oracle" in capsys.readouterr().out
