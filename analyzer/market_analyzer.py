"""Central market analyzer for Aether Quant V2: combines expert, regime,
topology, liquidity and risk-engine outputs into one explainable per-asset
action."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


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
    liquidity_considered: bool
    reasons: list[str]
    signal_quality_score: float = 0.0
    signal_quality_breakdown: dict = field(default_factory=dict)
    predicted_return_magnitude: float | None = None
    predicted_volatility: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def compute_signal_quality_score(
    confidence: float,
    regime_confidence: float,
    topology: dict,
    liquidity: dict,
) -> tuple[float, dict]:
    """Bounded [0,1] composite of raw model confidence, regime confidence,
    topology peer-support and liquidity friction. Always computed and
    exposed (signal_quality_score/signal_quality_breakdown) for dashboard
    visibility; only influences routing in build_market_analysis_decision()
    when use_composite_signal_score=True - see analyzer/README.md. Small
    hand-tuned weights, mirroring moe/gating.py's
    _quality_multiplier/_performance_score style - not a trained model."""
    confidence_component = _clamp01(float(confidence))
    regime_component = _clamp01(float(regime_confidence))

    correlation_strength = _clamp01(float(topology.get("correlation_strength", 0.0) or 0.0))
    topology_penalty = {"isolated": 0.3, "elevated": 0.6}.get(str(topology.get("topology_risk", "unknown")), 1.0)
    topology_component = correlation_strength * topology_penalty if topology else regime_component

    participation_rate = _clamp01(float(liquidity.get("participation_rate", 0.0) or 0.0))
    liquidity_component = _clamp01(1.0 - participation_rate) if liquidity else 1.0

    weights = {"confidence": 0.45, "regime": 0.20, "topology": 0.20, "liquidity": 0.15}
    score = (
        weights["confidence"] * confidence_component
        + weights["regime"] * regime_component
        + weights["topology"] * topology_component
        + weights["liquidity"] * liquidity_component
    )
    breakdown = {
        "confidence_component": confidence_component,
        "regime_component": regime_component,
        "topology_component": topology_component,
        "liquidity_component": liquidity_component,
        "weights": dict(weights),
    }
    return _clamp01(score), breakdown


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
    liquidity: dict | None = None,
    min_confidence_to_trade: float = 0.12,
    retrain_min_regime_confidence: float = 0.20,
    low_regime_confidence_threshold: float = 0.35,
    use_composite_signal_score: bool = False,
    predicted_return_magnitude: float | None = None,
    predicted_volatility: float | None = None,
    is_currently_invested: bool = False,
) -> MarketAnalysisDecision:
    # signal_name == "short" (Phase 3 of the 5/10 -> 9/10 roadmap,
    # portfolio/book_construction.py) is treated identically to "buy"/"sell"
    # by every safety-tier check below (`in {"buy", "sell", "short"}`) - a
    # book-selected short position passes through the exact same
    # deterministic trade-lock/risk-off/topology/liquidity categorization
    # as any other directional signal, never bypassing it. See
    # analyzer/README.md for why this categorization stays deterministic.
    reasons: list[str] = []

    # Priority 0 (evaluated before even trade-lock): closing an EXISTING
    # position is risk-REDUCING by construction, so none of the protective
    # vetoes below (trade-lock, risk-off regime, elevated topology) may
    # block it - only ever suppress a new/added exposure. Before this fix
    # they applied identically to "sell", so a risk-off regime or an
    # elevated-topology reading during exactly the periods you'd most want
    # to cut a position instead trapped it open (development/Problems.md:
    # confirmed to be why the COVID-2020 drawdown window closed zero
    # positions in the first real backtest). "sell" is the one signal that
    # universally means "close whatever is open" (main.py::_apply_signal()
    # liquidates on it regardless of long/short), so this only ever reduces
    # risk, never increases it - a "short"/"buy" signal still goes through
    # every tier below unchanged, and a "sell" with nothing currently open
    # falls through too (there's nothing to protect by fast-pathing it).
    if signal_name == "sell" and is_currently_invested:
        reasons.append("exit_signal_for_open_position_bypasses_risk_vetoes")
        bypass_quality_score, bypass_quality_breakdown = compute_signal_quality_score(
            confidence, float((regime or {}).get("confidence", 0.0) or 0.0), topology or {}, liquidity or {}
        )
        return MarketAnalysisDecision(
            action="trade",
            signal=signal_name,
            target_weight=target_weight,
            confidence=confidence,
            probability_up=probability_up,
            trading_eligible=trading_eligible,
            topology_considered=bool(topology),
            liquidity_considered=bool(liquidity),
            reasons=reasons,
            signal_quality_score=bypass_quality_score,
            signal_quality_breakdown=bypass_quality_breakdown,
            predicted_return_magnitude=predicted_return_magnitude,
            predicted_volatility=predicted_volatility,
        )
    decision_source = str(gating.get("decision_source", "unknown"))
    regime_confidence = float(regime.get("confidence", 0.0) or 0.0)
    risk_regime = str(regime.get("risk_regime", "risk_neutral"))
    topology = topology or {}
    topology_considered = bool(topology)
    topology_risk = str(topology.get("topology_risk", "unknown")) if topology_considered else "unknown"
    liquidity = liquidity or {}
    liquidity_considered = bool(liquidity)
    liquidity_action = str(liquidity.get("recommended_action", "allow")) if liquidity_considered else "allow"
    if topology_considered:
        reasons.append(f"topology_state={topology.get('state', 'unknown')}")
    else:
        reasons.append("topology_absent_v2_11_pending")

    # Always computed and exposed for dashboard visibility, regardless of
    # use_composite_signal_score - see compute_signal_quality_score()'s
    # docstring and analyzer/README.md. trade_metric is what priorities 7/8
    # actually gate on below: the composite score when the flag is on,
    # otherwise raw confidence - byte-identical to pre-flag behavior when
    # use_composite_signal_score=False (the default).
    signal_quality_score, signal_quality_breakdown = compute_signal_quality_score(
        confidence, regime_confidence, topology, liquidity
    )
    trade_metric = signal_quality_score if use_composite_signal_score else confidence

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
            liquidity_considered=liquidity_considered,
            reasons=reasons,
            signal_quality_score=signal_quality_score,
            signal_quality_breakdown=signal_quality_breakdown,
            predicted_return_magnitude=predicted_return_magnitude,
            predicted_volatility=predicted_volatility,
        )

    # Priority 2: reduce_risk - asset-level risk regime override even
    # without a portfolio-wide lock (e.g. risk_off + would-be trade).
    if risk_regime == "risk_off" and signal_name in {"buy", "sell", "short"}:
        reasons.append("risk_off_regime_overrides_directional_signal")
        return MarketAnalysisDecision(
            action="reduce_risk",
            signal="hold",
            target_weight=0.0,
            confidence=confidence,
            probability_up=probability_up,
            trading_eligible=trading_eligible,
            topology_considered=topology_considered,
            liquidity_considered=liquidity_considered,
            reasons=reasons,
            signal_quality_score=signal_quality_score,
            signal_quality_breakdown=signal_quality_breakdown,
            predicted_return_magnitude=predicted_return_magnitude,
            predicted_volatility=predicted_volatility,
        )

    # Priority 3: reduce_risk - elevated cross-sectional volatility pressure
    # from the deterministic topology layer overrides a directional signal.
    # V2-17.5 added a probabilistic topology overlay (topology.learned_topology)
    # feeding the retrain-trigger/retraining pipeline, but deliberately left
    # this rule reading only the deterministic topology_risk - see
    # analyzer/README.md and development/v2_architecture.md's V2-17.5 section.
    if topology_risk == "elevated" and signal_name in {"buy", "sell", "short"}:
        reasons.append("topology_elevated_volatility_pressure_overrides_directional_signal")
        return MarketAnalysisDecision(
            action="reduce_risk",
            signal="hold",
            target_weight=0.0,
            confidence=confidence,
            probability_up=probability_up,
            trading_eligible=trading_eligible,
            topology_considered=topology_considered,
            liquidity_considered=liquidity_considered,
            reasons=reasons,
            signal_quality_score=signal_quality_score,
            signal_quality_breakdown=signal_quality_breakdown,
            predicted_return_magnitude=predicted_return_magnitude,
            predicted_volatility=predicted_volatility,
        )

    # Priority 4: retrain_candidate - zero experts contributing AND the
    # regime read is itself low-confidence. Stateless per-bar heuristic,
    # separate from the real trailing-window retrain-trigger system V2-16/17
    # built in performance/triggers.py + retraining/ - this rule was never
    # wired to it and still isn't; see analyzer/README.md.
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
            liquidity_considered=liquidity_considered,
            reasons=reasons,
            signal_quality_score=signal_quality_score,
            signal_quality_breakdown=signal_quality_breakdown,
            predicted_return_magnitude=predicted_return_magnitude,
            predicted_volatility=predicted_volatility,
        )

    # Priority 5: simulate - liquidity blocked (zero volume or DDV below
    # the floor). An unexecutable order must not reach the order book.
    # See V2-18 for future data-driven calibration of these thresholds.
    if liquidity_action == "block" and signal_name in {"buy", "sell", "short"}:
        reasons.append("liquidity_blocked_insufficient_volume_simulate_instead")
        return MarketAnalysisDecision(
            action="simulate",
            signal=signal_name,
            target_weight=0.0,
            confidence=confidence,
            probability_up=probability_up,
            trading_eligible=trading_eligible,
            topology_considered=topology_considered,
            liquidity_considered=liquidity_considered,
            reasons=reasons,
            signal_quality_score=signal_quality_score,
            signal_quality_breakdown=signal_quality_breakdown,
            predicted_return_magnitude=predicted_return_magnitude,
            predicted_volatility=predicted_volatility,
        )

    # Priority 6: simulate - thin market; participation rate would be
    # uncomfortably large relative to daily volume.
    if liquidity_action == "simulate_instead" and signal_name in {"buy", "sell", "short"}:
        reasons.append("liquidity_thin_market_simulate_instead")
        return MarketAnalysisDecision(
            action="simulate",
            signal=signal_name,
            target_weight=0.0,
            confidence=confidence,
            probability_up=probability_up,
            trading_eligible=trading_eligible,
            topology_considered=topology_considered,
            liquidity_considered=liquidity_considered,
            reasons=reasons,
            signal_quality_score=signal_quality_score,
            signal_quality_breakdown=signal_quality_breakdown,
            predicted_return_magnitude=predicted_return_magnitude,
            predicted_volatility=predicted_volatility,
        )

    # Priority 7: trade - only for trading-eligible assets with an actionable
    # directional signal, sufficient confidence, no topology isolation, and
    # no liquidity block (redundant guard — tiers 5/6 already caught those).
    # Gates on trade_metric, not raw confidence directly - see trade_metric's
    # definition above (identical to confidence unless
    # use_composite_signal_score=True).
    if (
        trading_eligible
        and signal_name in {"buy", "sell", "short"}
        and trade_metric >= min_confidence_to_trade
        and topology_risk != "isolated"
        and liquidity_action not in {"block", "simulate_instead"}
    ):
        reasons.append("trading_eligible_directional_signal_above_confidence_threshold")
        return MarketAnalysisDecision(
            action="trade",
            signal=signal_name,
            target_weight=target_weight,
            confidence=confidence,
            probability_up=probability_up,
            trading_eligible=trading_eligible,
            topology_considered=topology_considered,
            liquidity_considered=liquidity_considered,
            reasons=reasons,
            signal_quality_score=signal_quality_score,
            signal_quality_breakdown=signal_quality_breakdown,
            predicted_return_magnitude=predicted_return_magnitude,
            predicted_volatility=predicted_volatility,
        )

    # Priority 8: simulate vs observe.
    if signal_name in {"buy", "sell", "short"} and regime_confidence >= low_regime_confidence_threshold:
        if topology_risk == "isolated":
            reasons.append("topology_isolated_asset_lacks_peer_confirmation_simulate_instead")
        elif trading_eligible:
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
            liquidity_considered=liquidity_considered,
            reasons=reasons,
            signal_quality_score=signal_quality_score,
            signal_quality_breakdown=signal_quality_breakdown,
            predicted_return_magnitude=predicted_return_magnitude,
            predicted_volatility=predicted_volatility,
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
        liquidity_considered=liquidity_considered,
        reasons=reasons,
        signal_quality_score=signal_quality_score,
        signal_quality_breakdown=signal_quality_breakdown,
    )
