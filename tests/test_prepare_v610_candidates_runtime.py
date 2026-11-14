"""scripts/prepare_v610_candidates.py's runtime (V6.6.6, #359): a candidate directory with its ensembles, the latency ratio against the installed models, and the whole
`main()` for both rules (R-MODEL9 and R-MODEL10), in a temporary tree so no real `ml/versions` directory is touched."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from script_loader import ROOT, load_script

WEIGHTS = {"training": {"decision_threshold": 0.5}}


@pytest.fixture
def module(monkeypatch, tmp_path):
    prepare = load_script("prepare_v610_candidates")
    monkeypatch.setattr(prepare, "ROOT_DIR", tmp_path)
    (tmp_path / "ml").mkdir()
    (tmp_path / "ml" / "model_weights.json").write_text(json.dumps(WEIGHTS), encoding="utf-8")
    (tmp_path / "config.json").write_text((ROOT / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
    return prepare


def _member(tmp_path, name, *, status="promotable", metrics=True, kinds=("multitask", "sequence")):
    folder = tmp_path / "members" / name
    folder.mkdir(parents=True)
    for kind in kinds:
        model, schema, metric = {"multitask": ("multitask_model.json", "multitask_feature_schema.json", "multitask_training_metrics.json"),
                                 "sequence": ("sequence_model.json", "sequence_feature_schema.json", "sequence_training_metrics.json")}[kind]
        (folder / model).write_text(json.dumps({"kind": kind}), encoding="utf-8")
        (folder / schema).write_text(json.dumps({"model_input_names": ["a", "b"]}), encoding="utf-8")
        if metrics:
            quality = {head + "_ranking_quality": {"quality_status": status} for head in ("rank_5d", "rank_20d", "residual_rank_5d", "residual_rank_20d")}
            (folder / metric).write_text(json.dumps({"backtest": quality}), encoding="utf-8")
    return f"members/{name}"


def test_a_head_needs_at_least_half_of_its_members_to_rate_it_watchlist_or_better(module, tmp_path):
    good, bad = _member(tmp_path, "good"), _member(tmp_path, "bad", status="not_promotable")
    missing = _member(tmp_path, "missing", metrics=False)
    dirs = lambda *names: [tmp_path / name for name in names]  # noqa: E731
    assert module.head_status(dirs(good, bad), "multitask", "rank_20d") is True
    assert module.head_status(dirs(bad, missing), "multitask", "rank_20d") is False and module.head_status([], "multitask", "rank_20d") is False


def test_a_candidate_directory_holds_the_first_members_files_and_every_members_export(module, tmp_path):
    first, second = _member(tmp_path, "m0"), _member(tmp_path, "m1", metrics=False)
    target = module.build_candidate_dir("cand", {"multitask": [first, second]})
    (target / "stale.txt").write_text("old", encoding="utf-8")
    target = module.build_candidate_dir("cand", {"multitask": [first, second], "sequence": [second]})
    assert not (target / "stale.txt").exists() and (target / "model_weights.json").exists() and (target / "multitask_training_metrics.json").exists()
    assert sorted(path.name for path in (target / "multitask_ensemble").iterdir()) == ["member_00.json", "member_01.json"]
    assert (target / "sequence_ensemble" / "member_00.json").exists() and not (target / "sequence_training_metrics.json").exists()


def test_latency_is_the_candidates_forward_time_over_the_installed_models(module, tmp_path, monkeypatch):
    import evaluation.model_predictions as predictions

    for kind, schema in (("multitask", "multitask_feature_schema.json"), ("sequence", "sequence_feature_schema.json")):
        (tmp_path / "ml" / f"{kind}_model.json").write_text("{}", encoding="utf-8")
        (tmp_path / "ml" / schema).write_text(json.dumps({"model_input_names": ["a"]}), encoding="utf-8")
    members = {"multitask": [_member(tmp_path, "m0"), _member(tmp_path, "m1")], "sequence": [_member(tmp_path, "m2")]}
    seen = []
    monkeypatch.setattr(predictions, "predict_heads_ensemble", lambda frame, exports, names, heads, model_kind, sequence_feature_schema, configured_window_size, batched: seen.append((model_kind, len(exports))))
    assert module.latency_ratio(members, None, 30) > 0.0 and ("multitask", 2) in seen and ("sequence", 1) in seen
    monkeypatch.setattr(module, "time", SimpleNamespace(perf_counter=lambda: 1.0))
    assert module.latency_ratio(members, None, 30) == 1.0


def _main_world(module, monkeypatch, tmp_path, *, ic_by_name):
    import v610_research
    import v620_research

    good, other = _member(tmp_path, "good"), _member(tmp_path, "other", status="not_promotable")
    (tmp_path / "ml" / "multitask_training_metrics.json").write_text(json.dumps({"backtest": {"sector_neutral_rank_20d_ranking_quality": {"quality_status": "watchlist"}}}), encoding="utf-8")
    model_ic = {"candidates": {"installed": {"members": {}}, "cand_pass": {"members": {"multitask": [good, good], "sequence": [good]}},
                               "cand_fail": {"members": {"multitask": [other]}}, "cand_empty": {"members": {"multitask": [other]}}}}
    (tmp_path / "model_ic.json").write_text(json.dumps(model_ic), encoding="utf-8")
    (tmp_path / "validation.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    monkeypatch.setattr(v610_research, "model_ic_checks", lambda ic, name: ic_by_name[name])
    monkeypatch.setattr(v620_research, "model10_checks", lambda ic, name: ic_by_name[name])
    monkeypatch.setattr(module, "latency_ratio", lambda members, frame, window: 1.2)


def _argv(tmp_path, *extra):
    return ["prepare", "--model-ic", str(tmp_path / "model_ic.json"), "--dataset", str(tmp_path / "validation.csv"), "--out", str(tmp_path / "out" / "candidates.json"), *extra]


@pytest.mark.parametrize("rule,extra", [("r-model9", []), ("r-model10", ["--rule", "r-model10", "--prefix", "v620_cand_"])])
def test_only_a_candidate_whose_ic_clauses_pass_gets_a_directory(module, monkeypatch, tmp_path, rule, extra):
    ic = {"installed": {}, "cand_pass": {"c1": True, "c2": True, "yardstick": 0.0}, "cand_fail": {"c1": True, "c2": False}, "cand_empty": {}}
    _main_world(module, monkeypatch, tmp_path, ic_by_name=ic)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, *extra))
    assert module.main() == 0
    written = json.loads((tmp_path / "out" / "candidates.json").read_text(encoding="utf-8"))
    prefix = "v620_cand_" if extra else "v610_cand_"
    assert written["installed"]["decision_heads_pass_r_head"] is True and "sector_neutral_rank_20d" in written["installed"]["passing_heads"]
    assert written["cand_pass"]["ic_pass"] is True and written["cand_pass"]["ml_dir"] == f"ml/versions/{prefix}cand_pass" and written["cand_pass"]["ensemble"] is True and written["cand_pass"]["latency_ratio"] == 1.2
    assert written["cand_fail"]["ic_pass"] is False and "ml_dir" not in written["cand_fail"] and written["cand_empty"]["ic_pass"] is False
    assert written["cand_pass"]["decision_heads_pass_r_head"] in (True, False) and rule
