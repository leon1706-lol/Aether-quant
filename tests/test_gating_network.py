from moe import build_gating_decision


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
