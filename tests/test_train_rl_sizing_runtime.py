"""train_rl_sizing's `main()` and row builders end to end on synthetic datasets (V6.6.6, #359): the daily bandit with and without a penalty sweep, the book-level policy for the forex pool and a
non-forex pool with and without a holdout, every way a run skips, the rows each builder drops, and the failure exit code. The multitask replay is stubbed (it needs a real export)."""

from __future__ import annotations

import datetime
import json
import runpy
import sys

import numpy as np
import pandas as pd
import pytest

import train_rl_sizing as rl
from risk.rl_sizing import FOREX_RL_SIZING_STATE_KEYS

STATE = {"rolling_volatility_20d": 0.02, "regime_signal_risk_score": 0.3, "topology_correlation_strength": 0.5, "liquidity_spread_proxy": 0.0005, "bond_credit_spread_level": 0.9,
         "alt_implied_volatility_level": 18.0, "alt_implied_vol_term_structure": 1.05, "alt_financial_conditions_change": -0.2, "regime_trend_bullish": 0.0, "regime_trend_bearish": 0.0,
         "regime_trend_sideways": 1.0, "fx_carry_3m": 0.1}


def make_frame(tickers, dates, seed=0, split=None):
    rng = np.random.default_rng(seed)
    start = datetime.date(2019, 1, 1)
    rows = []
    for ticker_index, ticker in enumerate(tickers):
        for day in range(dates):
            risk = float(rng.normal(0.3, 0.2))
            row = {"ticker": ticker, "date": (start + datetime.timedelta(days=day)).isoformat(), "f0": float(ticker_index), "confidence": 0.5,
                   "target_return_1d": float(rng.normal(0.0, 0.01) - 0.05 * (risk - 0.3)), "target_return_20d": float(rng.normal(0.002 * (ticker_index - len(tickers) / 2), 0.02)), **STATE}
            row["regime_signal_risk_score"] = risk
            if split:
                row["split"] = split
            rows.append(row)
    return pd.DataFrame(rows)


@pytest.fixture(autouse=True)
def stub_model(monkeypatch):
    monkeypatch.setattr(rl, "run_exported_multitask_model", lambda export, inputs: {"rank_20d": min(1.0, max(0.0, 0.5 + inputs[0] / 20.0))})


def world(monkeypatch, tmp_path, *, training=None, tickers=("AAA", "BBB", "CCC", "DDD"), dates=40, with_model=True, with_schema=True, with_backtest=True, holdout=False, asset_class="equity", args=()):
    ml = tmp_path / "ml"
    data = ml / "datasets"
    data.mkdir(parents=True)
    config = {"phase_v2": {"rl_sizing": {"training": {"min_training_rows": 20, "epochs": 5, **(training or {})}}, "costs": {"commission_bps_per_side": 0.2, "min_commission_usd": 2.0},
                           "liquidity": {"max_spread_proxy_by_type": {"forex": 0.01, "equity": 0.05}}},
              "phase1": {"universe": {"assets": [{"ticker": t, "security_type": "forex" if asset_class == "forex" else "equity", "asset_class": asset_class} for t in tickers]}}, "runtime": {"initial_cash": 100000}}
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    make_frame(tickers, dates, 1).to_csv(data / "validation_dataset.csv", index=False)
    if with_backtest:
        make_frame(tickers, dates, 2).to_csv(data / "backtest_dataset.csv", index=False)
    if holdout:
        make_frame(tickers, dates, 3, split="backtest").to_csv(data / "holdout_dataset.csv", index=False)
    if with_schema:
        (ml / "feature_schema.json").write_text(json.dumps({"model_input_names": ["f0"]}), encoding="utf-8")
    if with_model:
        (ml / "multitask_model.json").write_text(json.dumps({"export": {}}), encoding="utf-8")
    monkeypatch.setattr(rl, "ML_DIR", ml)
    monkeypatch.setattr(rl, "FEATURE_SCHEMA_PATH", ml / "feature_schema.json")
    original = rl.load_multitask_export  # its default path is bound when the module loads
    monkeypatch.setattr(rl, "load_multitask_export", lambda path=ml / "multitask_model.json": original(path))
    monkeypatch.setattr(sys, "argv", ["train_rl_sizing", "--version-id", "r1", "--config-path", str(tmp_path / "config.json"), "--dataset-dir", str(data), *args])
    return ml / "versions" / "r1"


