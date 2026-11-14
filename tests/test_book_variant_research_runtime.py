"""scripts/book_variant_research.py's runtime (V6.6.6, #359): conflicting variants in a combination, and the whole R-BOOK run (each variant against B0 on both modes
and both splits, the head and dataset variants, the greedy combination and the holdout look) with the as-live harness stood in."""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import pytest

from script_loader import load_script


@pytest.fixture
def research(monkeypatch, tmp_path):
    module = load_script("book_variant_research")
    monkeypatch.setattr(module, "ROOT_DIR", tmp_path)
    config = {"phase_v2": {"rank_signal": {"heads": {"rank_20d": 1.0}, "min_promotion_status": ["promotable", "watchlist"]}}}
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return module


def test_two_variants_that_set_the_same_key_differently_never_combine(research):
    research.VARIANTS["X1"] = {"config": {"portfolio_book.top_n": 4}}
    research.VARIANTS["X2"] = {"config": {"portfolio_book.top_n": 5}}
    research.VARIANTS["X3"] = {"heads": {"a": 1.0}, "ml_dir": "one"}
    research.VARIANTS["X4"] = {"heads": {"b": 1.0}, "ml_dir": "two"}
    try:
        assert research.merge_variants(["X1", "X2"]) == {} and research.merge_variants(["X3", "X4"]) == {}
        assert research.merge_variants(["B1", "B3"])["heads"] == {"rank_20d": 1.0}
    finally:
        for key in ("X1", "X2", "X3", "X4"):
            research.VARIANTS.pop(key)


def test_the_greedy_combination_skips_a_conflicting_variant_and_keeps_the_ones_that_pass(research):
    research.VARIANTS["X1"] = {"config": {"portfolio_book.top_n": 4}}
    research.VARIANTS["X2"] = {"config": {"portfolio_book.top_n": 5}}
    base = {"ungated": {"validation": {"net_sharpe": 0.1, "net_max_drawdown": -0.1}, "backtest": {"net_sharpe": 0.1, "net_max_drawdown": -0.1}}}
    better = {"ungated": {"validation": {"net_sharpe": 0.3, "net_max_drawdown": -0.1}, "backtest": {"net_sharpe": 0.4, "net_max_drawdown": -0.1}}}
    try:
        chosen, log = research.greedy_combination(["X1", "X2"], {"X1": 0.3, "X2": 0.2}, lambda spec: better, base, "B", lambda spec: True)
    finally:
        research.VARIANTS.pop("X1")
        research.VARIANTS.pop("X2")
    assert chosen == ["X1"] and log[-1] == {"variant": "X2", "skipped": "conflicts with an adopted variant"}


def _sharpe(split, overrides, heads, dataset, gate, ml_dir):
    """A stand-in for each scored row set: B1 (a slower rebalance) gains on the backtest, a new model's heads gain too, everything else equals B0."""
    value = 0.30 if split == "validation" else 0.20
    overrides = overrides or {}
    if overrides.get("portfolio_book.rebalance_every_bars") == 20 and not ml_dir:
        value += 0.25 if split == "backtest" else 0.02
    if ml_dir:
        value += 0.25 if split == "backtest" else 0.02
    if heads and "residual_rank_20d" in heads:
        value += 0.25 if split == "backtest" else 0.01
    if gate == "off":
        value += 0.01
    return value


class Harness:
    def __init__(self, split, dataset_path, config, ml_dir):
        self.split, self.dataset_path, self.config, self.ml_dir = split, dataset_path, config, ml_dir

    def as_live(self, config_overrides=None, **kwargs):
        heads = self.config["phase_v2"]["rank_signal"]["heads"]
        return SimpleNamespace(net_sharpe=_sharpe(self.split, config_overrides, heads, str(self.dataset_path), kwargs.get("gate"), self.ml_dir), split=self.split)


def _install(monkeypatch, *, calls):
    levers = types.ModuleType("as_live_levers")
    levers.AsLiveHarness = Harness
    levers.summarize = lambda result: {"net_sharpe": result.net_sharpe, "net_max_drawdown": -0.1}
    calibration = types.ModuleType("lean_calibration")
    calibration.calibrated_overrides = lambda harness: {"rebalance_counter_start": 0}
    calibration.topology_inputs_fn_for = lambda harness, cfg: calls.append("topology") or "fn"
    calibration.use_topology = lambda harness, fn: calls.append("use")
    monkeypatch.setitem(sys.modules, "as_live_levers", levers)
    monkeypatch.setitem(sys.modules, "lean_calibration", calibration)


def _calibration(tmp_path, branch="B"):
    folder = tmp_path / "ml" / "evaluation" / "v600"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "calibration.json").write_text(json.dumps({"verdict": {"branch": branch}}), encoding="utf-8")


def test_a_variant_that_clears_every_margin_is_adopted_and_the_holdout_is_looked_at(research, monkeypatch, tmp_path, capsys):
    calls = []
    _install(monkeypatch, calls=calls)
    _calibration(tmp_path)
    out = tmp_path / "out" / "book.json"
    monkeypatch.setattr(sys, "argv", ["book_variant_research", "--only", "B1", "B2a", "--out", str(out), "--dataset", "ml/datasets/full.csv"])
    assert research.main() == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["branch"] == "B" and written["verdicts"]["B1"]["adopted"] is True and written["verdicts"]["B2a"]["adopted"] is False
    assert written["final"]["adopted"] == ["B1"] and set(written["final"]["holdout_seen"]) == {"b0", "final"} and "R-BOOK adopted: ['B1']" in capsys.readouterr().out and "topology" in calls


def test_head_and_dataset_variants_load_their_own_scores_and_branch_a_also_judges_the_as_live_book(research, monkeypatch, tmp_path, capsys):
    calls = []
    _install(monkeypatch, calls=calls)
    _calibration(tmp_path, branch="A")
    version = tmp_path / "ml" / "versions" / "v600cs20261015_mt_v8_rank60_s1"
    version.mkdir(parents=True)
    (version / "multitask_training_metrics.json").write_text(json.dumps({"backtest": {"rank_60d_ranking_quality": {"quality_status": "promotable"}}}), encoding="utf-8")
    out = tmp_path / "book_a.json"
    monkeypatch.setattr(sys, "argv", ["book_variant_research", "--only", "B7", "B9", "--out", str(out), "--branch", "A"])
    assert research.main() == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["verdicts"]["B9"]["head_status_ok"] is True and "B0@B9" in written["results"] and "as_live" in written["verdicts"]["B7"]
    assert written["verdicts"]["B7"]["head_status_ok"] is True and written["final"]["adopted"] == ["B7"]


def test_when_nothing_beats_the_costs_only_the_base_book_meets_the_holdout(research, monkeypatch, tmp_path, capsys):
    _install(monkeypatch, calls=[])
    _calibration(tmp_path)
    out = tmp_path / "none.json"
    monkeypatch.setattr(sys, "argv", ["book_variant_research", "--only", "B3", "--out", str(out)])
    assert research.main() == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["final"]["adopted"] == [] and set(written["final"]["holdout_seen"]) == {"b0"} and "none (no variant beats costs)" in capsys.readouterr().out
