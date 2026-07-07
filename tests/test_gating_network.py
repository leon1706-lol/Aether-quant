import math

import pytest

from moe import (
    EXPERT_NAMES,
    GATING_MODEL_FEATURE_KEYS,
    build_gating_decision,
    build_gating_model_features,
)
from moe.gating import ExpertGateWeight


def _metrics() -> dict:
    return {
        "experts": {
            "bullish": {
                "quality_gate": {"quality_status": "stable", "gating_eligible": True},
                "validation": {"balanced_accuracy": 0.55},
                "backtest": {"balanced_accuracy": 0.53, "mcc": 0.06},
            },
            "bearish": {
                "quality_gate": {"quality_status": "stable", "gating_eligible": True},
                "validation": {"balanced_accuracy": 0.57},
                "backtest": {"balanced_accuracy": 0.52, "mcc": 0.04},
            },
            "sideways": {
                "quality_gate": {"quality_status": "watchlist", "gating_eligible": True},
                "validation": {"balanced_accuracy": 0.51},
                "backtest": {"balanced_accuracy": 0.50, "mcc": 0.01},
            },
            "volatility": {
                "quality_gate": {"quality_status": "disabled_for_gating", "gating_eligible": False},
                "validation": {"balanced_accuracy": 0.60},
                "backtest": {"balanced_accuracy": 0.60, "mcc": 0.20},
            },
        }
    }


def test_gating_prefers_regime_aligned_expert():
    decision = build_gating_decision(
        regime={
            "trend_regime": "bullish",
            "volatility_regime": "normal_volatility",
            "risk_regime": "risk_on",
        },
        expert_training_metrics=_metrics(),
        expert_probabilities={
            "bullish": 0.70,
            "bearish": 0.35,
            "sideways": 0.52,
            "volatility": 0.20,
        },
        baseline_probability_up=0.55,
    )

    weights = {weight.expert: weight.weight for weight in decision.weights}

    assert decision.decision_source == "baseline_and_experts"
    assert "bullish" in decision.active_experts
    assert weights["bullish"] > weights["bearish"]
    assert weights["volatility"] == 0.0
    assert decision.final_probability_up > 0.55


def test_gating_falls_back_to_baseline_when_no_experts_are_eligible():
    metrics = {
        "experts": {
            expert: {"quality_gate": {"quality_status": "disabled_for_gating", "gating_eligible": False}}
            for expert in ("bullish", "bearish", "sideways", "volatility")
        }
    }
    decision = build_gating_decision(
        regime={"trend_regime": "bullish"},
        expert_training_metrics=metrics,
        expert_probabilities={"bullish": 0.80},
        baseline_probability_up=0.61,
    )

    assert decision.decision_source == "baseline_fallback"
    assert decision.final_probability_up == 0.61
    assert decision.active_experts == []


def test_watchlist_experts_can_contribute_with_reduced_weight():
    decision = build_gating_decision(
        regime={
            "trend_regime": "sideways",
            "volatility_regime": "low_volatility",
            "risk_regime": "risk_neutral",
        },
        expert_training_metrics=_metrics(),
        expert_probabilities={
            "bullish": 0.60,
            "bearish": 0.40,
            "sideways": 0.58,
            "volatility": 0.50,
        },
    )

    weights = {weight.expert: weight.weight for weight in decision.weights}

    assert decision.decision_source == "experts_only"
    assert weights["sideways"] > 0.0
    assert weights["volatility"] == 0.0
    assert 0.0 <= decision.final_probability_up <= 1.0


# ---------------------------------------------------------------------------
# build_gating_model_features
# ---------------------------------------------------------------------------


def _sample_weight(expert: str, probability_up: float | None = 0.5) -> ExpertGateWeight:
    return ExpertGateWeight(
        expert=expert,
        weight=0.25,
        raw_score=0.25,
        probability_up=probability_up,
        quality_status="stable",
        quality_multiplier=1.0,
        gating_eligible=True,
        regime_alignment=0.7,
        performance_score=0.6,
        reason="test_fixture",
    )


