"""aq evaluate's dataset and model flows (V6.6.6, #359): the idealized and as-live rank books, Monte Carlo, benchmarks, capacity, stress
and calibration, with the simulator and the model stubbed. The test checks the wiring: what is run, what is printed, what is written."""

from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import aq_cli
from test_aq_cli_evaluate_lean import env, ns  # noqa: F401  (the fixture and the namespace builder)


def _result(sharpe=0.4):
    return SimpleNamespace(
        gross_sharpe=0.6, net_sharpe=sharpe, gross_total_return=0.1, net_total_return=0.08, net_max_drawdown=-0.05, annualized_turnover=3.0, cost_drag_annual_bps=12.0,
        num_rebalances=5, num_dates_used=100, mean_names_long=4.0, mean_names_short=0.0, num_vetoed_rebalances=1, veto_reasons={"gate": 1},
        per_date=["2025-01-02", "2025-01-03"], per_date_net_return=[0.001, -0.002], to_dict=lambda: {"net_sharpe": sharpe},
    )


@pytest.fixture
def book(env, monkeypatch):
    import evaluation

    dataset = pd.DataFrame({
        "date": ["2025-01-02", "2025-01-03"] * 2, "ticker": ["AAA"] * 2 + ["BBB"] * 2, "split": "backtest", "training_eligible": [True, True, True, False],
        "target_return_1d": [0.01, -0.01, 0.02, 0.0], "target_return_20d": [0.05, -0.05, 0.1, 0.0], "target_direction_20d": [1, 0, 1, 0],
    })
    dataset.to_csv(env.root / "full.csv", index=False)
    (env.root / "ml" / "sequence_model.json").write_text("{}", encoding="utf-8")
    (env.root / "ml" / "sequence_feature_schema.json").write_text(json.dumps({"model_input_names": ["x"]}), encoding="utf-8")
    runs = []
    monkeypatch.setattr(evaluation, "predict_head", lambda frame, export, names, head, **kwargs: np.full(len(frame), 0.7))
    monkeypatch.setattr(evaluation, "simulate_rank_book", lambda frame, **kwargs: runs.append(kwargs) or _result(0.5 if "live_rank_score" in str(kwargs.get("prediction_column")) else 0.4))
    monkeypatch.setattr(evaluation, "capacity_curve", lambda frame, participation_cap, base_kwargs, top_n_sweep: {"capacity_usd": 5e6, "binding_ticker": "AAA", "per_top_n": [{"top_n": 3, "net_sharpe": 0.3}]})
    monkeypatch.setattr(evaluation, "stress_test_costs", lambda frame, base_kwargs, cost_multipliers: [{"cost_multiplier": m, "net_sharpe": 0.2, "net_total_return": 0.01} for m in cost_multipliers])
    defaults = dict(dataset=str(env.root / "full.csv"), model=None, head=None, split=None, rank_book=False, all=False, capacity=False, stress=False, calibrate_edge=False)
    return SimpleNamespace(runs=runs, args=lambda **flags: ns(**{**defaults, **flags}))


def test_missing_configuration_dataset_model_or_rows_stop_the_run(env, book, monkeypatch, capsys):
    config = json.loads((env.root / "config.json").read_text(encoding="utf-8"))
    config["phase1"]["target"]["ranking"]["net_performance"] = {}
    (env.root / "config.json").write_text(json.dumps(config), encoding="utf-8")
    assert aq_cli.cmd_evaluate(book.args()) == 1 and "net_performance is not configured" in capsys.readouterr().err
    config["phase1"]["target"]["ranking"]["net_performance"] = {"top_n": 2}
    (env.root / "config.json").write_text(json.dumps(config), encoding="utf-8")
    assert aq_cli.cmd_evaluate(ns(dataset=str(env.root / "gone.csv"), model=None, head=None, split=None, rank_book=False, all=False, capacity=False, stress=False, calibrate_edge=False)) == 1
    (env.root / "ml" / "sequence_model.json").unlink()
    assert aq_cli.cmd_evaluate(book.args()) == 1 and "aq train" in capsys.readouterr().err
    (env.root / "ml" / "sequence_model.json").write_text("{}", encoding="utf-8")
    assert aq_cli.cmd_evaluate(book.args(rank_book=True)) == 0
    pd.DataFrame({"date": ["2025-01-02"], "ticker": ["A"], "split": ["train"]}).to_csv(env.root / "empty.csv", index=False)
    empty = book.args()
    empty.dataset = str(env.root / "empty.csv")
    assert aq_cli.cmd_evaluate(empty) == 1 and "no rows for split" in capsys.readouterr().err


