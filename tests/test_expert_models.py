import pandas as pd

from train import assess_expert_quality, train_expert_models


def _expert_training_config() -> dict:
    return {
        "name": "Aether Quant",
        "phase1": {
            "features": {
                "input_set": [
                    "momentum_5d",
                    "momentum_20d",
                    "rolling_volatility_20d",
                ]
            }
        },
        "phase3": {
            "model": {
                "type": "robust_mlp_classifier",
                "hidden_layers": [4],
                "dropout": 0.0,
                "activation": "relu",
                "normalization": "layernorm",
                "output_activation": "sigmoid",
                "use_asset_context": False,
            },
            "training": {
                "seed": 7,
                "epochs": 2,
                "batch_size": 2,
                "learning_rate": 0.001,
                "weight_decay": 0.0,
                "patience": 2,
                "decision_threshold": 0.5,
                "optimize_threshold_metric": "f1",
                "threshold_search_min": 0.45,
                "threshold_search_max": 0.55,
                "threshold_search_steps": 3,
            },
        },
        "phase_v2": {
            "expert_models": {
                "model": {
                    "hidden_layers": [4],
                    "dropout": 0.0,
                    "normalization": "layernorm",
                },
                "training": {
                    "epochs": 2,
                    "patience": 2,
                    "min_train_rows": 1,
                    "min_validation_rows": 1,
                    "min_backtest_rows": 1,
                }
            }
        },
    }


def _row(date: str, ticker: str, split: str, momentum: float, volatility: float, target: int) -> dict:
    return {
        "date": date,
        "ticker": ticker,
        "split": split,
        "training_eligible": True,
        "target_direction": target,
        "momentum_5d": momentum,
        "momentum_20d": momentum,
        "rolling_volatility_20d": volatility,
        "momentum_5d_scaled": momentum,
        "momentum_20d_scaled": momentum,
        "rolling_volatility_20d_scaled": volatility,
    }


def test_train_expert_models_writes_metrics_and_weight_exports(tmp_path):
    rows = []
    for split, target in [("train", 1), ("validation", 1), ("backtest", 0)]:
        rows.append(_row(f"2020-01-0{len(rows) + 1}", "BULL", split, 0.06, 0.012, target))
    for split, target in [("train", 0), ("validation", 0), ("backtest", 1)]:
        rows.append(_row(f"2020-01-0{len(rows) + 1}", "BEAR", split, -0.06, 0.05, target))
    for split, target in [("train", 1), ("validation", 0), ("backtest", 1)]:
        rows.append(_row(f"2020-01-0{len(rows) + 1}", "SIDE", split, 0.0, 0.006, target))

    dataset = pd.DataFrame(rows)
    dataset_manifest = {
        "project": "Aether Quant",
        "feature_names": ["momentum_5d", "momentum_20d", "rolling_volatility_20d"],
        "model_input_names": ["momentum_5d_scaled", "momentum_20d_scaled", "rolling_volatility_20d_scaled"],
        "target_column": "target_direction",
    }

    summary = train_expert_models(
        _expert_training_config(),
        dataset,
        dataset_manifest,
        output_dir=tmp_path / "expert_models",
        metrics_path=tmp_path / "expert_training_metrics.json",
    )

    assert set(summary["trained_experts"]) == {"bullish", "bearish", "sideways", "volatility"}
    assert summary["skipped_experts"] == []
    assert "quality_status_counts" in summary
    assert "gating_eligible_experts" in summary
    assert (tmp_path / "expert_models" / "bullish" / "model_weights.json").exists()
    assert (tmp_path / "expert_models" / "volatility" / "metrics.json").exists()
    assert (tmp_path / "expert_training_metrics.json").exists()


def test_assess_expert_quality_disables_overfit_or_weak_experts():
    metrics = {
        "train": {"balanced_accuracy": 0.82},
        "validation": {"balanced_accuracy": 0.47},
        "backtest": {"balanced_accuracy": 0.43, "mcc": -0.15},
    }
    training_config = {
        "quality_gate": {
            "min_validation_balanced_accuracy": 0.48,
            "min_backtest_balanced_accuracy": 0.48,
            "min_backtest_mcc": -0.05,
            "max_train_backtest_balanced_accuracy_gap": 0.20,
            "watchlist_margin": 0.03,
        }
    }

    quality = assess_expert_quality(metrics, training_config)

    assert quality["quality_status"] == "disabled_for_gating"
    assert quality["gating_eligible"] is False
    assert "train_backtest_gap_too_large" in quality["failures"]


def test_assess_expert_quality_marks_near_gate_experts_as_watchlist():
    metrics = {
        "train": {"balanced_accuracy": 0.59},
        "validation": {"balanced_accuracy": 0.50},
        "backtest": {"balanced_accuracy": 0.49, "mcc": -0.03},
    }
    training_config = {
        "quality_gate": {
            "min_validation_balanced_accuracy": 0.48,
            "min_backtest_balanced_accuracy": 0.48,
            "min_backtest_mcc": -0.05,
            "max_train_backtest_balanced_accuracy_gap": 0.20,
            "watchlist_margin": 0.03,
        }
    }

    quality = assess_expert_quality(metrics, training_config)

    assert quality["quality_status"] == "watchlist"
    assert quality["gating_eligible"] is True
