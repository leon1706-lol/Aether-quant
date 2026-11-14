"""scripts/topology_sizing_research.py's runtime (V6.6.6, #359): R-TOPO's decision, the per-row learned sizing inputs and the whole command (off against the best, mid
and worst peer brackets on both splits), with the as-live harness and the model passes stood in."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from script_loader import load_script


@pytest.fixture
def module(monkeypatch, tmp_path):
    research = load_script("topology_sizing_research")
    (tmp_path / "ml" / "evaluation").mkdir(parents=True)
    monkeypatch.setattr(research, "ROOT_DIR", tmp_path)
    return research


def _split(sharpe):
    return {"net_sharpe": sharpe, "net_max_drawdown": -0.05}


def test_off_replaces_the_shipped_state_only_when_it_beats_on_by_the_gate_margins(module, monkeypatch):
    monkeypatch.setattr(module, "r_gate", lambda base, variant: {"passes_r_gate": variant["backtest"]["net_sharpe"] - base["backtest"]["net_sharpe"] >= 0.1})
    keep = module.decide({"on_mid": {"validation": _split(0.3), "backtest": _split(0.3)}, "off": {"validation": _split(0.3), "backtest": _split(0.35)}})
    off = module.decide({"on_mid": {"validation": _split(0.3), "backtest": _split(0.3)}, "off": {"validation": _split(0.3), "backtest": _split(0.5)}})
    assert keep["branch"] == "keep_on" and keep["topology_learning_enabled"] is True and off["branch"] == "switch_off" and off["topology_learning_enabled"] is False


def test_each_row_with_a_feature_vector_gets_the_learned_inputs_keyed_by_day_and_ticker(module, monkeypatch):
    import topology.learned_topology as learned
    import train_topology

    monkeypatch.setattr(train_topology, "dataset_feature_vectors_indexed", lambda records, probabilities: ([0, 2], [[1.0], [2.0]], [None, None], ["calm", "stress"]))
    monkeypatch.setattr(learned, "learned_sizing_inputs", lambda vector, model, schema, cluster_regime_label, peer_distance, temperature, min_confidence_for_learned: {"vector": vector, "regime": cluster_regime_label, "peer": peer_distance})
    frame = pd.DataFrame({"date": ["2021-01-04 00:00", "2021-01-05", "2021-01-06"], "ticker": ["AAA", "BBB", "CCC"]})
    table = module.topology_inputs_by_row(frame, {}, {}, [0.5, 0.5, 0.5], 0.5, temperature=0.35, min_confidence=0.2)
    assert table == {("2021-01-04", "AAA"): {"vector": [1.0], "regime": "calm", "peer": 0.5}, ("2021-01-06", "CCC"): {"vector": [2.0], "regime": "stress", "peer": 0.5}}


class Harness:
    def __init__(self, split, use_cache, dataset_path):
        self.frame = pd.DataFrame({"date": ["2021-01-04", "2021-01-05"], "ticker": ["AAA", "BBB"]})
        self.topology_inputs_fn = None
        self._mechanisms = {"x": 1}
        self.split = split
        self.sharpes = []

    def as_live(self):
        lookup = self.topology_inputs_fn
        self.sharpes.append(None if lookup is None else lookup("AAA", "2021-01-04 00:00"))
        return SimpleNamespace(sharpe=0.2 + 0.1 * (lookup is None))


def test_the_command_runs_the_book_off_and_at_three_peer_brackets_and_writes_a_decision(module, monkeypatch, tmp_path, capsys):
    import evaluation.model_predictions as predictions
    import evaluation.readme_research as readme_research

    for name in ("topology_model.json", "topology_feature_schema.json", "multitask_model.json"):
        (tmp_path / "ml" / name).write_text("{}", encoding="utf-8")
    (tmp_path / "ml" / "multitask_feature_schema.json").write_text(json.dumps({"model_input_names": ["a"]}), encoding="utf-8")
    (tmp_path / "config.json").write_text(json.dumps({"phase_v2": {"topology_learning": {"temperature": 0.5}}}), encoding="utf-8")
    monkeypatch.setattr(predictions, "predict_heads", lambda frame, model, names, heads, model_kind, batched: {"direction": [0.5] * len(frame)})
    refreshed = []
    monkeypatch.setattr(readme_research, "refresh_readme_best_effort", lambda: refreshed.append(True))
    harnesses = []
    monkeypatch.setattr(module, "AsLiveHarness", lambda split, use_cache, dataset_path: harnesses.append(Harness(split, use_cache, dataset_path)) or harnesses[-1])
    monkeypatch.setattr(module, "summarize", lambda result: {"net_sharpe": result.sharpe, "net_max_drawdown": -0.05})
    monkeypatch.setattr(module, "topology_inputs_by_row", lambda frame, model, schema, probabilities, peer, temperature, min_confidence: {
        ("2021-01-04", "AAA"): {"topology_source": "learned", "topology_confidence": 0.8, "topology_disagreement": 0.1},
        ("2021-01-05", "BBB"): {"topology_source": "deterministic", "topology_confidence": 0.0, "topology_disagreement": 0.0}})
    monkeypatch.setattr(module, "r_gate", lambda base, variant: {"passes_r_gate": False})
    monkeypatch.setattr(sys, "argv", ["topology_sizing_research", "--no-cache"])
    assert module.main() == 0
    written = json.loads((tmp_path / "ml" / "evaluation" / "topology_sizing_research.json").read_text(encoding="utf-8"))
    assert written["decision"]["branch"] == "keep_on" and set(written["results"]) == {"off", "on_best", "on_mid", "on_worst"} and refreshed == [True]
    assert written["multiplier_stats"]["on_mid"]["validation"]["rows"] == 2 and written["multiplier_stats"]["on_mid"]["validation"]["learned_share"] == 0.5
    assert [h.topology_inputs_fn for h in harnesses] == [None, None] and harnesses[0].sharpes[0] is None and "decision:" in capsys.readouterr().out