def test_the_rank_book_runs_with_and_without_the_one_bar_lag_and_the_monte_carlo(env, book, monkeypatch, capsys):
    import evaluation.monte_carlo as monte_carlo

    ok = {"status": "OK", "runs_curves": np.ones((2, 3)), "config": {"n_runs": 2, "method": "block", "block_size": 20, "seed": 42}, "final_return_pct": {"p5": -1, "p50": 2, "p95": 5},
          "max_drawdown": {"p95": 9}, "sharpe": {"p5": -0.1, "p95": 1.2}, "prob_negative_return": 0.2}
    answers = iter([ok, {"status": "TOO_SHORT"}])
    monkeypatch.setattr(monte_carlo, "run_monte_carlo", lambda returns, **kwargs: dict(next(answers)))
    assert aq_cli.cmd_evaluate(book.args(rank_book=True, monte_carlo=True)) == 0
    text = capsys.readouterr().out
    assert "Rank book (sequence/rank_20d" in text and "lag tax" in text and "Monte Carlo (OK): 2 runs" in text and (env.out / "monte_carlo_curves.npz").exists()
    assert aq_cli.cmd_evaluate(book.args(monte_carlo=True)) == 0 and "Monte Carlo TOO_SHORT" in capsys.readouterr().out
    assert aq_cli.cmd_evaluate(argparse.Namespace(**{**vars(book.args(rank_book=True)), "json": True})) == 0
    assert "Rank book" not in capsys.readouterr().out
    assert (env.out / "rank_book_simulation_entry_lag_1_sequence.json").exists()


def test_the_default_run_is_the_rank_book_and_classification_needs_its_target(env, book, monkeypatch, capsys):
    import evaluation.backtest_statistics as statistics

    assert aq_cli.cmd_evaluate(book.args()) == 0 and "Rank book" in capsys.readouterr().out
    monkeypatch.setattr(statistics, "classification_scores", lambda labels, predicted, probability: {"n": 3, "accuracy": 0.67, "f1": 0.5, "neg_log_loss": -0.6})
    assert aq_cli.cmd_evaluate(book.args(classification=True)) == 0
    assert "Classification (sequence direction_20d" in capsys.readouterr().out and (env.out / "classification_scores_sequence.json").exists()
    frame = pd.read_csv(env.root / "full.csv").drop(columns=["target_direction_20d"])
    frame.to_csv(env.root / "full.csv", index=False)
    assert aq_cli.cmd_evaluate(book.args(classification=True)) == 0 and "classification scores skipped" in capsys.readouterr().err


def test_capacity_stress_and_the_edge_calibration(env, book, capsys):
    assert aq_cli.cmd_evaluate(book.args(capacity=True, stress=True, calibrate_edge=True)) == 0
    text = capsys.readouterr().out
    assert "Capacity: $5,000,000 (binding: AAA)" in text and "Cost stress test" in text and "Calibrated edge_bps_per_rank_unit (target_return_20d)" in text
    frame = pd.read_csv(env.root / "full.csv").drop(columns=["target_return_20d"])
    frame.to_csv(env.root / "full.csv", index=False)
    assert aq_cli.cmd_evaluate(book.args(calibrate_edge=True)) == 0 and "falling back to target_return_1d" in capsys.readouterr().err


def test_the_as_live_book_is_run_beside_the_idealized_one(env, book, monkeypatch, capsys):
    import evaluation.live_parity as parity

    monkeypatch.setattr(aq_cli, "_blend_raw_scores_for_dataset", lambda frame, config, window: ([0.5] * len(frame), {"heads": {"rank_20d": 1.0}, "model_priority": ["sequence"], "demoted": []}))
    monkeypatch.setattr(aq_cli, "_core_quality_tickers", lambda: set())
    monkeypatch.setattr(parity, "build_as_live_kwargs", lambda base, **kwargs: dict(base, prediction_column="live_rank_score"))
    monkeypatch.setattr(parity, "build_live_mechanisms", lambda config, frame, core_crypto_tickers: {})
    monkeypatch.setattr(parity, "load_live_venue_listing_dates", lambda config, root: {})
    gates = []
    monkeypatch.setattr(parity, "make_rolling_ic_gate_fn", lambda frame, **kwargs: gates.append(kwargs) or (lambda date: None))
    config = json.loads((env.root / "config.json").read_text(encoding="utf-8"))
    config["phase_v2"]["rolling_ic_gate"] = {"enabled": True}
    config["phase_v2"]["costs"]["impact_model"] = {"eta": 0.5}
    (env.root / "config.json").write_text(json.dumps(config), encoding="utf-8")
    assert aq_cli.cmd_evaluate(book.args(as_live=True)) == 0
    text = capsys.readouterr().out
    assert "Rank book AS-LIVE" in text and "with Almgren impact model" in text and gates and (env.out / "rank_book_simulation_as_live_backtest.json").exists()
    assert len(book.runs) >= 3, "the idealized run, the as-live run and the impact run"
    config["phase_v2"]["rolling_ic_gate"] = {"enabled": False}
    config["phase_v2"]["costs"].pop("impact_model")
    (env.root / "config.json").write_text(json.dumps(config), encoding="utf-8")
    assert aq_cli.cmd_evaluate(book.args(as_live=True, rank_book=True, split="all")) == 0
    assert "Almgren" not in capsys.readouterr().out.split("Rank book AS-LIVE")[-1]