def test_build_gating_model_features_returns_fixed_length_vector_in_declared_order():
    weights = [_sample_weight(expert) for expert in EXPERT_NAMES]
    regime = {"trend_regime": "bullish", "volatility_regime": "low_volatility", "risk_regime": "risk_on"}

    features = build_gating_model_features(regime, 0.55, weights)

    assert len(features) == len(GATING_MODEL_FEATURE_KEYS) == 26
    # bullish block: probability_up, quality_multiplier, performance_score, regime_alignment
    assert features[0:4] == [0.5, 1.0, 0.6, 0.7]
    # baseline_probability_up sits right after all 4 experts' 4-field blocks (index 16)
    assert features[16] == 0.55
    # trend_regime_bullish / trend_regime_bearish / trend_regime_sideways
    assert features[17:20] == [1.0, 0.0, 0.0]
    # volatility_regime_low_volatility / normal_volatility / high_volatility
    assert features[20:23] == [1.0, 0.0, 0.0]
    # risk_regime_risk_on / risk_off / risk_neutral
    assert features[23:26] == [1.0, 0.0, 0.0]


def test_build_gating_model_features_defaults_missing_probabilities_to_half():
    weights = [_sample_weight(expert, probability_up=None) for expert in EXPERT_NAMES]

    features = build_gating_model_features({}, None, weights)

    assert features[0] == 0.5  # missing expert probability defaults to 0.5
    assert features[16] == 0.5  # missing baseline probability defaults to 0.5


# ---------------------------------------------------------------------------
# build_gating_decision with an optional learned model
# ---------------------------------------------------------------------------


def _linear_sigmoid_gating_model(weights: list[float], bias: float) -> dict:
    """A minimal, hand-verifiable 26-input linear -> sigmoid stack, same
    export shape as every other model (train.py::export_architecture()),
    small enough to compute an independent reference value by hand."""
    return {
        "export": {
            "architecture": [
                {"type": "linear", "weight_key": "l1.weight", "bias_key": "l1.bias"},
                {"type": "sigmoid"},
            ],
            "state_dict": {
                "l1.weight": [weights],
                "l1.bias": [bias],
            },
        }
    }


def test_gating_uses_learned_model_when_present():
    weights_vector = [0.02 * i for i in range(26)]
    bias = -0.1
    gating_model = _linear_sigmoid_gating_model(weights_vector, bias)
    gating_feature_schema = {"feature_keys": list(GATING_MODEL_FEATURE_KEYS)}

    decision = build_gating_decision(
        regime={"trend_regime": "bullish", "volatility_regime": "normal_volatility", "risk_regime": "risk_on"},
        expert_training_metrics=_metrics(),
        expert_probabilities={"bullish": 0.70, "bearish": 0.35, "sideways": 0.52, "volatility": 0.20},
        baseline_probability_up=0.55,
        gating_model=gating_model,
        gating_feature_schema=gating_feature_schema,
    )

    assert decision.decision_source == "learned_gating"
    feature_vector = build_gating_model_features(
        {"trend_regime": "bullish", "volatility_regime": "normal_volatility", "risk_regime": "risk_on"},
        0.55,
        decision.weights,
    )
    pre_sigmoid = sum(w * x for w, x in zip(weights_vector, feature_vector)) + bias
    expected = 1.0 / (1.0 + math.exp(-pre_sigmoid))
    assert decision.final_probability_up == pytest.approx(expected, abs=1e-9)


def test_gating_falls_back_to_hardcoded_blend_when_model_missing():
    kwargs = dict(
        regime={"trend_regime": "bullish", "volatility_regime": "normal_volatility", "risk_regime": "risk_on"},
        expert_training_metrics=_metrics(),
        expert_probabilities={"bullish": 0.70, "bearish": 0.35, "sideways": 0.52, "volatility": 0.20},
        baseline_probability_up=0.55,
    )
    without_model = build_gating_decision(**kwargs)
    with_none_model = build_gating_decision(**kwargs, gating_model=None, gating_feature_schema=None)

    assert without_model.decision_source == "baseline_and_experts"
    assert with_none_model.decision_source == "baseline_and_experts"
    assert without_model.final_probability_up == with_none_model.final_probability_up


def test_gating_never_raises_on_malformed_learned_model():
    malformed_model = {"export": {"architecture": [{"type": "conv2d"}], "state_dict": {}}}

    decision = build_gating_decision(
        regime={"trend_regime": "bullish", "volatility_regime": "normal_volatility", "risk_regime": "risk_on"},
        expert_training_metrics=_metrics(),
        expert_probabilities={"bullish": 0.70, "bearish": 0.35, "sideways": 0.52, "volatility": 0.20},
        baseline_probability_up=0.55,
        gating_model=malformed_model,
        gating_feature_schema={"feature_keys": list(GATING_MODEL_FEATURE_KEYS)},
    )

    assert decision.decision_source == "baseline_and_experts"
    assert 0.0 <= decision.final_probability_up <= 1.0
