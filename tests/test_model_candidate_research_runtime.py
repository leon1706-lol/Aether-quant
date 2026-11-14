"""scripts/model_candidate_research.py's runtime (V6.6.6, #359): the IC of a thin or full row set, the blended decision score, a kind's ensemble prediction, the
per-split scoring, the R-MODEL10 bootstrap and the whole command (with and without `--each-member` and `--bootstrap`)."""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd
import pytest

from script_loader import ROOT, load_script

DATES = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2021-09-01", periods=90)]
TICKERS = [f"T{n:02d}" for n in range(14)]


@pytest.fixture
def module(monkeypatch, tmp_path):
    research = load_script("model_candidate_research")
    monkeypatch.setattr(research, "ROOT_DIR", tmp_path)
    (tmp_path / "config.json").write_text((ROOT / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
    return research


def _frame():
    rng = np.random.default_rng(2)
    rows = []
    for index, date in enumerate(DATES):
        split = "validation" if index < 40 else ("backtest" if index < 70 else "holdout")
        for number, ticker in enumerate(TICKERS):
            row = {"date": date, "ticker": ticker, "split": split, "training_eligible": True, "in_main_group": number != 13}
            for head, (target, _) in {"rank_5d": ("target_rank_5d", 5), "rank_20d": ("target_rank_20d", 20), "sector_neutral_rank_20d": ("target_sector_neutral_rank_20d", 20),
                                      "residual_rank_5d": ("target_residual_rank_5d", 5), "residual_rank_20d": ("target_residual_rank_20d", 20)}.items():
                row[target] = rng.random()
            rows.append(row)
    return pd.DataFrame(rows)


def _heads(frame, seed):
    rng = np.random.default_rng(seed)
    return {head: rng.random(len(frame)) for head in ("rank_5d", "rank_20d", "sector_neutral_rank_20d", "residual_rank_5d", "residual_rank_20d")}


def test_a_candidate_text_names_its_member_directories_per_kind(module):
    assert module.parse_candidate("ctl=multitask:a,b;sequence:c") == ("ctl", {"multitask": ["a", "b"], "sequence": ["c"]})
    for bad in ("x=unknown:a", "=multitask:a", "x=multitask:", "x"):
        with pytest.raises(ValueError):
            module.parse_candidate(bad)


def test_the_ic_needs_fifty_rows_with_a_prediction_and_a_target(module):
    frame = _frame()
    thin = module.ic_stats(frame.iloc[:30], np.random.default_rng(1).random(30), "target_rank_20d", 20)
    assert thin == {"daily_mean_ic": None, "hac_t": None, "non_overlapping_mean_ic": None, "non_overlapping_t": None, "dates": 0}
    full = module.ic_stats(frame, np.random.default_rng(1).random(len(frame)), "target_rank_20d", 20)
    assert full["dates"] > 0 and full["daily_mean_ic"] is not None


def test_the_blend_takes_each_head_from_the_first_model_that_has_it(module):
    predictions = {"sequence": {"rank_20d": np.array([1.0, np.nan, np.nan])}, "multitask": {"rank_20d": np.array([3.0, 5.0, np.nan]), "rank_5d": np.array([2.0, 2.0, 2.0])}}
    heads = {"rank_20d": 1.0, "rank_5d": 1.0, "skipped": 0.0, "missing": 1.0}
    blended = module.blend_decision_score(predictions, heads, ["sequence", "multitask", "absent"])
    assert blended[0] == pytest.approx(1.5) and blended[1] == pytest.approx(3.5) and blended[2] == pytest.approx(2.0)
    assert np.isnan(module.blend_decision_score({"multitask": {"rank_20d": np.array([np.nan])}}, {"rank_20d": 1.0}, ["multitask"])[0])


def test_a_kinds_members_are_averaged_by_the_ensemble_predictor(module, monkeypatch, tmp_path):
    import evaluation.model_predictions as predictions

    for name in ("m0", "m1"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "sequence_model.json").write_text(json.dumps({"id": name}), encoding="utf-8")
    (tmp_path / "m0" / "sequence_feature_schema.json").write_text(json.dumps({"model_input_names": ["a"]}), encoding="utf-8")
    seen = {}
    monkeypatch.setattr(predictions, "predict_heads_ensemble", lambda frame, exports, names, heads, model_kind, sequence_feature_schema, configured_window_size, batched: seen.update(count=len(exports), kind=model_kind, schema=sequence_feature_schema) or {"rank_20d": [1]})
    assert module.predict_kind(None, ["m0", "m1"], "sequence", 30) == {"rank_20d": [1]} and seen["count"] == 2 and seen["schema"] == {"model_input_names": ["a"]}
    module.predict_kind(None, ["m0", "m1"], "sequence", 30)


def test_each_split_is_scored_for_the_decision_and_every_head(module):
    frame = _frame()
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    scored = module.score(frame, {"multitask": _heads(frame, 1), "sequence": _heads(frame, 2)}, config)
    assert set(scored) == {"validation", "backtest", "holdout"} and "multitask.rank_20d" in scored["validation"] and "decision_rank_20d_swapped_priority" in scored["backtest"]
    narrow = frame.drop(columns=["target_residual_rank_20d"])
    assert "multitask.residual_rank_20d" not in module.score(narrow, {"multitask": _heads(narrow, 1)}, config)["validation"]


def test_the_bootstrap_reports_the_spread_of_resampled_ensembles_and_a_floor_yardstick(module):
    frame = _frame()
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    members = {"multitask": [_heads(frame, seed) for seed in (1, 2, 3)], "sequence": [_heads(frame, 4)]}
    result = module.bootstrap_decision_ic(frame, members, config, runs=6)
    assert result["decision_rank_20d"]["runs"] > 0 and result["decision_rank_20d"]["yardstick"] >= 0.02
    single = module.bootstrap_decision_ic(frame.iloc[:20], {"multitask": [_heads(frame.iloc[:20], 1)]}, config, runs=2)
    assert single["decision_rank_20d"] == {"runs": 0, "mean": None, "std": 0.0, "yardstick": 0.02}


def _dataset(tmp_path):
    frame = _frame()
    frame.to_csv(tmp_path / "d.csv", index=False)
    return str(tmp_path / "d.csv")


@pytest.mark.parametrize("extra,keys", [([], {"dataset", "candidates"}), (["--each-member", "--bootstrap", "ctl", "--bootstrap-n", "4"], {"dataset", "candidates", "bootstrap"})])
def test_the_command_scores_every_candidate_and_optionally_each_member_and_the_bootstrap(module, monkeypatch, tmp_path, capsys, extra, keys):
    dataset = _dataset(tmp_path)
    calls = []
    monkeypatch.setattr(module, "predict_kind", lambda frame, dirs, kind, window: calls.append((kind, tuple(dirs))) or _heads(frame, len(calls)))
    out = tmp_path / "out" / "model_ic.json"
    monkeypatch.setattr(sys, "argv", ["model_candidate_research", "--dataset", dataset, "--candidate", "ctl=multitask:a,b;sequence:c", "--candidate", "other=multitask:d", "--out", str(out), *extra])
    assert module.main() == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert set(written) == keys and set(written["candidates"]) == {"ctl", "other"} and ("members_scored" in written["candidates"]["ctl"]) == bool(extra)
    if extra:
        assert set(written["candidates"]["ctl"]["members_scored"]) == {"a", "b", "c"} and written["bootstrap"]["candidate"] == "ctl"