def test_factor_exposure_volatility_benchmarks_replay_and_limit_fills(env, book, monkeypatch, capsys):
    import evaluation.benchmark_comparison as benchmark
    import evaluation.factor_neutralization_check as factor
    import evaluation.kill_switch_replay as replay
    import evaluation.limit_fill_simulator as limits
    import evaluation.volatility_threshold_calibration as volatility

    monkeypatch.setattr(benchmark, "close_pivot_from_frame", lambda frame: pd.DataFrame({"AAA": [1.0, 2.0]}))
    monkeypatch.setattr(benchmark, "run_all_baselines", lambda pivot: {"baselines": [{"strategy": "spy", "net_sharpe": 0.3, "total_return_pct": 10.0}, {"strategy": "bonds", "net_sharpe": None, "total_return_pct": 1.0, "status": "SKIPPED"}]})
    answers = iter([
        {"status": "OK", "n_obs": 50, "market_ticker": "SPY", "total_sharpe": 0.4, "alpha_sharpe": 0.1, "r_squared": 0.5, "loadings": {"mkt": 0.9}, "factor_contribution_pct": {"mkt": 80}},
        {"status": "SKIPPED", "reason": "no SPY"},
    ])
    monkeypatch.setattr(factor, "compute_book_factor_exposure", lambda per_date, returns, pivot: next(answers))
    volatility_answers = iter([{"status": "OK", "by_asset_class": {"equity": {"p80": 0.4}}, "suggested_config": {"default": 0.45}}, {"status": "SKIPPED", "reason": "no data"}])
    monkeypatch.setattr(volatility, "calibrate_elevated_volatility_thresholds", lambda dataset, classes, percentile, current_default: next(volatility_answers))
    monkeypatch.setattr(replay, "replay_kill_switch_over_dataset", lambda per_date, returns, config, max_daily_drawdown_pct, max_total_drawdown_pct: [{"date": "2025-01-02"}])
    monkeypatch.setattr(replay, "summarize_kill_switch_replay", lambda records: {"trip_count": 1, "total_dates": 2, "locked_days": 1, "locked_day_fraction": 0.5})
    overall = {"fill_rate": 0.7, "timeout_rate": 0.1, "num_signals": 10}
    monkeypatch.setattr(limits, "simulate_limit_fills", lambda dataset, unfilled_timeout_bars, offset_multiplier: {"overall": overall, "by_asset_class": {"equity": {"fill_rate": 0.7, "num_signals": 10}}})
    monkeypatch.setattr(limits, "sweep_limit_fill_offsets", lambda dataset, unfilled_timeout_bars, offset_multipliers: {m: {"overall": overall} for m in offset_multipliers})
    flags = dict(factor_exposure=True, calibrate_volatility_threshold=True, benchmarks=True, replay_kill_switch=True, simulate_limit_fills=True)
    assert aq_cli.cmd_evaluate(book.args(**flags)) == 0
    text = capsys.readouterr().out
    for fragment in ("Factor exposure (50 dates, market=SPY)", "Suggested phase_v2.topology.elevated_volatility_threshold", "Benchmarks (split=backtest", "n/a", "Kill-switch replay", "overall: fill_rate=70.00%", "equity: fill_rate"):
        assert fragment in text, fragment
    assert aq_cli.cmd_evaluate(book.args(**flags, rank_book=True, limit_fill_offset_sweep="0.5,1.0")) == 0
    text = capsys.readouterr().out
    assert "Factor exposure SKIPPED: no SPY" in text and "Volatility threshold calibration SKIPPED" in text and "offset_multiplier=0.5" in text
