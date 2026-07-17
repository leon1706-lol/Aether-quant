import math

import pytest

from moe import (
    EXPERT_NAMES,
    GATING_MODEL_FEATURE_KEYS,
    build_gating_decision,
    build_gating_model_features,
)
from moe.gating import ExpertGateWeight, _performance_score


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


# ---------------------------------------------------------------------------
# final_magnitude / final_volatility (per-expert multitask blend)
# ---------------------------------------------------------------------------


def test_final_magnitude_and_volatility_default_to_none_when_never_supplied():
    decision = build_gating_decision(
        regime={"trend_regime": "bullish", "volatility_regime": "normal_volatility", "risk_regime": "risk_on"},
        expert_training_metrics=_metrics(),
        expert_probabilities={"bullish": 0.70, "bearish": 0.35, "sideways": 0.52, "volatility": 0.20},
        baseline_probability_up=0.55,
    )

    assert decision.final_magnitude is None
    assert decision.final_volatility is None
    assert all(weight.magnitude is None and weight.volatility is None for weight in decision.weights)


def test_final_magnitude_blends_baseline_and_expert_average_with_baseline_weight():
    decision = build_gating_decision(
        regime={"trend_regime": "bullish", "volatility_regime": "normal_volatility", "risk_regime": "risk_on"},
        expert_training_metrics=_metrics(),
        expert_probabilities={"bullish": 0.70, "bearish": 0.35, "sideways": 0.52, "volatility": 0.20},
        baseline_probability_up=0.55,
        baseline_weight=0.25,
        expert_magnitudes={"bullish": 0.02, "bearish": -0.01, "sideways": 0.0, "volatility": 0.03},
        expert_volatilities={"bullish": 0.01, "bearish": 0.015, "sideways": 0.005, "volatility": 0.04},
        baseline_magnitude=0.01,
        baseline_volatility=0.012,
    )

    weights_by_expert = {weight.expert: weight.weight for weight in decision.weights}
    expected_expert_magnitude = sum(
        weights_by_expert[expert] * value
        for expert, value in {"bullish": 0.02, "bearish": -0.01, "sideways": 0.0, "volatility": 0.03}.items()
    )
    expected_expert_volatility = sum(
        weights_by_expert[expert] * value
        for expert, value in {"bullish": 0.01, "bearish": 0.015, "sideways": 0.005, "volatility": 0.04}.items()
    )
    expected_magnitude = 0.25 * 0.01 + 0.75 * expected_expert_magnitude
    expected_volatility = 0.25 * 0.012 + 0.75 * expected_expert_volatility

    assert decision.final_magnitude == pytest.approx(expected_magnitude, abs=1e-9)
    assert decision.final_volatility == pytest.approx(expected_volatility, abs=1e-9)


def test_final_magnitude_falls_back_to_baseline_only_when_no_expert_has_a_value():
    decision = build_gating_decision(
        regime={"trend_regime": "bullish", "volatility_regime": "normal_volatility", "risk_regime": "risk_on"},
        expert_training_metrics=_metrics(),
        expert_probabilities={"bullish": 0.70, "bearish": 0.35, "sideways": 0.52, "volatility": 0.20},
        baseline_probability_up=0.55,
        baseline_magnitude=0.015,
        baseline_volatility=0.02,
        # expert_magnitudes/expert_volatilities omitted entirely -> every
        # ExpertGateWeight.magnitude/volatility stays None.
    )

    assert decision.final_magnitude == 0.015
    assert decision.final_volatility == 0.02


