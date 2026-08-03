"""Tests for train.py's V5.1 Phase 4 (item 4) multi-model walk-forward
machinery: _run_walk_forward_trainer() (best-effort per-window subprocess
call to train_multitask.py/train_sequence.py) and
run_net_performance_simulation()/_run_walk_forward_net_performance() (the
offline rank-book simulation reused by both the walk-forward path and the
regular trainers' backtest-split evaluation).

Full end-to-end _run_walk_forward() coverage (real dataset build, real
subprocess launches) is intentionally left to CODESPACE RUN 3 - this repo
has no existing fixture for a from-scratch synthetic build_feature_dataset()
run, and building one here would duplicate a lot of machinery for little
marginal coverage over the pure/mockable pieces this file tests directly.

Conventions: no test classes, module-level helpers, unittest.mock patching
of subprocess.run (never a real train_multitask.py/train_sequence.py
process) - same convention tests/test_retraining_orchestrator.py already
uses for its own best-effort subprocess stages.
"""

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from train import (
    _run_walk_forward_net_performance,
    _run_walk_forward_trainer,
    run_net_performance_simulation,
)


# ---------------------------------------------------------------------------
# _run_walk_forward_trainer
# ---------------------------------------------------------------------------


def test_run_walk_forward_trainer_returns_parsed_metrics_on_success(tmp_path, monkeypatch):
    version_id = "walk-forward-abc/window_0"
    metrics_dir = tmp_path / "ml" / "versions" / version_id
    metrics_dir.mkdir(parents=True)
    metrics_path = metrics_dir / "sequence_training_metrics.json"
    metrics_path.write_text(json.dumps({"backtest": {"mcc": 0.5}}), encoding="utf-8")

    monkeypatch.setattr("train.ML_DIR", tmp_path / "ml")
    completed = MagicMock(returncode=0, stdout="ok", stderr="")

    with patch("train.subprocess.run", return_value=completed) as run_mock:
        result = _run_walk_forward_trainer(
            "train_sequence.py", version_id, tmp_path / "full_dataset.csv", tmp_path / "feature_schema.json",
            tmp_path / "config.json", timeout_seconds=60,
        )

    assert result == {"backtest": {"mcc": 0.5}}
    argv = run_mock.call_args.args[0]
    assert "--version-id" in argv and version_id in argv
    assert "--dataset-path" in argv
    assert "--feature-schema-path" in argv
    assert "--config-path" in argv


def test_run_walk_forward_trainer_returns_none_on_nonzero_exit(tmp_path, monkeypatch):
    monkeypatch.setattr("train.ML_DIR", tmp_path / "ml")
    completed = MagicMock(returncode=1, stdout="", stderr="boom")

    with patch("train.subprocess.run", return_value=completed):
        result = _run_walk_forward_trainer(
            "train_multitask.py", "run/window_0", tmp_path / "d.csv", tmp_path / "s.json", tmp_path / "c.json",
            timeout_seconds=60,
        )

    assert result is None


def test_run_walk_forward_trainer_returns_none_when_subprocess_fails_to_launch(tmp_path, monkeypatch):
    monkeypatch.setattr("train.ML_DIR", tmp_path / "ml")

    with patch("train.subprocess.run", side_effect=OSError("no such file")):
        result = _run_walk_forward_trainer(
            "train_multitask.py", "run/window_0", tmp_path / "d.csv", tmp_path / "s.json", tmp_path / "c.json",
            timeout_seconds=60,
        )

    assert result is None


def test_run_walk_forward_trainer_returns_none_when_metrics_file_never_written(tmp_path, monkeypatch):
    # A "skipped, no artifacts written" run (e.g. too few rows in a short
    # window) - exits 0 but the metrics file was never created.
    monkeypatch.setattr("train.ML_DIR", tmp_path / "ml")
    completed = MagicMock(returncode=0, stdout="skipped", stderr="")

    with patch("train.subprocess.run", return_value=completed):
        result = _run_walk_forward_trainer(
            "train_multitask.py", "run/window_0", tmp_path / "d.csv", tmp_path / "s.json", tmp_path / "c.json",
            timeout_seconds=60,
        )

    assert result is None


def test_run_walk_forward_trainer_never_aborts_walk_forward_on_any_failure_mode():
    # Best-effort contract (same as retraining/orchestrator.py::train_multitask()):
    # every failure mode above returns None, never raises.
    with patch("train.subprocess.run", side_effect=RuntimeError("unexpected")):
        result = _run_walk_forward_trainer(
            "train_sequence.py", "run/window_0", "d.csv", "s.json", "c.json", timeout_seconds=60,
        )
    assert result is None


