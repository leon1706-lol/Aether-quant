"""scripts/build_legacy_probability.py (V6.1.0): the legacy signal's probability goes through main.py's gating call."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from moe.gating import build_gating_decision
from regime.market_regime import build_market_regime_vector

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_legacy_probability", ROOT / "scripts" / "build_legacy_probability.py")
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)


def test_the_row_probability_is_the_gating_blend_with_the_sequence_direction():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    features = {"momentum_5d": 0.03, "rolling_volatility_20d": 0.012, "topology_correlation_strength": 0.4}
    experts = {"bullish": 0.6, "bearish": 0.45, "sideways": 0.5, "volatility": 0.52}
    value = legacy.legacy_probability(features, 0.55, experts, 0.7, {}, config)
    gating = config["phase_v2"]["gating_network"]
    regime = build_market_regime_vector(features, portfolio_drawdown=0.0, average_correlation=0.4,
                                        **legacy.regime_thresholds(config)).to_dict()
    expected = build_gating_decision(
        regime=regime, expert_training_metrics={}, expert_probabilities=experts, baseline_probability_up=0.55,
        baseline_weight=gating["baseline_weight"], sequence_prediction={"direction": 0.7}, sequence_weight=gating["sequence_weight"],
    ).final_probability_up
    assert value == pytest.approx(expected, abs=1e-15)
    assert legacy.legacy_probability(features, 0.55, experts, None, {}, config) != value  # the sequence head moves it


def _eligible_metrics():
    quality = {"quality_gate": {"quality_status": "stable", "gating_eligible": True},
               "validation": {"balanced_accuracy": 0.56}, "backtest": {"balanced_accuracy": 0.54, "mcc": 0.05}}
    return {"experts": {name: dict(quality) for name in legacy.EXPERT_COLUMNS}}


def test_recombining_stored_components_equals_the_direct_row_and_an_excluded_expert_moves_it():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    features = {"momentum_5d": 0.03, "rolling_volatility_20d": 0.012, "topology_correlation_strength": 0.4}
    experts = {"bullish": 0.6, "bearish": 0.45, "sideways": 0.5, "volatility": 0.52}
    metrics = _eligible_metrics()
    direct = legacy.legacy_probability(features, 0.55, experts, 0.7, metrics, config)
    regime = build_market_regime_vector(features, portfolio_drawdown=0.0, average_correlation=0.4,
                                        **legacy.regime_thresholds(config)).to_dict()
    row = {"baseline": 0.55, **experts, "sequence_direction": 0.7, **{name: regime[name] for name in legacy.REGIME_COLUMNS}}
    assert legacy.legacy_probability_from_components(row, metrics, config) == pytest.approx(direct, abs=1e-15)
    dropped = legacy.legacy_probability_from_components(row, metrics, config, excluded_experts=("bullish",))
    assert dropped != direct
    assert dropped == pytest.approx(legacy.legacy_probability(features, 0.55, {k: v for k, v in experts.items() if k != "bullish"},
                                                              0.7, metrics, config), abs=1e-15)
