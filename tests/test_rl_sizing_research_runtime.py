"""scripts/rl_sizing_research.py's runtime (V6.6.6, #359): R-RL's decision and the whole command (no RL, five multiplier ranges and the shadow-guarded minimum range, on
both splits), with the as-live harness stood in."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from script_loader import load_script


@pytest.fixture
def module(monkeypatch, tmp_path):
    research = load_script("rl_sizing_research")
    (tmp_path / "ml" / "evaluation").mkdir(parents=True)
    monkeypatch.setattr(research, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(research, "summarize", lambda result: {"net_sharpe": result.net_sharpe})
    return research


def test_a_range_ships_only_when_the_trainer_agrees_and_both_splits_gain(module):
    gains = {"0.9-1.1": {"validation": 0.06, "backtest": 0.01}, "0.8-1.0": {"validation": 0.2, "backtest": 0.07}, "0.6-1.0": {"validation": 0.1, "backtest": 0.06}}
    shipped = module.decide(True, gains)
    assert shipped["branch"] == "edge_pass" and shipped["range"] == [0.8, 1.0] and shipped["shadow_guard"] is False and shipped["passing"] == ["0.6-1.0", "0.8-1.0"]
    for beats in (False, None):
        assert module.decide(beats, gains) == {"branch": "trade_anyway_minimum_range", "range": [0.9, 1.1], "shadow_guard": True, "reason": "trainer verdict false or no range gains >= +0.05 Sharpe on both splits"}
    assert module.decide(True, {"0.9-1.1": {"validation": 0.0, "backtest": 0.0}})["branch"] == "trade_anyway_minimum_range"


class Harness:
    def __init__(self, split, use_cache, dataset_path, rl_model_path):
        self.split = split
        self.calls = []

    def as_live(self, config_overrides=None):
        self.calls.append(config_overrides)
        if not config_overrides:
            return SimpleNamespace(net_sharpe=0.2)
        gain = 0.1 if config_overrides.get("dynamic_risk.min_rl_multiplier") == 0.8 else 0.0
        return SimpleNamespace(net_sharpe=0.2 + gain + (0.01 if "dynamic_risk.rl_shadow_guard" in config_overrides else 0.0))


@pytest.mark.parametrize("beats,branch", [(True, "edge_pass"), (False, "trade_anyway_minimum_range")])
def test_the_command_runs_every_range_and_the_guarded_minimum_on_both_splits(module, monkeypatch, tmp_path, capsys, beats, branch):
    import evaluation.readme_research as readme_research

    harnesses = []
    monkeypatch.setattr(module, "AsLiveHarness", lambda split, use_cache, dataset_path, rl_model_path: harnesses.append(Harness(split, use_cache, dataset_path, rl_model_path)) or harnesses[-1])
    refreshed = []
    monkeypatch.setattr(readme_research, "refresh_readme_best_effort", lambda: refreshed.append(True))
    (tmp_path / "metrics.json").write_text(json.dumps({"policy_beats_constant_unpenalized": beats}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["rl_sizing_research", "--rl-model", "ml/versions/x/rl.json", "--trainer-metrics", str(tmp_path / "metrics.json"), "--no-cache"])
    assert module.main() == 0
    written = json.loads((tmp_path / "ml" / "evaluation" / "rl_sizing_research.json").read_text(encoding="utf-8"))
    assert written["decision"]["branch"] == branch and written["trainer_policy_beats_constant"] is beats and refreshed == [True]
    assert set(written["splits"]) == {"validation", "backtest"} and len(harnesses[0].calls) == 1 + 5 + 1 and written["splits"]["validation"]["minimum_range_with_shadow_guard"]["sharpe_gain"] == pytest.approx(0.01)
    assert "decision:" in capsys.readouterr().out


def test_without_trainer_metrics_the_verdict_is_unknown_and_the_minimum_range_ships(module, monkeypatch, tmp_path):
    import evaluation.readme_research as readme_research

    monkeypatch.setattr(module, "AsLiveHarness", lambda split, use_cache, dataset_path, rl_model_path: Harness(split, use_cache, dataset_path, rl_model_path))
    monkeypatch.setattr(readme_research, "refresh_readme_best_effort", lambda: None)
    monkeypatch.setattr(sys, "argv", ["rl_sizing_research", "--rl-model", "m.json"])
    assert module.main() == 0
    written = json.loads((tmp_path / "ml" / "evaluation" / "rl_sizing_research.json").read_text(encoding="utf-8"))
    assert written["trainer_policy_beats_constant"] is None and written["decision"]["branch"] == "trade_anyway_minimum_range"
