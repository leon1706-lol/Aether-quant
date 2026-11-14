"""scripts/gate_research.py (V6.6.6): R-GATE's decision, every experiment's call, and the run over both splits."""

from __future__ import annotations

import json

from script_loader import load_script


def _summary(sharpe, drawdown):
    return {"net_sharpe": sharpe, "net_total_return": 0.01, "net_max_drawdown": drawdown, "kill_switch_locked_dates": 0}


def test_r_gate_needs_a_backtest_gain_and_no_real_loss_elsewhere():
    module = load_script("gate_research")
    base = {"backtest": _summary(0.5, -0.10), "validation": _summary(0.4, -0.10)}
    assert module.decide(base, {"backtest": _summary(0.65, -0.105), "validation": _summary(0.39, -0.10)})["passes_r_gate"] is True
    assert module.decide(base, {"backtest": _summary(0.65, -0.13), "validation": _summary(0.4, -0.10)})["passes_r_gate"] is False
    assert module.decide(base, {"backtest": _summary(0.55, -0.10), "validation": _summary(0.4, -0.10)})["backtest_sharpe_gain"] == 0.05


class _Harness:
    def __init__(self, split, use_cache=True, dataset_path=None):
        self.split, self.calls = split, []

    def as_live(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs


def test_every_experiment_calls_the_harness():
    module = load_script("gate_research")
    groups = module.experiments({})
    harness = _Harness("backtest")
    for runs in groups.values():
        for run in runs.values():
            run(harness)
    assert len(harness.calls) == sum(len(runs) for runs in groups.values())
    assert {"min_rank_confidence_spread": 0.25} in harness.calls and {"gate": "off"} in harness.calls


def test_main_runs_the_chosen_groups_and_names_r_gate_winners(tmp_path, monkeypatch, capsys):
    module = load_script("gate_research")
    monkeypatch.setattr(module, "AsLiveHarness", _Harness)

    def summarize(kwargs):
        good = kwargs.get("min_rank_confidence_spread") == 0.25 or kwargs.get("gate") == "off"
        return _summary(0.9 if good else 0.5, -0.10)

    monkeypatch.setattr(module, "summarize", summarize)
    out = tmp_path / "gates.json"
    monkeypatch.setattr(module.sys, "argv", ["x", "--group", "spread", "ic_gate", "--only", "0.25", "ic gate off", "--out", str(out)])
    assert module.main() == 0
    results = json.loads(out.read_text(encoding="utf-8"))
    assert set(results) == {"as-live (config)", "spread floor 0.25", "ic gate off"}
    assert results["ic gate off"]["decision"]["passes_r_gate"] is True
    assert "R-GATE passes: ['spread floor 0.25']" in capsys.readouterr().out


def test_main_defaults_to_every_group_and_the_standard_path(tmp_path, monkeypatch, capsys):
    module = load_script("gate_research")
    monkeypatch.setattr(module, "AsLiveHarness", _Harness)
    monkeypatch.setattr(module, "summarize", lambda kwargs: _summary(0.5, -0.1))
    monkeypatch.setattr(module, "ROOT_DIR", tmp_path)
    (tmp_path / "ml" / "evaluation").mkdir(parents=True)
    monkeypatch.setattr(module.sys, "argv", ["x", "--no-cache"])
    assert module.main() == 0
    assert "R-GATE passes: none" in capsys.readouterr().out and (tmp_path / "ml" / "evaluation" / "v570_gate_research.json").exists()
