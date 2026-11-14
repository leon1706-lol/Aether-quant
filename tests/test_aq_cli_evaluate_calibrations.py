"""aq evaluate's calibration flows (V6.6.6, #359): the book spread, the rolling-IC floor and its replay, the confidence threshold and the
ablation, with the model and the calibrators stubbed. The test checks what is run, printed and written."""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd
import pytest

import aq_cli
from test_aq_cli_evaluate_lean import env, ns  # noqa: F401  (the fixture and the namespace builder)


@pytest.fixture
def calibrate(env, monkeypatch):
    import evaluation
    import portfolio.rank_signal as rank_signal

    pd.DataFrame({
        "date": ["2025-01-02", "2025-01-03"] * 2, "ticker": ["AAA"] * 2 + ["BBB"] * 2, "split": "backtest", "training_eligible": True,
        "target_return_1d": [0.01, -0.01, 0.02, 0.0], "target_return_20d": [0.05, -0.05, 0.1, 0.0],
    }).to_csv(env.root / "full.csv", index=False)
    (env.root / "ml" / "sequence_model.json").write_text("{}", encoding="utf-8")
    (env.root / "ml" / "sequence_feature_schema.json").write_text(json.dumps({"model_input_names": ["x"]}), encoding="utf-8")
    (env.root / "ml" / "multitask_model.json").write_text("{}", encoding="utf-8")  # no schema beside it: skipped
    (env.root / "ml" / "multitask_training_metrics.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(rank_signal, "resolve_rank_signal_policy", lambda metrics, config: {"heads": {"rank_20d": 1.0, "off": 0.0}, "model_priority": ["multitask", "sequence"]})
    monkeypatch.setattr(evaluation, "predict_head", lambda frame, export, names, head, **kwargs: np.full(len(frame), 0.7))
    monkeypatch.setattr(evaluation, "predict_heads", lambda frame, export, names, heads, **kwargs: {"rank_20d": np.full(len(frame), 0.7)})
    monkeypatch.setattr(evaluation, "compute_blended_raw_scores", lambda frame, predictions, policy: [0.4] * len(frame))
    monkeypatch.setattr(evaluation, "simulate_rank_book", lambda frame, **kwargs: None)
    defaults = dict(dataset=str(env.root / "full.csv"), model=None, head=None, split=None, rank_book=False, all=False, capacity=False, stress=False, calibrate_edge=False)
    return lambda **flags: ns(**{**defaults, **flags})


DISTRIBUTION = {"min": 0.0, "p10": 0.1, "median": 0.2, "p75": 0.3, "max": 0.4}


def test_the_book_spread_is_calibrated_from_the_live_pool(env, calibrate, monkeypatch, capsys):
    import evaluation

    seen = {}
    monkeypatch.setattr(evaluation, "calibrate_book_confidence_spread", lambda dataset, **kwargs: seen.update(kwargs) or {
        "calibrated_min_rank_confidence_spread": 0.1234, "percentile": 0.1, "num_dates_used": 40, "num_dates_skipped_thin_universe": 2, "spread_distribution": DISTRIBUTION})
    assert aq_cli.cmd_evaluate(calibrate(calibrate_book_spread=True)) == 0
    text = capsys.readouterr().out
    assert "Calibrated min_rank_confidence_spread (p10, 40 dates used" in text and "0.1234" in text and seen["session_asset_class"] == "equity"
    assert (env.out / "book_spread_calibration.json").exists()


def test_the_rolling_ic_floor_is_calibrated_and_its_gate_replayed(env, calibrate, monkeypatch, capsys):
    import evaluation.rolling_ic_gate_calibration as floor
    import evaluation.rolling_ic_gate_replay as replay

    monkeypatch.setattr(floor, "calibrate_rolling_ic_floor", lambda dataset, **kwargs: {
        "calibrated_min_rolling_mean_ic": -0.02, "percentile": 0.1, "num_samples_used": 30, "num_samples_skipped_insufficient_history": 5, "rolling_ic_distribution": DISTRIBUTION})
    assert aq_cli.cmd_evaluate(calibrate(calibrate_rolling_ic_floor=True)) == 0
    assert "Calibrated min_rolling_mean_ic (p10, 30 samples used" in capsys.readouterr().out
    monkeypatch.setattr(replay, "replay_rolling_ic_gate_over_dataset", lambda dataset, **kwargs: [{"date": "2025-01-02"}])
    monkeypatch.setattr(replay, "summarize_rolling_ic_gate_replay", lambda records: {
        "overall": {"disengaged_days": 1, "total_dates": 4, "disengaged_day_fraction": 0.25}, "by_era": {"era_1": {"disengaged_days": 1, "total_dates": 2, "disengaged_day_fraction": 0.5}, "era_2": {"disengaged_days": 0, "total_dates": 0, "disengaged_day_fraction": None}}})
    assert aq_cli.cmd_evaluate(calibrate(replay_rolling_ic_gate=True)) == 0
    text = capsys.readouterr().out
    assert "1/4 rebalance dates disengaged (25.00%)" in text and "era_1: 1/2 disengaged (50.00%)" in text and "n/a (no dates in era)" in text
    assert (env.out / "rolling_ic_gate_replay.json").exists()


def test_the_confidence_threshold_is_calibrated_with_a_fallback_horizon(env, calibrate, monkeypatch, capsys):
    import evaluation

    monkeypatch.setattr(evaluation, "calibrate_confidence_threshold", lambda dataset, **kwargs: {
        "calibrated_min_confidence_to_trade": 0.31, "calibrated_min_confidence_to_trade_book_selected": 0.41, "percentile": 0.1, "num_rows_used": 50,
        "num_dates_skipped_thin_universe": 1, "num_rows_used_book_selected": 20})
    assert aq_cli.cmd_evaluate(calibrate(calibrate_confidence_threshold=True)) == 0
    text = capsys.readouterr().out
    assert "Calibrated min_confidence_to_trade (p10, 50 paying rows used" in text and "book_selected (20 paying book-selected rows used): 0.4100" in text
    frame = pd.read_csv(env.root / "full.csv").drop(columns=["target_return_20d"])
    frame.to_csv(env.root / "full.csv", index=False)
    assert aq_cli.cmd_evaluate(calibrate(calibrate_confidence_threshold=True)) == 0
    assert "falling back to target_return_1d" in capsys.readouterr().err


def test_the_ablation_lists_each_variant_and_ends_with_json_when_asked(env, calibrate, monkeypatch, capsys):
    import evaluation

    results = {"static_baseline": {"net_sharpe": 0.4, "delta_vs_static_baseline": 0.0}, "no_cost_model": {"status": "not_offline_measurable", "reason": "needs Lean"}}
    seen = {}
    monkeypatch.setattr(evaluation, "run_ablation", lambda dataset, kwargs, variants: seen.update(variants=variants) or results)
    assert aq_cli.cmd_evaluate(calibrate(ablation=True, variants="static_baseline, no_cost_model,")) == 0
    text = capsys.readouterr().out
    assert seen["variants"] == ["static_baseline", "no_cost_model"] and "[not_offline_measurable] needs Lean" in text and "delta_vs_static_baseline=+0.0000" in text
    assert aq_cli.cmd_evaluate(calibrate(ablation=True)) == 0 and "no_hysteresis" in seen["variants"]
    capsys.readouterr()
    assert aq_cli.cmd_evaluate(argparse.Namespace(**{**vars(calibrate(ablation=True)), "json": True})) == 0
    assert '"ablation"' in capsys.readouterr().out
