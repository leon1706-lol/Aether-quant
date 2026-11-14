"""scripts/v661_replay_check.py (V6.6.6): the ledger's session returns from the pinned weights, against the engine's."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd

from script_loader import load_script, run_script


def _marks():
    sessions = [f"2024-01-0{day}" for day in range(1, 7)]
    return pd.DataFrame({"BTCUSD": [100.0, 101.0, 103.0, 102.0, 104.0, 105.0], "SPY": [50.0, 50.5, 50.2, 50.8, 51.0, 51.3]}, index=sessions)


def test_ledger_returns_hold_each_decision_by_its_fill_lag():
    module = load_script("v661_replay_check")
    marks = _marks()
    rows = {"2024-01-01": {"BTCUSD": 0.5, module.FLAT_TICKER: 0.5}, "2024-01-04": {"BTCUSD": 0.2, "SPY": 0.3}}
    returns = module.ledger_returns(rows, marks, {"BTCUSD": "crypto", "SPY": "equity"}, start="2024-01-02", end="2024-01-05")
    assert list(returns.index) == ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    assert returns.notna().all() and returns.loc["2024-01-03"] > 0


def _patch_main(module, monkeypatch, ledger_values):
    marks = _marks()
    panel = SimpleNamespace(dates=list(marks.index), tickers=list(marks.columns), closes=None, asset_class={"BTCUSD": "crypto"}, sessions=list(marks.index))
    seen = {}
    monkeypatch.setattr(module, "load_market_panel", lambda root, config: seen.update(assets=config["phase1"]["universe"]["assets"]) or panel)
    monkeypatch.setattr(module, "load_weight_file", lambda path, sha: {"2024-01-01": {"BTCUSD": 0.5}})
    monkeypatch.setattr(module, "resolve_target_weights_config", lambda raw: "target")
    monkeypatch.setattr(module, "load_rate_series", lambda path: ([], []))
    monkeypatch.setattr(module, "simulate_target_weights", lambda *args, **kwargs: (kwargs["carry_fn"]("BTCUSD", "2024-01-02"), {"strategy": "daily"})[1])
    monkeypatch.setattr(module, "known_closes", lambda *args: marks)
    index = list(marks.index[1:])
    monkeypatch.setattr(module, "ledger_returns", lambda rows, marks, classes, start, end: pd.Series(ledger_values, index=index))
    monkeypatch.setattr(module, "to_sessions", lambda strategy, sessions: pd.Series(np.linspace(0.01, 0.05, 5), index=index))
    return seen


def test_main_writes_the_report_and_passes_on_a_close_replay(tmp_path, monkeypatch, capsys):
    module = load_script("v661_replay_check")
    seen = _patch_main(module, monkeypatch, list(np.linspace(0.01, 0.05, 5)))
    (tmp_path / "config.json").write_text((module.ROOT / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    assert module.main([]) == 0
    report = json.loads((tmp_path / "ml" / "evaluation" / "v661" / "replay_check.json").read_text(encoding="utf-8"))
    assert report["sessions"] == 5 and report["correlation"] > 0.99 and "correlation_one_bar_early" in capsys.readouterr().out
    assert {asset["ticker"] for asset in seen["assets"]} >= {"SPY", "AGG", "BTCUSD"}
    assert all(asset["security_type"] == "crypto" or asset["ticker"] in ("SPY", "AGG") for asset in seen["assets"])


def test_main_fails_a_replay_that_disagrees(tmp_path, monkeypatch):
    module = load_script("v661_replay_check")
    _patch_main(module, monkeypatch, [0.05, 0.01, 0.04, 0.02, 0.03])
    (tmp_path / "config.json").write_text((module.ROOT / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    assert module.main(["--start", "2024-01-02"]) == 1


def test_help_runs_as_a_script(monkeypatch, capsys):
    assert run_script("v661_replay_check", ["--help"], monkeypatch) == 0
    assert "--start" in capsys.readouterr().out
