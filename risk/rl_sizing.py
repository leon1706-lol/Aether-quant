"""Offline-trained contextual-bandit sizing overlay (development/Problems.md
#71, Phase 4.12, Component E) - a SHRINK-ONLY multiplier layered on top of
risk/position_sizing.py::build_dynamic_position_sizing()'s output, never
replacing it. Pure Python, no numpy/torch at runtime, matching
topology/learned_topology.py's exact "pure inference, model trained offline,
degrades to a strict no-op when the model is missing/malformed/disabled"
split.

Honest framing, not oversold (see train_rl_sizing.py's own module docstring
for the full data-source story): this is a full-information contextual
bandit fit offline over ml/datasets/*.csv (the SAME rows train.py already
builds), NOT online/off-policy reinforcement learning against live
exploration data - main.py has never logged a stochastic sizing action, and
risk/position_sizing.py's own established rule (topology_sizing_multiplier()'s
docstring) forbids ever randomizing a live sizing decision. The offline
reward for every candidate action is computable in closed form from the
already-known forward return, so no exploration is needed to fit this - see
train_rl_sizing.py.

What this CAN plausibly do: learn to shrink size in STATE-CONDITIONAL
low-edge regimes (e.g. high implied volatility + backwardation + tightening
financial conditions - exactly the alt-data features Problems.md #71's
Component D added), reducing turnover/fees in the states this project's own
Backtest 1 measured were the most costly. What it CANNOT do: manufacture
alpha where none exists - if the underlying signal doesn't clear costs
anywhere, the reward-maximizing policy over a shrink-only action set
degenerates to "always pick the smallest multiplier," which is a `max_*_multiplier`
config change, not a model, and is the intended "give up gracefully" behavior,
not a bug.

Default OFF (phase_v2.dynamic_risk.rl_sizing_enabled) - see
risk/position_sizing.py's rl_multiplier param and main.py's wiring."""

from __future__ import annotations

import json
from pathlib import Path

# Fixed, order-significant state key list - the trained artifact carries
# its OWN copy of this same list (model["state_keys"]) and
# rl_sizing_multiplier() below refuses to score anything (falls back to
# 1.0) if the two disagree, rather than silently reordering/misaligning
# a state vector against weights trained for a different order. Every key
# here is already computed once per bar as part of the existing base
# feature/topology payload - no new computation, no new data source.
RL_SIZING_STATE_KEYS = [
    "confidence",
    "rolling_volatility_20d",
    "regime_signal_risk_score",
    "topology_correlation_strength",
    "liquidity_spread_proxy",
    "bond_credit_spread_level",
    "alt_implied_volatility_level",
    "alt_implied_vol_term_structure",
    "alt_financial_conditions_change",
]

DEFAULT_MIN_RL_MULTIPLIER = 0.6
DEFAULT_MAX_RL_MULTIPLIER = 1.0


def build_rl_sizing_state(base_features: dict, confidence: float) -> dict | None:
    """Pulls RL_SIZING_STATE_KEYS out of the SAME base_features dict
    main.py's _build_model_input_impl() already assembled this bar (plus
    the model's own separately-computed confidence score, not itself a
    base_feature) - no new computation, no new data source. Returns None
    if any key is absent (e.g. Component D's alt-data features not yet in
    input_set/retrained), which rl_sizing_multiplier() treats identically
    to "no model" - a strict 1.0 no-op, never a crash or a partially-built
    state vector."""
    state = {}
    for key in RL_SIZING_STATE_KEYS:
        if key == "confidence":
            continue
        if key not in base_features:
            return None
        state[key] = float(base_features[key])
    state["confidence"] = float(confidence)
    return state


