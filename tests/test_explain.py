"""lab/explain.py: permutation importance on out-of-sample rows, feature-group ablation and seed stability."""

from __future__ import annotations

import pytest

from lab import explain, trainer
from lab_world import make_lab


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    lab = make_lab(tmp_path_factory.mktemp("lab") / "lab")
    record = trainer.train_run(lab, "lin", log=lambda line: None)
    return lab, lab / "runs" / record["id"]


def test_the_momentum_features_carry_the_planted_signal(trained):
    _, run = trained
    report = explain.explain_run(run)
    assert set(report["importance"]) == {"ret_1", "ret_5", "ret_20", "ret_60", "vol_20", "vol_60"}
    assert report["groups"]["momentum"] > 0 and report["groups"]["momentum"] > (report["groups"]["volatility"] or 0)
    assert report["feature_ic"]["ret_20"] > 0.3
    assert "permutation importance" in explain.render_mapping("permutation importance", report["importance"])
    assert explain.render_mapping("x", {"a": None, "b": 1, "c": 0.5}) == "x\n  a: -\n  b: 1\n  c: +0.5000"


def test_removing_the_momentum_group_costs_the_most_and_an_empty_group_is_noted(trained):
    lab, run = trained
    report = explain.ablate_run(lab, run, groups={"momentum": ["ret_1", "ret_5", "ret_20", "ret_60"], "volatility": ["vol_20", "vol_60"],
                                                  "everything": ["ret_1", "ret_5", "ret_20", "ret_60", "vol_20", "vol_60"]}, log=lambda line: None)
    rows = report["groups"]
    assert rows["momentum"]["change"] < rows["volatility"]["change"] and rows["everything"]["note"] == "nothing left to train on"
    assert set(explain.ablate_run(lab, run, train=lambda *a, **k: {"id": "x", "metrics": {}}, log=lambda line: None)["groups"]) == {"momentum", "volatility"}


def test_seed_stability_reports_the_spread_and_flags_an_unstable_model(trained):
    lab, run = trained
    stable = explain.seed_stability(lab, run, seeds=2, log=lambda line: None)
    assert stable["per_seed_ic"][0] == pytest.approx(stable["per_seed_ic"][1]) and stable["unstable"] is False
    fake = explain.seed_stability(lab, run, seeds=3, train=lambda *a, **k: {"id": "f", "metrics": {"per_seed_ic": {"1": 0.1, "2": -0.1, "3": 0.05}}})
    assert fake["unstable"] is True and fake["range"] == [-0.1, 0.1]
    empty = explain.seed_stability(lab, run, seeds=1, train=lambda *a, **k: {"id": "e", "metrics": {}})
    assert empty["mean"] is None and empty["range"] is None and empty["unstable"] is False


def test_a_network_run_is_explained_through_its_saved_weights(tmp_path):
    pytest.importorskip("torch")
    lab = make_lab(tmp_path / "lab", models={"seq": "tcn"}, epochs=1)
    record = trainer.train_run(lab, "seq", log=lambda line: None)
    report = explain.explain_run(lab / "runs" / record["id"])
    assert set(report["importance"]) == {"ret_1", "ret_5", "ret_20", "ret_60", "vol_20", "vol_60"}
