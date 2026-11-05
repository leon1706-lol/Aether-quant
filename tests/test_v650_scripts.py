"""The V6.5.0 research scripts: the guards that keep selection off later data, the rule-hash check, the trial list, the recipe and the ML score tables."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


research = _load("v650_research")
recipe = _load("v650_make_recipe")
scores = _load("v650_ml_scores")
trials = _load("v650_trials")


def test_pre2013_sharpe_uses_the_runs_own_observations_per_year():
    amendment = _load("v650_amendment2")
    rng = np.random.default_rng(1)
    days = pd.bdate_range("2005-01-03", periods=1500).strftime("%Y-%m-%d")
    series = pd.Series(rng.normal(0.0005, 0.01, 1500), index=days)

    # weekdays only: about 261 observations a year, so a fixed 365 would inflate this Sharpe by about 18%
    assert amendment.per_year(series) == pytest.approx(261, abs=2)
    expected = series.mean() / series.std(ddof=1) * np.sqrt(amendment.per_year(series))
    assert amendment.sharpe_on_observations(series) == pytest.approx(expected)
    assert amendment.sharpe_on_observations(series.iloc[:5]) is None


def test_correlated_earnings_sleeves_keep_only_the_higher_sharpe():
    amendment = _load("v650_amendment2")
    rng = np.random.default_rng(2)
    base = rng.normal(size=300)
    daily = pd.DataFrame({"a": base, "b": base + rng.normal(scale=0.1, size=300), "c": rng.normal(size=300)})
    scores = {"a": {"sharpe": 0.5}, "b": {"sharpe": 0.9}, "c": {"sharpe": 0.1}}

    assert amendment.apply_correlation_clause(["a", "b", "c"], scores, daily) == ["b", "c"]
    assert amendment.apply_correlation_clause([], scores, daily) == []


def test_the_earnings_trials_are_the_amendments_and_outside_the_hashed_list():
    amendment = _load("v650_amendment2")
    assert [spec.id for spec in amendment.EPS_SPECS] == ["t4_eps_sue_20", "t4_eps_sue_60"]
    assert not {spec.id for spec in amendment.EPS_SPECS} & {spec.id for spec in trials.ALL_SPECS}


def test_selection_guard_refuses_anything_past_the_selection_end():
    research.assert_selection_only("2023-06-30")
    with pytest.raises(SystemExit, match="past the selection window"):
        research.assert_selection_only("2023-07-01")


def test_a_changed_rule_file_stops_every_stage(tmp_path, monkeypatch):
    text = '{"a": 1}'
    (tmp_path / "rules.json").write_text(text, encoding="utf-8")
    (tmp_path / "rules.sha256").write_text(hashlib.sha256(text.encode()).hexdigest() + "\n", encoding="utf-8")
    monkeypatch.setattr(research, "OUT", tmp_path)
    assert research.check_rules() == {"a": 1}

    (tmp_path / "rules.json").write_text('{"a": 2}', encoding="utf-8")
    with pytest.raises(SystemExit, match="rules.json changed"):
        research.check_rules()


def test_ml_and_model_sleeves_use_their_own_selection_window():
    rules = {"selection_windows": {"rule_sleeves": ["2014-12-01", "2019-03-15", "2023-06-30"], "ml_sleeves": ["2019-01-01", "2021-04-01", "2023-06-30"]}}
    by_id = {spec.id: spec for spec in trials.ALL_SPECS}
    assert research.window_of(by_id["t3_fx_carry"], rules)[0] == "2014-12-01"
    assert research.window_of(by_id["t2_a1_20_top6"], rules)[0] == "2019-01-01"
    assert research.window_of(by_id["t5_st_a"], rules)[0] == "2019-01-01"


def test_trial_ids_are_unique_and_inside_the_budget():
    ids = [spec.id for spec in trials.ALL_SPECS]
    assert len(ids) == len(set(ids))
    assert len(ids) + len(trials.ABLATION_IDS) + len(trials.COMBINATION_IDS) <= 60


def test_rule_file_lists_every_trial():
    rules = json.loads((ROOT / "ml" / "evaluation" / "v650" / "rules.json").read_text(encoding="utf-8")) if (ROOT / "ml" / "evaluation" / "v650" / "rules.json").exists() else None
    if rules is None:
        pytest.skip("rules.json is under gitignored ml/")
    assert {entry["id"] for entry in rules["trials"]["sleeves"]} == {spec.id for spec in trials.ALL_SPECS}


def test_recipe_stops_before_the_verification_data_and_uses_asof_labels():
    base = {
        "phase1": {"target": {"ranking": {"beta_estimation": "full_history"}}, "universe": {"common_window": {"start": "2014-12-01", "end": "2025-06-30"}}},
        "phase_v2": {"retraining": {"walk_forward": {"net_performance": True}}},
    }
    config = recipe.recipe(base, end="2023-11-30")

    assert config["phase1"]["target"]["ranking"]["beta_estimation"] == "asof"
    assert config["phase1"]["universe"]["common_window"]["end"] == "2023-11-30"
    assert config["phase_v2"]["retraining"]["walk_forward"]["net_performance"] is False
    assert base["phase1"]["target"]["ranking"]["beta_estimation"] == "full_history"


def _window_dir(tmp_path, *, split_dates):
    rows = []
    for ticker in ("A", "B", "C"):
        for date, split in split_dates:
            rows.append({"date": date, "ticker": ticker, "split": split})
    window = tmp_path / "window_0"
    window.mkdir()
    pd.DataFrame(rows).to_csv(window / "full_dataset.csv", index=False)
    return window


def test_score_tables_cover_only_the_windows_backtest_split_up_to_the_end(tmp_path, monkeypatch):
    window = _window_dir(tmp_path, split_dates=[("2022-01-03", "training"), ("2023-06-30", "backtest"), ("2023-07-03", "backtest")])

    def heads(window_dir, frame, mask, kind, sequence_window):
        values = np.arange(len(frame), dtype=float)
        return {head: values for head in scores.HEADS}

    monkeypatch.setattr(scores, "window_heads", heads)
    tables = scores.tables_for_window(window, end="2023-06-30", sequence_window=30)

    assert set(tables) == {"ml_a1", "ml_a2", "ml_a3"}
    for table in tables.values():
        assert set(table["date"]) == {"2023-06-30"}
        assert len(table) == 3


def test_score_tables_skip_a_model_this_window_did_not_train(tmp_path, monkeypatch):
    window = _window_dir(tmp_path, split_dates=[("2023-06-30", "backtest")])
    monkeypatch.setattr(scores, "window_heads", lambda d, f, m, kind, w: None if kind == "sequence" else {h: np.ones(len(f)) for h in scores.HEADS})

    assert set(scores.tables_for_window(window, end="2023-06-30", sequence_window=30)) == {"ml_a2"}


def test_blend_is_of_daily_ranks_so_head_scales_do_not_matter():
    frame = pd.DataFrame({"date": ["d", "d", "d"]})
    assert scores.daily_rank(frame, np.array([1.0, 100.0, 1000.0])).tolist() == pytest.approx([1 / 3, 2 / 3, 1.0])