def test_final_magnitude_falls_back_to_expert_average_when_baseline_missing():
    decision = build_gating_decision(
        regime={"trend_regime": "bullish", "volatility_regime": "normal_volatility", "risk_regime": "risk_on"},
        expert_training_metrics=_metrics(),
        expert_probabilities={"bullish": 0.70, "bearish": 0.35, "sideways": 0.52, "volatility": 0.20},
        expert_magnitudes={"bullish": 0.02, "bearish": -0.01, "sideways": 0.0, "volatility": 0.03},
        expert_volatilities={"bullish": 0.01, "bearish": 0.015, "sideways": 0.005, "volatility": 0.04},
        # baseline_probability_up omitted -> decision_source == "experts_only",
        # baseline_magnitude/baseline_volatility also both None.
    )

    weights_by_expert = {weight.expert: weight.weight for weight in decision.weights}
    expected_magnitude = sum(
        weights_by_expert[expert] * value
        for expert, value in {"bullish": 0.02, "bearish": -0.01, "sideways": 0.0, "volatility": 0.03}.items()
    )
    assert decision.final_magnitude == pytest.approx(expected_magnitude, abs=1e-9)


def test_final_magnitude_uses_baseline_when_gate_falls_back_with_no_eligible_experts():
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
        baseline_magnitude=0.03,
        baseline_volatility=0.05,
        expert_magnitudes={"bullish": 0.10},
        expert_volatilities={"bullish": 0.20},
    )

    # baseline_fallback: no expert contributed any raw_score, so the
    # magnitude/volatility blend must ignore expert_magnitudes/
    # expert_volatilities entirely too, same as it ignores expert
    # probabilities in this branch.
    assert decision.decision_source == "baseline_fallback"
    assert decision.final_magnitude == 0.03
    assert decision.final_volatility == 0.05


def test_expert_gate_weight_carries_magnitude_and_volatility_through():
    decision = build_gating_decision(
        regime={"trend_regime": "bullish", "volatility_regime": "normal_volatility", "risk_regime": "risk_on"},
        expert_training_metrics=_metrics(),
        expert_probabilities={"bullish": 0.70, "bearish": 0.35, "sideways": 0.52, "volatility": 0.20},
        baseline_probability_up=0.55,
        expert_magnitudes={"bullish": 0.02},
        expert_volatilities={"bullish": 0.01},
    )

    bullish_weight = next(weight for weight in decision.weights if weight.expert == "bullish")
    bearish_weight = next(weight for weight in decision.weights if weight.expert == "bearish")
    assert bullish_weight.magnitude == 0.02
    assert bullish_weight.volatility == 0.01
    assert bearish_weight.magnitude is None
    assert bearish_weight.volatility is None


def test_sequence_prediction_is_ignored_when_weight_is_zero():
    """Default sequence_weight=0.0 must be byte-identical to omitting
    sequence_prediction entirely - the off-by-default, no-op contract
    every other new-signal integration in this codebase follows."""
    kwargs = dict(
        regime={"trend_regime": "bullish", "volatility_regime": "normal_volatility", "risk_regime": "risk_on"},
        expert_training_metrics=_metrics(),
        expert_probabilities={"bullish": 0.70, "bearish": 0.35, "sideways": 0.52, "volatility": 0.20},
        baseline_probability_up=0.55,
        baseline_magnitude=0.01,
        baseline_volatility=0.012,
        expert_magnitudes={"bullish": 0.02, "bearish": -0.01, "sideways": 0.0, "volatility": 0.03},
        expert_volatilities={"bullish": 0.01, "bearish": 0.015, "sideways": 0.005, "volatility": 0.04},
    )
    without_sequence = build_gating_decision(**kwargs)
    with_zero_weight = build_gating_decision(
        **kwargs, sequence_prediction={"direction": 0.9, "magnitude": 0.5, "volatility": 0.5}, sequence_weight=0.0
    )

    assert with_zero_weight.final_probability_up == without_sequence.final_probability_up
    assert with_zero_weight.final_magnitude == without_sequence.final_magnitude
    assert with_zero_weight.final_volatility == without_sequence.final_volatility
    assert with_zero_weight.sequence_blended is False
    assert without_sequence.sequence_blended is False


