"""Runtime inference for the learned multi-leg strategy-selector model
(V4.7, development/Problems.md #29's own framing - a model that picks
which enabled strategy to prefer, replacing/augmenting
portfolio/options_strategy.py::order_enabled_strategies()'s static
risk-tier-preference reordering).

Pure Python, no numpy/sklearn at runtime - same "trained offline
(train_strategy_selector.py), loaded as a plain JSON dict, degrades
node-by-node (here: strategy-by-strategy) to an empty score dict when
missing/malformed" split topology/learned_topology.py already establishes
for the topology model. Never raises -
risk/asset_class_router.py::route_multi_leg_option_sizing() falls back to
today's exact order_enabled_strategies() ordering whenever this module
returns {} (its only output when no trained model exists, which is the
ONLY state this codebase can reach today - see train_strategy_selector.py's
own module docstring for why: zero real option positions have ever
traded, so there is no per-strategy realized-outcome data to train from
yet).
"""

from __future__ import annotations

FEATURE_KEYS = ("regime_risk_score", "regime_trend_score", "topology_correlation_strength")


def build_strategy_selector_features(base_features: dict, topology: dict) -> dict[str, float]:
    """Pure, degrade-to-0.0 feature extraction reusing values main.py
    already computes every bar (base_features["regime_signal_risk_score"/
    "regime_signal_trend_score"], topology["correlation_strength"]) -
    deliberately NOT a new computation path, so this feature vector stays
    in lockstep with whatever the main probability model itself already
    sees, and needs no additional per-bar state. Never raises on a
    missing key. Key names here (bare, e.g. "regime_risk_score") match
    train_strategy_selector.py's own extraction from a persisted
    option_strategy_outcome event's regime/topology sub-payloads (which
    use the SAME bare key names main.py's regime_payload/topology_payload
    dicts do, before base_features's own "regime_signal_"/"topology_"
    prefixing) - the trainer and this runtime scorer must always agree on
    FEATURE_KEYS; this module owns that contract for the runtime side."""
    return {
        "regime_risk_score": float(base_features.get("regime_signal_risk_score", 0.0) or 0.0),
        "regime_trend_score": float(base_features.get("regime_signal_trend_score", 0.0) or 0.0),
        "topology_correlation_strength": float((topology or {}).get("correlation_strength", 0.0) or 0.0),
    }


def score_strategies(model: dict | None, features: dict[str, float]) -> dict[str, float]:
    """model is train_strategy_selector.py's own strategy_selector_model.json
    payload: {"strategy_names": [...], "scorers": {name: {"weights":
    {feature_key: w}, "bias": b}}, "feature_keys": [...]}. Returns {}
    (never raises) when model is None/empty/malformed - the exact
    byte-identical-default trigger
    risk/asset_class_router.py::route_multi_leg_option_sizing() relies on
    (falls back to order_enabled_strategies() whenever this is falsy).
    Otherwise a plain linear score per strategy_name: bias + sum(weight *
    feature_value) - deliberately simple (this is a brand-new,
    realistically-always-under-threshold data stream, per
    train_strategy_selector.py's own docstring - not worth a more complex
    runtime scorer until real training data exists to justify one)."""
    if not model:
        return {}
    scorers = model.get("scorers")
    if not scorers:
        return {}

    scores: dict[str, float] = {}
    for strategy_name, scorer in scorers.items():
        try:
            weights = scorer.get("weights", {})
            bias = float(scorer.get("bias", 0.0))
            score = bias + sum(float(weights.get(key, 0.0)) * float(value) for key, value in features.items())
        except (TypeError, ValueError, AttributeError):
            continue
        scores[strategy_name] = score
    return scores
