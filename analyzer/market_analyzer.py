"""Central market analyzer for Aether Quant V2: combines expert, regime,
topology and risk-engine outputs into one explainable per-asset action."""

from __future__ import annotations

from dataclasses import asdict, dataclass


ACTIONS = ("observe", "simulate", "trade", "reduce_risk", "retrain_candidate")


@dataclass(frozen=True)
class MarketAnalysisDecision:
    action: str
    signal: str
    target_weight: float
    confidence: float
    probability_up: float
    trading_eligible: bool
    topology_considered: bool
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def build_market_analysis_decision(
    signal_name: str,
    confidence: float,
    probability_up: float,
    target_weight: float,
    regime: dict,
    gating: dict,
    trading_eligible: bool,
    trade_lock_active: bool,
    trade_lock_reason: str | None = None,
    topology: dict | None = None,
    min_confidence_to_trade: float = 0.12,
    retrain_min_regime_confidence: float = 0.20,
    low_regime_confidence_threshold: float = 0.35,
) -> MarketAnalysisDecision:
    reasons: list[str] = []
    decision_source = str(gating.get("decision_source", "unknown"))
    regime_confidence = float(regime.get("confidence", 0.0) or 0.0)
    risk_regime = str(regime.get("risk_regime", "risk_neutral"))
    topology_considered = topology is not None
    if topology_considered:
        reasons.append(f"topology_state={topology.get('state', 'unknown')}")
    else:
        reasons.append("topology_absent_v2_11_pending")

    # Priority 1: reduce_risk - portfolio-level risk lock always wins.
    if trade_lock_active:
        reasons.append(trade_lock_reason or "risk_lock_active")
        return MarketAnalysisDecision(
            action="reduce_risk",
            signal="hold",
            target_weight=0.0,
            confidence=confidence,
            probability_up=probability_up,
            trading_eligible=trading_eligible,
            topology_considered=topology_considered,
            reasons=reasons,
        )

    # Priority 2: reduce_risk - asset-level risk regime override even
    # without a portfolio-wide lock (e.g. risk_off + would-be trade).
    if risk_regime == "risk_off" and signal_name in {"buy", "sell"}:
        reasons.append("risk_off_regime_overrides_directional_signal")
        return MarketAnalysisDecision(
            action="reduce_risk",
            signal="hold",
            target_weight=0.0,
            confidence=confidence,
            probability_up=probability_up,
            trading_eligible=trading_eligible,
            topology_considered=topology_considered,
            reasons=reasons,
        )

    # Priority 3: retrain_candidate - zero experts contributing AND the
    # regime read is itself low-confidence. Stateless heuristic (no
    # trailing window yet; V2-16 will replace this with a real trigger).
    if decision_source == "baseline_fallback" and regime_confidence < retrain_min_regime_confidence:
        reasons.append("baseline_fallback_with_low_regime_confidence")
        return MarketAnalysisDecision(
            action="retrain_candidate",
            signal="hold",
            target_weight=0.0,
            confidence=confidence,
            probability_up=probability_up,
            trading_eligible=trading_eligible,
            topology_considered=topology_considered,
            reasons=reasons,
        )

    # Priority 4: trade - only for trading-eligible assets, with an
    # actionable directional signal, sufficient confidence, no lock.
    if trading_eligible and signal_name in {"buy", "sell"} and confidence >= min_confidence_to_trade:
        reasons.append("trading_eligible_directional_signal_above_confidence_threshold")
        return MarketAnalysisDecision(
            action="trade",
            signal=signal_name,
            target_weight=target_weight,
            confidence=confidence,
            probability_up=probability_up,
            trading_eligible=trading_eligible,
            topology_considered=topology_considered,
            reasons=reasons,
        )

    # Priority 5: simulate vs observe.
    if signal_name in {"buy", "sell"} and regime_confidence >= low_regime_confidence_threshold:
        if trading_eligible:
            reasons.append("confidence_below_trade_threshold_simulate_instead")
        else:
            reasons.append("observation_only_asset_directional_signal_simulate_instead")
        return MarketAnalysisDecision(
            action="simulate",
            signal=signal_name,
            target_weight=0.0,
            confidence=confidence,
            probability_up=probability_up,
            trading_eligible=trading_eligible,
            topology_considered=topology_considered,
            reasons=reasons,
        )

    reasons.append("no_actionable_edge")
    return MarketAnalysisDecision(
        action="observe",
        signal="hold",
        target_weight=0.0,
        confidence=confidence,
        probability_up=probability_up,
        trading_eligible=trading_eligible,
        topology_considered=topology_considered,
        reasons=reasons,
    )