def test_sequence_prediction_is_ignored_when_none_even_with_positive_weight():
    decision = build_gating_decision(
        regime={"trend_regime": "bullish", "volatility_regime": "normal_volatility", "risk_regime": "risk_on"},
        expert_training_metrics=_metrics(),
        expert_probabilities={"bullish": 0.70, "bearish": 0.35, "sideways": 0.52, "volatility": 0.20},
        baseline_probability_up=0.55,
        sequence_prediction=None,
        sequence_weight=0.3,
    )

    assert decision.sequence_blended is False


def test_sequence_prediction_blends_probability_magnitude_and_volatility():
    decision = build_gating_decision(
        regime={"trend_regime": "bullish", "volatility_regime": "normal_volatility", "risk_regime": "risk_on"},
        expert_training_metrics=_metrics(),
        expert_probabilities={"bullish": 0.70, "bearish": 0.35, "sideways": 0.52, "volatility": 0.20},
        baseline_probability_up=0.55,
        baseline_magnitude=0.01,
        baseline_volatility=0.012,
        expert_magnitudes={"bullish": 0.02, "bearish": -0.01, "sideways": 0.0, "volatility": 0.03},
        expert_volatilities={"bullish": 0.01, "bearish": 0.015, "sideways": 0.005, "volatility": 0.04},
        sequence_prediction={"direction": 0.9, "magnitude": 0.05, "volatility": 0.08},
        sequence_weight=0.2,
    )
    pre_sequence = build_gating_decision(
        regime={"trend_regime": "bullish", "volatility_regime": "normal_volatility", "risk_regime": "risk_on"},
        expert_training_metrics=_metrics(),
        expert_probabilities={"bullish": 0.70, "bearish": 0.35, "sideways": 0.52, "volatility": 0.20},
        baseline_probability_up=0.55,
        baseline_magnitude=0.01,
        baseline_volatility=0.012,
        expert_magnitudes={"bullish": 0.02, "bearish": -0.01, "sideways": 0.0, "volatility": 0.03},
        expert_volatilities={"bullish": 0.01, "bearish": 0.015, "sideways": 0.005, "volatility": 0.04},
    )

    expected_probability = 0.2 * 0.9 + 0.8 * pre_sequence.final_probability_up
    expected_magnitude = 0.2 * 0.05 + 0.8 * pre_sequence.final_magnitude
    expected_volatility = 0.2 * 0.08 + 0.8 * pre_sequence.final_volatility

    assert decision.final_probability_up == pytest.approx(expected_probability, abs=1e-9)
    assert decision.final_magnitude == pytest.approx(expected_magnitude, abs=1e-9)
    assert decision.final_volatility == pytest.approx(expected_volatility, abs=1e-9)
    assert decision.sequence_blended is True


def test_sequence_prediction_applies_on_top_of_learned_gating_override():
    """The sequence blend must apply after decision_source has already
    been resolved to "learned_gating", not just the hardcoded blend -
    it's a final layered adjustment regardless of which path produced
    final_probability first."""
    gating_model = {
        "export": {
            "architecture": [
                {
                    "type": "linear",
                    "weight_key": "w",
                    "bias_key": "b",
                    "in_features": len(GATING_MODEL_FEATURE_KEYS),
                    "out_features": 1,
                },
                {"type": "sigmoid"},
            ],
            "state_dict": {
                "w": [[0.0] * len(GATING_MODEL_FEATURE_KEYS)],
                "b": [2.0],  # sigmoid(2.0) ~= 0.8808, independent of input
            },
        }
    }
    decision = build_gating_decision(
        regime={"trend_regime": "bullish", "volatility_regime": "normal_volatility", "risk_regime": "risk_on"},
        expert_training_metrics=_metrics(),
        expert_probabilities={"bullish": 0.70, "bearish": 0.35, "sideways": 0.52, "volatility": 0.20},
        baseline_probability_up=0.55,
        gating_model=gating_model,
        gating_feature_schema={"input_order": list(GATING_MODEL_FEATURE_KEYS)},
        sequence_prediction={"direction": 0.1, "magnitude": None, "volatility": None},
        sequence_weight=0.5,
    )

    assert decision.decision_source == "learned_gating"
    learned_probability = 1.0 / (1.0 + math.exp(-2.0))
    expected_probability = 0.5 * 0.1 + 0.5 * learned_probability
    assert decision.final_probability_up == pytest.approx(expected_probability, abs=1e-9)
    assert decision.sequence_blended is True


