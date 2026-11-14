"""scripts/v643_research.py's runtime (V6.6.6, #359): the chain's frame, harness, score override and as-live memo, every stage and the command,
on the synthetic as-live harness. The heavy research helpers (labels, leakage audit, IC report, PBO, spanning) are stubbed; the chain is real."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import research_fakes
from script_loader import load_script

SCALED = ["a_scaled", "b_scaled", "dist_52w_high_scaled"]
INPUTS = ["x1", "x2"]


def _research_frame(asof: bool = False) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows = []
    for index, day in enumerate(research_fakes.DATES):
        split = "train" if index < 10 else "validation" if index < 18 else "backtest" if index < 26 else "holdout"
        for ticker in research_fakes.TICKERS:
            row = {"date": day, "ticker": ticker, "split": split, "regime_signal_risk_score": float(rng.uniform()), "liquidity_log_dollar_volume": 10.0}
            for name in [*INPUTS, *SCALED, "close_to_close_return_1d", "close_to_close_return_5d", "momentum_20d", "rolling_volatility_20d", "dist_52w_high"]:
                row[name] = float(rng.normal())
            for target in ("target_rank_20d", "target_rank_5d", "target_residual_rank_20d", "target_residual_rank_5d", "target_beta_neutral_rank_20d", "target_beta_neutral_rank_5d",
                           *(("target_residual_rank_20d_asof", "target_beta_neutral_rank_20d_asof") if asof else ())):
                row[target] = float(rng.uniform())
            for target in ("target_return_1d", "target_return_5d", "target_return_20d"):
                row[target] = float(rng.normal(0, 0.02))
            for column in ("asset_class_equity", "asset_class_crypto", "asset_class_bond", "asset_class_future", "asset_class_option", "asset_class_forex"):
                row[column] = 0.0
            rows.append(row)
    return pd.DataFrame(rows)


@pytest.fixture
def chain_world(monkeypatch, tmp_path):
    research_fakes.install(monkeypatch)
    module = load_script("v643_research")
    load_script("v640_research")
    monkeypatch.setattr(module, "ROOT_DIR", tmp_path)
    (tmp_path / "ml").mkdir()
    (tmp_path / "ml" / "feature_schema.json").write_text(json.dumps({"scaled_feature_names": SCALED}), encoding="utf-8")
    (tmp_path / "ml" / "multitask_feature_schema.json").write_text(json.dumps({"model_input_names": INPUTS}), encoding="utf-8")
    config = json.loads((module.ROOT_DIR.parent.parent / "config.json").read_text(encoding="utf-8")) if False else None
    from script_loader import ROOT

    (tmp_path / "config.json").write_text((ROOT / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
    import evaluation.research_probes as probes

    monkeypatch.setattr(probes, "load_research_frame", lambda dataset, columns: _research_frame(asof=True))
    args = SimpleNamespace(dataset="d.csv", asof_labels=str(tmp_path / "labels" / "asof.parquet"), out=str(tmp_path / "out" / "research.json"), max_phases=2, stages=[])
    return module, module.Chain(args), config


def test_the_frame_is_read_once_and_merges_cached_labels(chain_world, tmp_path):
    module, chain, _ = chain_world
    frame = chain.frame()
    assert chain.scaled == SCALED and chain.model_inputs == INPUTS and chain.frame() is frame
    labels_path = tmp_path / "labels" / "asof.parquet"
    labels_path.parent.mkdir()
    pd.DataFrame({"date": research_fakes.DATES[:2], "ticker": ["EQ0", "EQ0"], "extra_label": [1.0, 2.0]}).to_parquet(labels_path, index=False)
    fresh = module.Chain(SimpleNamespace(dataset="d.csv", asof_labels=str(labels_path), out=str(tmp_path / "o2" / "r.json"), max_phases=2))
    assert "extra_label" in fresh.frame().columns


def test_the_installed_score_comes_from_the_harnesses_and_the_override_restores_them(chain_world):
    module, chain, _ = chain_world
    installed = chain.installed_scores()
    assert installed.notna().all() and chain.installed_scores() is not None
    harness = chain.harness("validation")
    assert chain.harness("validation") is harness
    before = harness.frame["live_rank_score"].copy()
    scores = pd.Series(np.linspace(0, 1, len(chain.frame())), index=chain.frame().index)
    with chain.score_override(harness, scores):
        assert not harness.frame["live_rank_score"].equals(before)
    assert np.allclose(harness.frame["live_rank_score"], before)


def test_the_s1_score_reads_the_sector_neutral_head(chain_world):
    module, chain, _ = chain_world
    assert len(chain.s1_scores(splits=("validation",))) == len(chain.frame())


def test_the_phases_are_evenly_spread_and_the_as_live_run_is_memoised(chain_world):
    module, chain, _ = chain_world
    assert len(chain.phases()) == 2
    first = chain.as_live("base", "validation", None)
    assert chain.as_live("base", "validation", None) is first and set(first) == {"summary", "daily"}
    scores = pd.Series(np.linspace(0, 1, len(chain.frame())), index=chain.frame().index)
    assert chain.as_live("t1", "validation", scores)["summary"]


def test_the_ic_report_is_the_research_harness(chain_world, monkeypatch):
    import evaluation.research_harness as harness_module

    module, chain, _ = chain_world
    monkeypatch.setattr(harness_module, "evaluate_signal", lambda frame, **kwargs: {"splits": {"validation": {"h20": {}}}})
    assert chain.ic(pd.Series(0.0, index=chain.frame().index)) == {"validation": {"h20": {}}}


def test_the_label_stage_builds_the_asof_labels_and_measures_the_leak(chain_world, monkeypatch, tmp_path):
    import evaluation.gate_audit as gate_audit
    import evaluation.model_predictions as model_predictions
    import features.asof_beta_labels as labels_module

    module, chain, _ = chain_world
    (tmp_path / "ml" / "multitask_model.json").write_text("{}", encoding="utf-8")
    import evaluation.research_probes as probes

    monkeypatch.setattr(probes, "load_research_frame", lambda dataset, columns: _research_frame(asof=False))
    chain.frame()

    def build(subframe, **kwargs):
        return pd.DataFrame({"target_residual_rank_20d_asof": 0.5, "target_beta_neutral_rank_20d_asof": 0.5}, index=subframe.index)

    monkeypatch.setattr(labels_module, "build_asof_rank_labels", build)
    monkeypatch.setattr(model_predictions, "predict_heads", lambda part, export, names, heads, **kwargs: {head: np.linspace(0, 1, len(part)) for head in heads})
    answers = iter([{"d": 0.1}, {"d": 0.05}, {"d": 0.9}, {"d": 0.2}, {"d": 0.1}, {}, {"d": 0.3}, {}, {"d": 0.9}, {"d": 0.4}, {"d": 0.4}, {"d": 0.4}] * 4)
    monkeypatch.setattr(gate_audit, "daily_rank_ic", lambda *a, **k: next(answers))
    module.stage_labels(chain)
    assert set(chain.report["label_leak"]) == {"validation", "backtest"} and (tmp_path / "labels" / "asof.parquet").exists()
    module.stage_labels(chain)


def test_the_leakage_stage_writes_its_audit(chain_world, monkeypatch):
    import evaluation.leakage_audit as leakage

    module, chain, _ = chain_world
    monkeypatch.setattr(leakage, "audit_leakage", lambda frame, **kwargs: {"flagged": [], "identity": 0.1, "single_feature_ic": {}})
    module.stage_leakage(chain)
    assert chain.report["leakage_audit"]["identity"] == 0.1 and (chain.out.parent / "leakage_audit.json").exists()


def _trial_stubs(monkeypatch):
    import evaluation.factor_spanning as spanning
    import evaluation.gate_audit as gate_audit
    import evaluation.research_probes as probes
    import features.cross_sectional_norm as norm

    monkeypatch.setattr(spanning, "build_factor_scores", lambda frame: pd.DataFrame({column: np.linspace(0, 1, len(frame)) for column in ("f_mom_12_1", "f_mom_20", "f_rev_5", "f_lowvol", "f_high52", "f_composite")}, index=frame.index))
    monkeypatch.setattr(norm, "cross_sectional_rank", lambda frame, columns: frame[columns].rank(pct=True))
    monkeypatch.setattr(probes, "fit_ridge_rank", lambda x, y, alpha: {"rows": len(x)})
    monkeypatch.setattr(probes, "fit_hgb_rank", lambda x, y, **kwargs: {"rows": len(x)})
    monkeypatch.setattr(probes, "predict_scores", lambda model, x: np.linspace(0, 1, len(x)))
    monkeypatch.setattr(gate_audit, "daily_rank_ic", lambda part, **kwargs: {"d": 0.05} if len(part) else {})


def test_the_trial_scores_cover_the_whole_grid(chain_world, monkeypatch):
    module, chain, _ = chain_world
    _trial_stubs(monkeypatch)
    chain.report["leakage_audit"] = {"flagged": ["a_scaled"], "single_feature_ic": {"b_scaled": {"flag": True}}}
    monkeypatch.setattr(chain, "s1_scores", lambda: pd.Series(0.5, index=chain.frame().index))
    scores = module.build_trial_scores(chain)
    assert set(scores) >= {"F1", "F6", "L1", "L2", "L3", "G1", "G2", "G3", "B1", "B2", "B3", "R1", "S1"} and "r1_weights" in chain.report


def _verdict_stubs(monkeypatch, chain, passes: bool):
    import evaluation.pbo as pbo
    import evaluation.factor_spanning as spanning

    monkeypatch.setattr(chain, "ic", lambda scores, splits=("validation", "backtest"): {split: {"h20": {"nonoverlap_mean_ic": 0.2 if passes and scores.name == "trial" else 0.0, "hac_t": 3.0 if passes else 0.0, "mean_ic": 0.1}, "h5": {}} for split in splits})
    monkeypatch.setattr(pbo, "probability_of_backtest_overfitting", lambda matrix, blocks: {"pbo": 0.1 if passes else 0.9})
    monkeypatch.setattr(spanning, "build_factor_returns", lambda part, names: pd.DataFrame({name: np.linspace(0, 0.01, len(part)) for name in names}))
    monkeypatch.setattr(spanning, "factor_spanning", lambda signal, factors: {"alpha_t": 3.0 if passes else 0.0})


@pytest.mark.parametrize("passes", [False, True])
def test_the_grid_pbo_spanning_and_verdict_stages_decide_a_winner_only_when_every_clause_holds(chain_world, monkeypatch, passes):
    module, chain, _ = chain_world
    _trial_stubs(monkeypatch)
    _verdict_stubs(monkeypatch, chain, passes)
    monkeypatch.setattr(chain, "s1_scores", lambda: pd.Series(0.5, index=chain.frame().index))
    if passes:
        monkeypatch.setattr(module, "build_trial_scores", lambda c: {name: c.frame()["momentum_20d"].rename("trial") for name in ("F1", "L1", "G1")})
        import v640_research

        monkeypatch.setattr(v640_research, "verdict_as_live", lambda base, variant: {"passes": True})
    scores = module.stage_grid(chain)
    module.stage_pbo(chain, scores)
    module.stage_spanning(chain, scores)
    module.stage_verdict(chain, scores)
    verdict = chain.report["verdict"]
    assert verdict["rule"] == "R-MODEL11" and (verdict["winner"] is not None) == passes
    if passes:
        assert verdict["winner_type"] in ("overlay", "probe") and chain.report["holdout_reads"]


@pytest.mark.parametrize("stages", [["labels", "leakage", "grid", "pbo", "spanning", "verdict"], ["grid"]])
def test_the_command_runs_the_stages_it_is_given(chain_world, monkeypatch, stages, tmp_path):
    module, chain, _ = chain_world
    calls = []
    for name in ("stage_labels", "stage_leakage", "stage_grid"):
        monkeypatch.setattr(module, name, lambda c, _n=name: calls.append(_n) or {"F1": 1})
    for name in ("stage_pbo", "stage_spanning", "stage_verdict"):
        monkeypatch.setattr(module, name, lambda c, scores, _n=name: calls.append(_n))
    monkeypatch.setattr(module, "Chain", lambda args: chain)
    monkeypatch.setattr(sys, "argv", ["v643", "--stages", *stages, "--out", str(tmp_path / "x" / "r.json")])
    assert module.main() == 0 and calls[0] in ("stage_labels", "stage_grid") and chain.report["phases"]