def test_the_daily_policy_trains_and_writes_a_verdict_against_the_constant_action(monkeypatch, tmp_path):
    version = world(monkeypatch, tmp_path)
    assert rl.main() == 0
    metrics = json.loads((version / "rl_sizing_training_metrics.json").read_text(encoding="utf-8"))
    assert metrics["training_rows"] > 0 and metrics["policy_beats_constant_unpenalized"] in (True, False) and (version / "rl_sizing_model.json").exists()


def test_the_penalty_sweep_picks_a_weight_on_a_chronological_holdout(monkeypatch, tmp_path):
    version = world(monkeypatch, tmp_path, tickers=("AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH"), dates=260, args=("--penalty-sweep", "1.0,2.0"))
    assert rl.main() == 0
    sweep = json.loads((version / "rl_sizing_training_metrics.json").read_text(encoding="utf-8"))["penalty_sweep"]
    assert sweep["reason"] == "selected_by_holdout_margin" and len(sweep["table"]) == 2
    world(monkeypatch, tmp_path / "config_sweep", training={"penalty_sweep": [1.0, 3.0]}, dates=30)
    assert rl.main() == 0


def test_a_backtest_with_no_usable_rows_still_writes_a_training_only_verdict(monkeypatch, tmp_path):
    version = world(monkeypatch, tmp_path)
    path = tmp_path / "ml" / "datasets" / "backtest_dataset.csv"
    frame = pd.read_csv(path)
    frame["target_return_1d"] = np.nan
    frame.to_csv(path, index=False)
    assert rl.main() == 0
    metrics = json.loads((version / "rl_sizing_training_metrics.json").read_text(encoding="utf-8"))
    assert metrics["backtest_rows"] == 0 and metrics["policy_beats_constant_unpenalized"] is None


def test_every_way_the_daily_policy_skips_writes_nothing(monkeypatch, tmp_path):
    for index, kwargs in enumerate(({"with_model": False}, {"with_schema": False}, {"with_backtest": False}, {"training": {"min_training_rows": 10**9}})):
        version = world(monkeypatch, tmp_path / f"s{index}", **kwargs)
        assert rl.main() == 0 and not version.exists()


def test_the_book_policy_trains_on_the_forex_pool_and_is_judged_on_backtest_and_holdout(monkeypatch, tmp_path):
    tickers = tuple(f"F{i}" for i in range(8))
    training = {"reward_mode": "book_member_20d", "book_pool_classes": ["forex"], "book_per_side": 2, "book_rebalance_every": 1, "book_min_training_rows": 20, "epochs": 5, "action_set": [0.0, 1.0, 1.5]}
    version = world(monkeypatch, tmp_path, training=training, tickers=tickers, asset_class="forex", holdout=True)
    assert rl.main() == 0
    metrics = json.loads((version / "rl_sizing_forex_training_metrics.json").read_text(encoding="utf-8"))
    assert set(metrics["judged"]) == {"backtest", "holdout"} and metrics["policy_beats_constant_unpenalized"] in (True, False) and (version / "rl_sizing_forex_model.json").exists()


def test_the_book_policy_for_another_class_writes_the_generic_names_and_skips_a_split_with_no_rows(monkeypatch, tmp_path):
    tickers = tuple(f"E{i}" for i in range(14))
    training = {"reward_mode": "book_member_20d", "book_pool_classes": ["equity"], "book_rebalance_every": 1, "book_min_training_rows": 20, "epochs": 3, "action_set": [0.0, 1.0]}
    version = world(monkeypatch, tmp_path, training=training, tickers=tickers, dates=10)
    path = tmp_path / "ml" / "datasets" / "backtest_dataset.csv"
    frame = pd.read_csv(path)
    frame["target_return_20d"] = np.nan
    frame.to_csv(path, index=False)
    assert rl.main() == 0
    metrics = json.loads((version / "rl_sizing_training_metrics.json").read_text(encoding="utf-8"))
    assert metrics["judged"] == {} and metrics["policy_beats_constant_unpenalized"] is False


def test_the_book_policy_skips_without_inputs_or_without_enough_rows(monkeypatch, tmp_path):
    tickers = tuple(f"F{i}" for i in range(8))
    training = {"reward_mode": "book_member_20d", "book_pool_classes": ["forex"], "book_per_side": 2, "book_rebalance_every": 1, "epochs": 3}
    version = world(monkeypatch, tmp_path / "nomodel", training=training, tickers=tickers, asset_class="forex", with_model=False)
    assert rl.main() == 0 and not version.exists()
    version = world(monkeypatch, tmp_path / "few", training={**training, "book_min_training_rows": 10**9}, tickers=tickers, asset_class="forex")
    assert rl.main() == 0 and not version.exists()