def test_performance_score_floors_at_zero_below_coin_flip_skill():
    # development/Problems.md: the old unconditional 0.25 floor let a
    # no-measured-skill expert (backtest balanced-accuracy AT or BELOW a
    # coin flip AND backtest MCC not positive) still contribute weight to
    # the blend - averaging several such experts together mathematically
    # pulls the combined prediction toward 0.5, which main.py's live output
    # (0.4836-0.4907) matched exactly.
    no_skill_metrics = {"validation": {"balanced_accuracy": 0.51}, "backtest": {"balanced_accuracy": 0.50, "mcc": 0.0}}
    assert _performance_score(no_skill_metrics) == 0.0

    below_random_metrics = {"validation": {"balanced_accuracy": 0.55}, "backtest": {"balanced_accuracy": 0.48, "mcc": -0.02}}
    assert _performance_score(below_random_metrics) == 0.0


def test_performance_score_positive_when_either_metric_clears_skill_floor():
    # Only ONE of backtest_balanced_accuracy > 0.5 / backtest_mcc > 0.0 needs
    # to clear the bar - matches _performance_score()'s own `and` (both must
    # be at-or-below to zero out), not requiring both to clear to count.
    bacc_only = {"validation": {"balanced_accuracy": 0.50}, "backtest": {"balanced_accuracy": 0.53, "mcc": 0.0}}
    assert _performance_score(bacc_only) > 0.0

    mcc_only = {"validation": {"balanced_accuracy": 0.50}, "backtest": {"balanced_accuracy": 0.50, "mcc": 0.03}}
    assert _performance_score(mcc_only) > 0.0


def test_zero_skill_expert_is_excluded_from_the_blend_entirely():
    metrics = {
        "experts": {
            "bullish": {
                "quality_gate": {"quality_status": "stable", "gating_eligible": True},
                "validation": {"balanced_accuracy": 0.55},
                "backtest": {"balanced_accuracy": 0.53, "mcc": 0.06},
            },
            "bearish": {
                # No measured skill - should score 0.0 and be excluded.
                "quality_gate": {"quality_status": "stable", "gating_eligible": True},
                "validation": {"balanced_accuracy": 0.50},
                "backtest": {"balanced_accuracy": 0.49, "mcc": -0.01},
            },
            "sideways": {
                "quality_gate": {"quality_status": "disabled_for_gating", "gating_eligible": False},
                "validation": {"balanced_accuracy": 0.50},
                "backtest": {"balanced_accuracy": 0.50, "mcc": 0.0},
            },
            "volatility": {
                "quality_gate": {"quality_status": "disabled_for_gating", "gating_eligible": False},
                "validation": {"balanced_accuracy": 0.50},
                "backtest": {"balanced_accuracy": 0.50, "mcc": 0.0},
            },
        }
    }
    decision = build_gating_decision(
        regime={"trend_regime": "bullish", "volatility_regime": "normal_volatility", "risk_regime": "risk_on"},
        expert_training_metrics=metrics,
        expert_probabilities={"bullish": 0.70, "bearish": 0.30, "sideways": None, "volatility": None},
    )

    bearish_weight = next(weight for weight in decision.weights if weight.expert == "bearish")
    assert bearish_weight.performance_score == 0.0
    assert bearish_weight.raw_score == 0.0
    assert bearish_weight.weight == 0.0
    # Only bullish had any measured skill - it should get ALL the weight.
    bullish_weight = next(weight for weight in decision.weights if weight.expert == "bullish")
    assert bullish_weight.weight == pytest.approx(1.0)
