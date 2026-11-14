"""scripts/v644_research.py's runtime (V6.6.6, #359): the candidate files, the chain, every stage of R-MODEL12 and R-TREND1, and the command, on the
synthetic as-live harness. The simulation, the IC report, the PBO and the spanning are stubbed; the stage logic and its clauses are real."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import research_fakes
from script_loader import ROOT, load_script
from test_v643_research_runtime import SCALED, INPUTS, _research_frame

SUMMARY = {"median_net_sharpe": 0.5, "phases": 2, "net_sharpe_by_phase": [0.4, 0.6], "median_net_max_drawdown": -0.05, "p25_net_sharpe": 0.4, "p10_net_sharpe": 0.4,
           "iqr_net_sharpe": 0.1, "cost_drag_by_phase": [40.0, 40.0], "median_turnover": 3.0, "p05_net_max_drawdown": -0.07, "legacy_net_return_median": 0.01}


@pytest.fixture
def world(monkeypatch, tmp_path):
    research_fakes.install(monkeypatch)
    load_script("v640_research")
    load_script("v643_research")
    module = load_script("v644_research")
    out_dir = tmp_path / "ml" / "evaluation" / "v644"
    for name in ("ROOT_DIR", "OUT_DIR"):
        monkeypatch.setattr(module, name, tmp_path if name == "ROOT_DIR" else out_dir)
    import v643_research

    monkeypatch.setattr(v643_research, "ROOT_DIR", tmp_path)
    (tmp_path / "ml").mkdir(exist_ok=True)
    (tmp_path / "ml" / "feature_schema.json").write_text(json.dumps({"scaled_feature_names": SCALED}), encoding="utf-8")
    (tmp_path / "ml" / "multitask_feature_schema.json").write_text(json.dumps({"model_input_names": INPUTS}), encoding="utf-8")
    config_text = (ROOT / "config.json").read_text(encoding="utf-8")
    (tmp_path / "config.json").write_text(config_text, encoding="utf-8")
    configs = out_dir / "configs"
    configs.mkdir(parents=True)
    for grid_id in module.GRID:
        (configs / f"{grid_id}.json").write_text(config_text, encoding="utf-8")
    import evaluation.research_probes as probes

    monkeypatch.setattr(probes, "load_research_frame", lambda dataset, columns: _research_frame(asof=True))
    args = SimpleNamespace(dataset="d.csv", asof_labels=str(tmp_path / "asof.parquet"), out=str(out_dir / "research.json"), max_phases=2, centred=False, memo=None, smoke=False,
                           wf_candidate="M1", wf_summary=None)
    chain = module.Chain644(args)
    monkeypatch.setattr(chain, "as_live", lambda trial, split, scores: {"summary": dict(SUMMARY), "daily": {day: 0.001 * ((i % 4) - 1) for i, day in enumerate(research_fakes.DATES)}})
    return module, chain, tmp_path


def _make_versions(module, tmp_path, grid_ids, seeds=(1, 2, 3)):
    for grid_id in grid_ids:
        for seed in seeds:
            folder = module.version_dir(grid_id, seed)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "multitask_model.json").write_text("{}", encoding="utf-8")
            (folder / "multitask_feature_schema.json").write_text("{}", encoding="utf-8")
            (folder / "multitask_training_metrics.json").write_text(json.dumps({"quality_status": "promotable"}), encoding="utf-8")


def test_candidate_files_are_assembled_from_the_installed_ml_and_the_members(world):
    module, chain, tmp_path = world
    _make_versions(module, tmp_path, ["M1"])
    (tmp_path / "ml" / "scaler_stats.json").write_text("{}", encoding="utf-8")
    assert module.version_dir("M1", 2).name == "v644_M1_s2" and module.candidate_config("M1", ensemble=True)["phase_v2"]["model_ensemble"]["enabled"] is True
    members = [module.version_dir("M1", seed) for seed in (1, 2, 3)]
    target = module.candidate_ml_dir("E", members, ensemble=True)
    assert (target / "scaler_stats.json").exists() and len(list((target / "multitask_ensemble").glob("member_*.json"))) == 3
    plain = module.candidate_ml_dir("E", members, ensemble=False)
    assert plain == target and not (target / "multitask_ensemble").exists()


def test_the_group_centred_targets_have_zero_group_means(world):
    module, chain, _ = world
    frame = module.add_centred_targets(_research_frame(asof=True).assign(target_sector_neutral_rank_20d=0.5), chain.config)
    assert "target_rank_20d_c" in frame and frame.groupby(["date", "_rank_group"])["target_rank_20d_c"].mean().abs().max() < 1e-5


def test_the_chain_reads_a_shared_memo_loads_its_frame_and_scores_an_ic_on_either_target(world, monkeypatch, tmp_path):
    import evaluation.research_harness as harness_module

    module, chain, _ = world
    memo = tmp_path / "memo.json"
    memo.write_text(json.dumps({"k": 1}), encoding="utf-8")
    shared = module.Chain644(SimpleNamespace(dataset="d.csv", asof_labels="x", out=str(tmp_path / "o" / "r.json"), max_phases=2, centred=True, memo=str(memo)))
    assert shared.memo == {"k": 1} and shared.tag == "_r13"
    frame = chain.frame()
    assert chain.frame() is frame and "target_rank_20d_c" in frame
    seen = []
    monkeypatch.setattr(harness_module, "evaluate_signal", lambda data, **kwargs: seen.append(kwargs["target_template"]) or {"splits": {split: {"h20": {"mean_ic": 0.1}} for split in kwargs["splits"]}})
    scores = pd.Series(0.5, index=frame.index)
    assert chain.ic_on(scores, "rank_20d")["validation"] == {"mean_ic": 0.1}
    chain.args.centred = True
    chain.ic_on(scores, "sector_neutral_rank_20d", splits=("holdout",))
    assert seen == ["target_rank_{h}d", "target_sector_neutral_rank_{h}d_c"]


def test_candidate_scores_are_cached_and_the_installed_book_can_exclude_tickers(world):
    module, chain, tmp_path = world
    first = chain.candidate_scores("c", tmp_path / "ml", chain.config)
    assert len(first) == len(chain.frame()) and (module.OUT_DIR / "scores" / "c__validation+backtest.parquet").exists()
    assert chain.candidate_scores("c", tmp_path / "ml", chain.config).equals(first)
    harness = chain.harness("validation")
    with chain.exclude_tickers(harness, ["EQ0"]):
        assert harness.frame.loc[harness.frame["ticker"] == "EQ0", "live_rank_score"].isna().all()
    assert chain.installed().notna().all()


def test_viability_and_the_first_clause(world):
    module, chain, tmp_path = world
    _make_versions(module, tmp_path, ["M0"], seeds=(1,))
    assert set(module.viability(module.version_dir("M0", 1), module.candidate_config("M0"))) == {"passes", "kept_head_weights", "model_priority"}
    ic = {"validation": {"mean_ic": 0.2, "nonoverlap_mean_ic": 0.2}}
    installed = {"validation": {"nonoverlap_mean_ic": 0.1}}
    assert module.c1_check(ic, {"identity_prior_ic": 0.1, "class_prior_ic": None}, installed)["passes"] is True
    assert module.c1_check({"validation": {"mean_ic": None, "nonoverlap_mean_ic": None}}, {"identity_prior_ic": 0.1}, installed)["passes"] is False


def _ic_stub(chain, monkeypatch, validation=0.2, backtest_t=3.0):
    monkeypatch.setattr(chain, "ic_on", lambda scores, head, splits=("validation", "backtest"): {split: {"mean_ic": 0.1, "nonoverlap_mean_ic": validation if scores.name == "cand" else 0.0, "hac_t": backtest_t} for split in splits})
    monkeypatch.setattr(chain, "candidate_scores", lambda name, ml_dir, config, splits=("validation", "backtest"): pd.Series(np.linspace(0, 1, len(chain.frame())), index=chain.frame().index, name="cand"))


def _run_to_verdict(module, chain, tmp_path, monkeypatch, *, passing=True):
    import evaluation.factor_spanning as spanning
    import evaluation.leakage_audit as leakage
    import evaluation.pbo as pbo

    import v640_research

    monkeypatch.setattr(v640_research, "verdict_as_live", lambda base, variant: {"passes": passing})
    _make_versions(module, tmp_path, ["M0", "M1"])
    _ic_stub(chain, monkeypatch, validation=0.2 if passing else 0.0)
    monkeypatch.setattr(leakage, "identity_check", lambda train, validation, target, **kwargs: {"identity_prior_ic": 0.0, "class_prior_ic": 0.0})
    monkeypatch.setattr(pbo, "probability_of_backtest_overfitting", lambda matrix, blocks: {"pbo": 0.1 if passing else 0.9})
    monkeypatch.setattr(spanning, "build_factor_scores", lambda frame: pd.DataFrame({c: np.linspace(0, 1, len(frame)) for c in ("f_mom_12_1", "f_mom_20", "f_rev_5", "f_lowvol", "f_high52")}, index=frame.index))
    monkeypatch.setattr(spanning, "build_factor_returns", lambda part, names: pd.DataFrame({name: np.linspace(0, 0.01, len(part)) for name in names}))
    monkeypatch.setattr(spanning, "factor_spanning", lambda signal, factors: {"alpha_t": 1.0})
    module.stage_priors(chain)
    module.stage_stage1(chain)
    module.stage_stage2(chain)
    module.stage_ensemble(chain)
    module.stage_aslive(chain)
    module.stage_pbo(chain)
    module.stage_spanning(chain)
    module.stage_walkforward_pick(chain)


def test_the_model_stages_run_end_to_end_and_pick_a_walk_forward_order(world, monkeypatch):
    module, chain, tmp_path = world
    _run_to_verdict(module, chain, tmp_path, monkeypatch, passing=True)
    assert chain.report["survivors"] and chain.report["ensemble"]["recipe"] and set(module.trial_specs(chain)) >= {"M0", "E"}
    assert chain.report["pbo"]["pbo"] == 0.1 and chain.report["spanning"] and chain.report["walkforward_pick"]["order"]
    assert (module.OUT_DIR / "stage1.json").exists() and (module.OUT_DIR / "walkforward_pick.json").exists()
    entries = module.candidate_entries(chain)
    assert "E" in entries and all(len(module.clauses_c0_c5(chain, entry)) == 6 for entry in entries.values())


def test_a_failing_grid_has_no_survivors_and_a_smoke_run_writes_no_side_files(world, monkeypatch):
    module, chain, tmp_path = world
    chain.args.smoke = True
    _run_to_verdict(module, chain, tmp_path, monkeypatch, passing=False)
    assert chain.report["survivors"] == [] and chain.report["ensemble"] == {"status": "no complete stage-2 candidate"} and not (module.OUT_DIR / "stage1.json").exists()
    assert chain.report["walkforward_pick"]["order"] == []


def test_missing_versions_are_named_and_a_pbo_needs_two_trials(world, monkeypatch):
    module, chain, tmp_path = world
    chain.report["priors"] = {}
    module.stage_stage1(chain)
    assert chain.report["stage1"]["M0"]["status"] == "missing"
    chain.report["survivors"] = ["M0"]
    chain.report["priors"] = {"rank_20d": {"identity_prior_ic": 0.0, "class_prior_ic": 0.0}}
    chain.report["installed_ic"] = {"rank_20d": {"validation": {"nonoverlap_mean_ic": 0.0}}}
    module.stage_stage2(chain)
    assert chain.report["stage2"]["M0"]["shipped_seed"] is None and chain.report["stage2"]["M0"]["c0"] is None
    module.stage_pbo(chain)
    assert chain.report["pbo"] == {"pbo": None, "reason": "fewer than 2 trials"}


def test_the_sixth_clause_reads_a_walk_forward_summary(world, tmp_path):
    module, chain, _ = world
    summary = tmp_path / "wf.json"
    summary.write_text(json.dumps({"run_id": "r", "num_windows": 5, "summary_by_metric": {"candidate_ic": {"cross_window_bootstrap": {"lower_bound": 0.01, "mean_ic": 0.03}}},
                                   "stability_by_metric": {"candidate_ic": {"sign_flip_fraction": 0.2}}}), encoding="utf-8")
    chain.args.wf_summary = str(summary)
    assert module.stage_c6(chain) == 0 and chain.report["c6"]["M1"]["passes"] is True
    summary.write_text(json.dumps({}), encoding="utf-8")
    assert module.stage_c6(chain) == 3


def _trend_stubs(monkeypatch, sharpe=0.5, drawdown=0.02):
    import evaluation.trend_sleeve_backtest as trend

    monkeypatch.setattr(trend, "load_daily_closes", lambda root, config, symbols: pd.DataFrame({"SPY": [1.0, 2.0]}))
    monkeypatch.setattr(trend, "trend_phase_summary", lambda closes, config, **kwargs: {"median_net_sharpe": sharpe, "median_max_drawdown": drawdown,
                                                                                      "daily_phase0": pd.Series({day: 0.001 * ((i % 3) - 1) for i, day in enumerate(research_fakes.DATES)})})


def test_the_trend_trials_choose_a_signal_and_the_main_book_is_scored_without_the_trend_symbols(world, monkeypatch):
    module, chain, _ = world
    _trend_stubs(monkeypatch)
    assert module.trend_config(chain.config, "sign_63").signal == "sign_63" and "commission_bps" in module.trend_kwargs(chain.config)
    assert module.trend_closes(chain) is module.trend_closes(chain)
    module.stage_trend(chain)
    assert chain.report["trend_choice"]["chosen"] == "T1" and chain.report["trend_choice"]["K2"] and chain.report["trend_choice"]["K3"]
    chain.args.smoke = False
    module.stage_trend(chain)
    assert set(chain.report["trend"]) == set(module.TREND_TRIALS)
    module.stage_trend_main(chain)
    assert {"K4", "K5"} <= set(chain.report["trend_choice"]) and set(chain.report["trend_main"]) == {"validation", "backtest"}
    assert module._sharpe([0.01]) == 0.0 and module._sharpe([0.01, 0.02, 0.0]) != 0.0


def test_the_holdout_is_read_for_a_passing_finalist_and_a_passing_trend_only(world, monkeypatch):
    module, chain, tmp_path = world
    _run_to_verdict(module, chain, tmp_path, monkeypatch, passing=True)
    _trend_stubs(monkeypatch)
    module.stage_holdout(chain)
    assert "model" not in chain.report["holdout"] and "trend" not in chain.report["holdout"]
    order = chain.report["walkforward_pick"]["order"]
    chain.report["c6"] = {name: {"passes": True} for name in order}
    chain.report["trend_choice"] = {"chosen": "T1", "K2": True, "K3": True, "K4": True, "K5": True}
    module.stage_holdout(chain)
    assert chain.report["holdout"]["model"]["finalist"] == order[0] and chain.report["holdout"]["trend"]["passes"] is True
    module.stage_holdout(chain)
    module.stage_verdict(chain)
    verdict = chain.report["verdict"]
    assert verdict["R-MODEL12"]["winner"] == order[0] and verdict["R-TREND1"]["passes"] is True


def test_the_verdict_without_a_holdout_has_no_winner(world, monkeypatch):
    module, chain, tmp_path = world
    _run_to_verdict(module, chain, tmp_path, monkeypatch, passing=True)
    module.stage_verdict(chain)
    assert chain.report["verdict"]["R-MODEL12"]["winner"] is None and chain.report["verdict"]["R-TREND1"]["passes"] is False


def test_the_command_runs_stages_and_reports_the_c6_status(world, monkeypatch):
    module, chain, tmp_path = world
    monkeypatch.setattr(module, "Chain644", lambda args: chain)
    monkeypatch.setitem(module.STAGES, "priors", lambda c: None)
    monkeypatch.setitem(module.STAGES, "c6", lambda c: 3)
    monkeypatch.setattr(sys, "argv", ["v644", "--stages", "priors", "c6", "--smoke"])
    assert module.main() == 3


def test_a_stage_two_entry_without_a_shipped_seed_is_no_candidate(world):
    module, chain, _ = world
    chain.report["stage2"] = {"M0": {"shipped_seed": None}}
    assert module.candidate_entries(chain) == {}