def test_a_penalty_sweep_reports_each_way_it_cannot_score_a_candidate():
    frame = make_frame(("AAA", "BBB"), 30)
    common = dict(model_input_names=["f0"], action_set=[0.6, 1.0], turnover_cost_bps_column="liquidity_spread_proxy", commission_bps=0.0, nominal_base_weight=0.05)
    few_fit = rl.select_penalty_weight(frame, {}, candidate_weights=[2.0], **common)
    assert few_fit["reason"] == "no_candidate_had_enough_rows" and few_fit["table"][0]["skipped"] == "too_few_fit_rows"
    empty_holdout = rl.select_penalty_weight(frame.assign(target_return_1d=np.nan), {}, candidate_weights=[2.0], **common)
    assert empty_holdout["reason"] == "empty_holdout"


def test_rows_with_a_gap_a_failed_replay_or_no_rank_are_dropped_by_both_builders(monkeypatch):
    frame = make_frame(("AAA", "BBB"), 12)
    common = dict(model_input_names=["f0"], action_set=[0.0, 1.0], turnover_cost_bps_column="liquidity_spread_proxy", commission_bps=0.0, nominal_base_weight=0.05)
    states, _ = rl.build_bandit_rows(frame.drop(columns=["regime_signal_risk_score"]), {}, **common)
    assert len(states) == 0
    assert len(rl.build_bandit_rows(frame.rename(columns={"f0": "g0"}), {}, **common)[0]) == 0

    def failing(export, inputs):
        raise RuntimeError("bad export")

    monkeypatch.setattr(rl, "run_exported_multitask_model", failing)
    assert len(rl.build_bandit_rows(frame, {}, **common)[0]) == 0
    monkeypatch.setattr(rl, "run_exported_multitask_model", lambda export, inputs: {})
    assert len(rl.build_bandit_rows(frame, {}, **common)[0]) == 0

    book = dict(asset_class_by_ticker={t: "forex" for t in ("AAA", "BBB")}, pool_classes=["forex"], per_side=0, rebalance_every=1, nominal_base_weight=0.02, nav=100000.0, costs_config={})
    keys = list(FOREX_RL_SIZING_STATE_KEYS)
    args = ({}, ["f0"], [0.0, 1.0], keys)
    monkeypatch.setattr(rl, "run_exported_multitask_model", failing)
    assert rl.build_book_member_rows(frame, *args, **book)[0].shape[0] == 0
    monkeypatch.setattr(rl, "run_exported_multitask_model", lambda export, inputs: {})
    assert rl.build_book_member_rows(frame, *args, **book)[0].shape[0] == 0
    monkeypatch.setattr(rl, "run_exported_multitask_model", lambda export, inputs: {"rank_20d": inputs[0] / 10.0})
    assert rl.build_book_member_rows(frame.assign(f0=np.nan), *args, **book)[0].shape[0] == 0
    assert rl.build_book_member_rows(frame.assign(fx_carry_3m=np.nan), *args, **book)[0].shape[0] == 0
    assert rl.build_book_member_rows(frame.assign(target_return_20d=np.nan), *args, **book)[0].shape[0] == 0


def test_the_export_loader_returns_none_for_a_missing_or_corrupt_file_and_the_config_and_paths_resolve(monkeypatch, tmp_path):
    assert rl.load_multitask_export(tmp_path / "none.json") is None
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    assert rl.load_multitask_export(tmp_path / "bad.json") is None
    (tmp_path / "good.json").write_text(json.dumps({"export": {}}), encoding="utf-8")
    assert rl.load_multitask_export(tmp_path / "good.json") == {"export": {}}
    (tmp_path / "config.json").write_text(json.dumps({"phase_v2": {"rl_sizing": {"training": {"epochs": 7}}}}), encoding="utf-8")
    assert rl.load_rl_sizing_training_config(tmp_path / "config.json") == {"epochs": 7}
    monkeypatch.setattr(rl, "ML_DIR", tmp_path / "ml")
    assert rl.rl_sizing_candidate_output_paths("v")["rl_sizing_model"] == tmp_path / "ml" / "versions" / "v" / "rl_sizing_model.json"


def test_a_failure_is_an_exit_code_and_the_script_runs_as_main(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["train_rl_sizing", "--version-id", "r9", "--config-path", str(tmp_path / "missing.json")])
    assert rl.main() == 1
    with pytest.raises(SystemExit) as stop:
        runpy.run_path(str(rl.__file__), run_name="__main__")
    assert stop.value.code == 1