# ---------------------------------------------------------------------------
# run_net_performance_simulation (shared by _run_walk_forward_net_performance
# and train_multitask.py/train_sequence.py's compute_*_metrics())
# ---------------------------------------------------------------------------


def _synthetic_backtest_frame(num_tickers=20, num_days=40, seed=0):
    rng = np.random.default_rng(seed)
    tickers = [f"T{i}" for i in range(num_tickers)]
    dates = pd.bdate_range("2021-01-01", periods=num_days)
    rows = []
    for date in dates:
        for index, ticker in enumerate(tickers):
            skill = (index - num_tickers / 2) / (num_tickers / 2)
            rows.append(
                {
                    "date": date,
                    "ticker": ticker,
                    "_predicted_head": skill + rng.normal(0, 0.4),
                    "target_return_1d": skill * 0.003 + rng.normal(0, 0.01),
                    "liquidity_log_dollar_volume": np.log(1e7 + index * 1e6),
                }
            )
    return pd.DataFrame(rows)


def _net_performance_config(**overrides) -> dict:
    config = dict(
        top_n=4, bottom_n=4, rebalance_every_bars=5, cost_bps_per_side=0.0, commission_bps=0.0,
        gross_exposure=1.0, dollar_neutral=True, sector_neutral=False, hysteresis_rank_margin=0.0,
        max_weight_per_name=0.5, capacity_participation_cap=0.01, capacity_top_n_sweep=[2, 4],
        stress_cost_multipliers=[1.0, 2.0],
    )
    config.update(overrides)
    return config


def test_run_net_performance_simulation_returns_none_when_prediction_column_missing():
    frame = _synthetic_backtest_frame()

    result = run_net_performance_simulation(frame, "does_not_exist", _net_performance_config(), {})

    assert result is None


def test_run_net_performance_simulation_returns_none_when_all_predictions_nan():
    frame = _synthetic_backtest_frame()
    frame["_predicted_head"] = np.nan

    result = run_net_performance_simulation(frame, "_predicted_head", _net_performance_config(), {})

    assert result is None


def test_run_net_performance_simulation_returns_simulation_capacity_and_stress():
    frame = _synthetic_backtest_frame()

    result = run_net_performance_simulation(frame, "_predicted_head", _net_performance_config(), {})

    assert result is not None
    assert set(result.keys()) == {"simulation", "capacity", "stress"}
    assert "net_sharpe" in result["simulation"]
    assert "capacity_usd" in result["capacity"]
    assert len(result["stress"]) == 2  # matches stress_cost_multipliers above


# ---------------------------------------------------------------------------
# _run_walk_forward_net_performance
# ---------------------------------------------------------------------------


def _dataset_with_split(num_tickers=20, num_days=40, seed=0):
    frame = _synthetic_backtest_frame(num_tickers, num_days, seed).rename(columns={"_predicted_head": "_unused"})
    frame["split"] = "backtest"
    frame["training_eligible"] = True
    return frame


def test_run_walk_forward_net_performance_returns_none_for_empty_backtest_split():
    dataset = _dataset_with_split()
    dataset["split"] = "train"  # no backtest rows at all

    result = _run_walk_forward_net_performance(
        dataset, ["f1"], {"export": {}}, "sequence", None, 30, "rank_20d", _net_performance_config(), {}
    )

    assert result is None


def test_run_walk_forward_net_performance_returns_none_when_predict_head_yields_all_nan():
    dataset = _dataset_with_split()

    with patch("train.predict_head", return_value=np.full(len(dataset), np.nan)):
        result = _run_walk_forward_net_performance(
            dataset, ["f1"], {"export": {}}, "sequence", None, 30, "rank_20d", _net_performance_config(), {}
        )

    assert result is None


def test_run_walk_forward_net_performance_returns_head_and_model_kind_on_success():
    dataset = _dataset_with_split()
    rng = np.random.default_rng(1)
    fake_predictions = rng.normal(0, 1, size=len(dataset))

    with patch("train.predict_head", return_value=fake_predictions):
        result = _run_walk_forward_net_performance(
            dataset, ["f1"], {"export": {}}, "sequence", None, 30, "rank_20d", _net_performance_config(), {}
        )

    assert result is not None
    assert result["head"] == "rank_20d"
    assert result["model_kind"] == "sequence"
    assert "simulation" in result and "capacity" in result and "stress" in result
