"""Gating logic for Aether Quant V2 Mixture-of-Experts."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from inference import run_exported_model


EXPERT_NAMES = ("bullish", "bearish", "sideways", "volatility")

# Fixed order, 26 dims - every value is already a bounded probability
# [0,1] or a one-hot flag, so (unlike topology/learned_topology.py's
# z-scored prototypes) no scaler/feature_stats is needed for this model.
GATING_MODEL_FEATURE_KEYS = (
    "bullish_probability_up", "bullish_quality_multiplier", "bullish_performance_score", "bullish_regime_alignment",
    "bearish_probability_up", "bearish_quality_multiplier", "bearish_performance_score", "bearish_regime_alignment",
    "sideways_probability_up", "sideways_quality_multiplier", "sideways_performance_score", "sideways_regime_alignment",
    "volatility_probability_up", "volatility_quality_multiplier", "volatility_performance_score", "volatility_regime_alignment",
    "baseline_probability_up",
    "trend_regime_bullish", "trend_regime_bearish", "trend_regime_sideways",
    "volatility_regime_low_volatility", "volatility_regime_normal_volatility", "volatility_regime_high_volatility",
    "risk_regime_risk_on", "risk_regime_risk_off", "risk_regime_risk_neutral",
)


@dataclass(frozen=True)
class ExpertGateWeight:
    expert: str
    weight: float
    raw_score: float
    probability_up: float | None
    quality_status: str
    quality_multiplier: float
    gating_eligible: bool
    regime_alignment: float
    performance_score: float
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class GatingDecision:
    final_probability_up: float
    baseline_probability_up: float | None
    expert_probability_up: float | None
    active_experts: list[str]
    disabled_experts: list[str]
    weights: list[ExpertGateWeight]
    decision_source: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["weights"] = [weight.to_dict() for weight in self.weights]
        return payload


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(float(value), upper))


def _expert_metrics(expert_training_metrics: dict, expert_name: str) -> dict:
    return dict(expert_training_metrics.get("experts", {}).get(expert_name, {}))


def _quality_multiplier(metrics: dict) -> tuple[float, str, bool]:
    quality_gate = metrics.get("quality_gate", {})
    quality_status = str(quality_gate.get("quality_status", metrics.get("quality_status", "unknown")))
    gating_eligible = bool(quality_gate.get("gating_eligible", metrics.get("gating_eligible", False)))
    if not gating_eligible or quality_status == "disabled_for_gating":
        return 0.0, quality_status, False
    if quality_status == "stable":
        return 1.0, quality_status, True
    if quality_status == "watchlist":
        return 0.55, quality_status, True
    return 0.35, quality_status, True


def _performance_score(metrics: dict) -> float:
    validation = metrics.get("validation", {})
    backtest = metrics.get("backtest", {})
    validation_balanced_accuracy = float(validation.get("balanced_accuracy", 0.5) or 0.5)
    backtest_balanced_accuracy = float(backtest.get("balanced_accuracy", 0.5) or 0.5)
    backtest_mcc = float(backtest.get("mcc", 0.0) or 0.0)

    score = 0.25
    score += max(0.0, validation_balanced_accuracy - 0.48) * 2.0
    score += max(0.0, backtest_balanced_accuracy - 0.48) * 3.0
    score += max(0.0, backtest_mcc) * 1.5
    return _clamp(score, 0.05, 1.0)


def _regime_alignment(expert_name: str, regime: dict) -> tuple[float, str]:
    trend_regime = str(regime.get("trend_regime", "unknown"))
    volatility_regime = str(regime.get("volatility_regime", "unknown"))
    risk_regime = str(regime.get("risk_regime", "unknown"))

    if expert_name == "bullish":
        if trend_regime == "bullish" and risk_regime != "risk_off":
            return 1.0, "bullish_trend_match"
        if trend_regime == "bullish":
            return 0.65, "bullish_but_risk_off"
        return 0.15, "trend_mismatch"

    if expert_name == "bearish":
        if trend_regime == "bearish":
            return 1.0, "bearish_trend_match"
        if risk_regime == "risk_off":
            return 0.60, "risk_off_support"
        return 0.15, "trend_mismatch"

    if expert_name == "sideways":
        if trend_regime == "sideways":
            return 1.0, "sideways_trend_match"
        if volatility_regime == "low_volatility":
            return 0.55, "low_volatility_support"
        return 0.20, "trend_mismatch"

    if expert_name == "volatility":
        if volatility_regime == "high_volatility":
            return 1.0, "high_volatility_match"
        if risk_regime == "risk_off":
            return 0.70, "risk_off_volatility_support"
        return 0.25, "volatility_not_elevated"

    return 0.0, "unknown_expert"


def build_gating_model_features(
    regime: dict,
    baseline_probability_up: float | None,
    weights: list[ExpertGateWeight],
) -> list[float]:
    """Pure feature-vector builder for the optional learned gating model -
    same fixed order as GATING_MODEL_FEATURE_KEYS. `weights` must contain
    exactly one ExpertGateWeight per EXPERT_NAMES entry, which
    build_gating_decision() always guarantees."""
    weight_by_expert = {weight.expert: weight for weight in weights}
    features: list[float] = []
    for expert_name in EXPERT_NAMES:
        expert_weight = weight_by_expert[expert_name]
        features.append(0.5 if expert_weight.probability_up is None else expert_weight.probability_up)
        features.append(expert_weight.quality_multiplier)
        features.append(expert_weight.performance_score)
        features.append(expert_weight.regime_alignment)
    features.append(0.5 if baseline_probability_up is None else _clamp(baseline_probability_up))

    trend_regime = str(regime.get("trend_regime", "unknown"))
    volatility_regime = str(regime.get("volatility_regime", "unknown"))
    risk_regime = str(regime.get("risk_regime", "unknown"))
    for label in ("bullish", "bearish", "sideways"):
        features.append(1.0 if trend_regime == label else 0.0)
    for label in ("low_volatility", "normal_volatility", "high_volatility"):
        features.append(1.0 if volatility_regime == label else 0.0)
    for label in ("risk_on", "risk_off", "risk_neutral"):
        features.append(1.0 if risk_regime == label else 0.0)
    return features


def build_gating_decision(
    regime: dict,
    expert_training_metrics: dict,
    expert_probabilities: dict[str, float | None],
    baseline_probability_up: float | None = None,
    baseline_weight: float = 0.25,
    gating_model: dict | None = None,
    gating_feature_schema: dict | None = None,
) -> GatingDecision:
    weights: list[ExpertGateWeight] = []
    disabled_experts = []

    for expert_name in EXPERT_NAMES:
        probability = expert_probabilities.get(expert_name)
        metrics = _expert_metrics(expert_training_metrics, expert_name)
        quality_multiplier, quality_status, gating_eligible = _quality_multiplier(metrics)
        performance_score = _performance_score(metrics)
        alignment, alignment_reason = _regime_alignment(expert_name, regime)

        if probability is None:
            raw_score = 0.0
            reason = "missing_probability"
        elif not gating_eligible:
            raw_score = 0.0
            reason = "quality_gate_disabled"
        else:
            raw_score = quality_multiplier * performance_score * alignment
            reason = alignment_reason

        if raw_score <= 0.0:
            disabled_experts.append(expert_name)

        weights.append(
            ExpertGateWeight(
                expert=expert_name,
                weight=0.0,
                raw_score=raw_score,
                probability_up=None if probability is None else _clamp(probability),
                quality_status=quality_status,
                quality_multiplier=quality_multiplier,
                gating_eligible=gating_eligible,
                regime_alignment=alignment,
                performance_score=performance_score,
                reason=reason,
            )
        )

    total_score = sum(weight.raw_score for weight in weights)
    if total_score <= 0.0:
        normalized_weights = weights
        expert_probability = None
        final_probability = baseline_probability_up if baseline_probability_up is not None else 0.5
        decision_source = "baseline_fallback"
    else:
        normalized_weights = [
            ExpertGateWeight(
                expert=weight.expert,
                weight=weight.raw_score / total_score,
                raw_score=weight.raw_score,
                probability_up=weight.probability_up,
                quality_status=weight.quality_status,
                quality_multiplier=weight.quality_multiplier,
                gating_eligible=weight.gating_eligible,
                regime_alignment=weight.regime_alignment,
                performance_score=weight.performance_score,
                reason=weight.reason,
            )
            for weight in weights
        ]
        expert_probability = sum(
            weight.weight * float(weight.probability_up)
            for weight in normalized_weights
            if weight.probability_up is not None
        )

        if baseline_probability_up is None:
            final_probability = expert_probability
            decision_source = "experts_only"
        else:
            clamped_baseline_weight = _clamp(baseline_weight, 0.0, 0.90)
            final_probability = (
                clamped_baseline_weight * _clamp(baseline_probability_up)
                + (1.0 - clamped_baseline_weight) * expert_probability
            )
            decision_source = "baseline_and_experts"

    # Optional, additive, always-falls-back learned override - see
    # development/Problems.md and moe/README.md. The hardcoded blend above
    # is always computed first and is what ships whenever no learned model
    # is present/enabled, or if scoring it fails for any reason (mirrors
    # topology/learned_topology.py's per-node fallback isolation: a
    # degraded/missing learned model must never crash a bar or block a
    # decision, only silently forfeit the improvement it would have added).
    if gating_model and gating_feature_schema:
        try:
            feature_vector = build_gating_model_features(regime, baseline_probability_up, normalized_weights)
            final_probability = run_exported_model(gating_model, feature_vector)
            decision_source = "learned_gating"
        except Exception:
            pass

    return GatingDecision(
        final_probability_up=_clamp(final_probability),
        baseline_probability_up=None if baseline_probability_up is None else _clamp(baseline_probability_up),
        expert_probability_up=None if expert_probability is None else _clamp(expert_probability),
        active_experts=[weight.expert for weight in normalized_weights if weight.weight > 0.0],
        disabled_experts=disabled_experts,
        weights=normalized_weights,
        decision_source=decision_source,
    )