def _softmax_argmax_index(scores: list[float]) -> int:
    """Deterministic argmax - NOT a sampled draw from the softmax
    distribution. topology_sizing_multiplier()'s docstring establishes the
    project-wide rule this module also follows: "probabilistic scoring may
    only ever produce a bounded, continuous adjustment, never a randomized
    or amplified decision." A stochastic policy is legitimate during
    OFFLINE training (see train_rl_sizing.py - exploration there costs
    nothing, it's arithmetic over historical rows) and forbidden at live
    inference. Ties broken toward the LAST action with the max score - by
    convention the action list is built low-to-high multiplier
    (see rl_sizing_multiplier()), so a tie prefers the larger (less
    aggressive shrink) multiplier, matching a zero-initialized/untrained
    model's intended "prefer no-op" default."""
    best_index = 0
    best_score = scores[0]
    for index, score in enumerate(scores):
        if score >= best_score:
            best_score = score
            best_index = index
    return best_index


def rl_sizing_multiplier(
    model: dict | None,
    state: dict | None,
    rl_sizing_enabled: bool,
    min_rl_multiplier: float = DEFAULT_MIN_RL_MULTIPLIER,
    max_rl_multiplier: float = DEFAULT_MAX_RL_MULTIPLIER,
) -> tuple[float, str]:
    """Bounded, deterministic (argmax, never sampled), shrink-only size
    adjustment - exact contract clone of
    risk/position_sizing.py::rank_sizing_multiplier()/topology_sizing_multiplier():
    returns (1.0, "<reason>") whenever the flag is off, the model is
    missing/malformed, the state is incomplete, or the model's own
    state_keys disagree with RL_SIZING_STATE_KEYS - every failure mode is a
    strict no-op, never a crash and never an amplified size.

    THREE safety properties, all enforced HERE rather than trusted from the
    artifact (an untrusted/stale/hand-edited model file must never be able
    to violate them):
    1. Argmax, never sampled - see _softmax_argmax_index()'s docstring.
    2. Clamped to [min_rl_multiplier, max_rl_multiplier] AFTER the argmax,
       so a corrupted/adversarial action table can never emit a
       multiplier outside the configured band, regardless of what the
       model file claims its own actions are.
    3. max_rl_multiplier defaults to 1.0 - SHRINK-ONLY, matching
       topology_sizing_multiplier()'s "never amplifies size beyond what
       deterministic-only sizing already computed" rule. Amplification
       (max_rl_multiplier > 1.0) is technically possible via config but
       is NOT the shipped/recommended posture for v1 - see
       development/Problems.md #71's abandon criteria."""
    if not rl_sizing_enabled or model is None or state is None:
        return 1.0, "rl_sizing_disabled_or_absent"

    try:
        state_keys = model.get("state_keys")
        actions = model.get("actions")
        weights = model.get("weights")
        bias = model.get("bias")
        mean = model.get("mean")
        scale = model.get("scale")
        if state_keys != RL_SIZING_STATE_KEYS:
            return 1.0, "rl_sizing_state_key_mismatch"
        if not actions or not weights or not bias or not mean or not scale:
            return 1.0, "rl_sizing_malformed_model"
        if len(weights) != len(actions) or len(bias) != len(actions):
            return 1.0, "rl_sizing_malformed_model"

        standardized = []
        for key, mean_value, scale_value in zip(state_keys, mean, scale):
            raw = float(state[key])
            denominator = float(scale_value) if float(scale_value) != 0.0 else 1.0
            standardized.append((raw - float(mean_value)) / denominator)

        scores = []
        for action_weights, action_bias in zip(weights, bias):
            if len(action_weights) != len(standardized):
                return 1.0, "rl_sizing_malformed_model"
            score = float(action_bias) + sum(w * x for w, x in zip(action_weights, standardized))
            scores.append(score)

        best_index = _softmax_argmax_index(scores)
        raw_multiplier = float(actions[best_index])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return 1.0, "rl_sizing_malformed_model"

    clamped = max(float(min_rl_multiplier), min(raw_multiplier, float(max_rl_multiplier)))
    return clamped, "rl_sizing_policy_scaled_sizing"


def load_rl_sizing_model(path: Path) -> dict | None:
    """Missing file -> None (fresh checkout / never trained - the
    documented default state). Malformed JSON -> None (never raises).
    Mirrors main.py's own "missing/malformed model -> None, never a hard
    failure" convention already established for every other optional
    learned artifact (topology, gating, experts)."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
