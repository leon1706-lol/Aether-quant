"""Learned/probabilistic topology overlay for Aether Quant V2-17.5.

Adds a data-driven, probabilistic layer on top of - never in place of - the
deterministic topology in market_topology.py: cluster probabilities,
confidence/uncertainty, a stress score, and small bounded 3D offsets. Pure
Python, no numpy/sklearn at runtime (matches market_topology.py, regime/,
liquidity/): the model is trained offline (see train_topology.py) and loaded
as a plain JSON dict; this module never touches a file and never raises,
degrading node-by-node - and, in the worst case, entirely - to the
deterministic baseline when the model is missing, malformed, or not
confident enough.

"Non-deterministic" here means probabilistic scoring, not randomized
behavior: every function is a deterministic function of its inputs (no RNG).
Trading actions never read the new fields this module adds -
analyzer/market_analyzer.py continues to consume only topology_risk/state,
exactly as produced by the unchanged deterministic layer.

Prototype offsets (development/Problems.md #56) have an intentionally
asymmetric contract: x/y are absolute scene units, clamped straight to
max_offset_xy, because x/y's scale never changes between
market_topology.py's 2D and 3D (V4-W3) embedding modes. z is normalized
to [-1, 1] and multiplied by max_offset_z before clamping, because z is
the one axis whose scene scale *does* change between modes (a 0..1
volatility encoding in 2D, a 0..100 spatial axis in 3D) - a raw offset
tuned for one scale would be meaningless, or effectively zero, on the
other.
"""

from __future__ import annotations

import math

FEATURE_KEYS = ("volatility", "momentum", "correlation_strength", "liquidity_score", "regime_risk_score")
TOPOLOGY_SOURCES = ("deterministic", "learned", "hybrid", "fallback")

DEFAULT_TEMPERATURE = 0.35
DEFAULT_TOP_N_NEIGHBORS = 3
DEFAULT_MIN_CONFIDENCE_FOR_LEARNED = 0.2
DEFAULT_MAX_OFFSET_XY = 6.0
DEFAULT_MAX_OFFSET_Z = 0.1

_FALLBACK_NODE_FIELDS = {
    "topology_source": "fallback",
    "cluster_probs": {},
    "topology_confidence": 0.0,
    "topology_uncertainty": 1.0,
    "stress_score": 0.0,
    "neighbor_shift_score": 0.0,
    "topology_disagreement": 0.0,
    "learned_neighbors": [],
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _normalize(vector: dict, feature_stats: dict) -> dict:
    normalized = {}
    for key in FEATURE_KEYS:
        value = float(vector.get(key, 0.0) or 0.0)
        key_stats = feature_stats.get(key) or {}
        mean = float(key_stats.get("mean", 0.0) or 0.0)
        std = float(key_stats.get("std", 0.0) or 0.0) or 1.0
        normalized[key] = (value - mean) / std
    return normalized


def _euclidean_distance(a: dict, b: dict) -> float:
    return math.sqrt(sum((value - float(b.get(key, 0.0) or 0.0)) ** 2 for key, value in a.items()))


def _softmax_neg_distances(distances: dict, temperature: float) -> dict:
    if not distances:
        return {}
    temperature = max(float(temperature), 1e-6)
    scaled = {key: -value / temperature for key, value in distances.items()}
    peak = max(scaled.values())
    exponentials = {key: math.exp(value - peak) for key, value in scaled.items()}
    total = sum(exponentials.values()) or 1.0
    return {key: value / total for key, value in exponentials.items()}


def _normalized_entropy(probabilities: dict) -> float:
    count = len(probabilities)
    if count <= 1:
        return 0.0
    entropy = -sum(p * math.log(p) for p in probabilities.values() if p > 0.0)
    return _clamp(entropy / math.log(count), 0.0, 1.0)


def _jaccard_distance(a: set, b: set) -> float:
    union = a | b
    if not union:
        return 0.0
    return 1.0 - (len(a & b) / len(union))


def _apply_offset(base: float, offset: float, confidence: float, max_shift: float) -> float:
    return base + _clamp(offset * confidence, -max_shift, max_shift)


def liquidity_score_from_decision(liquidity: dict) -> float:
    """Maps a liquidity.market_liquidity.LiquidityDecision-shaped dict (or
    any dict carrying participation_rate/estimated_slippage) into a single
    0..1 liquidity_score feature - higher is more liquid. Shared by
    train_topology.py (offline training) and main.py (runtime) so both
    sides compute this feature identically."""
    liquidity = liquidity or {}
    participation_rate = float(liquidity.get("participation_rate", 0.0) or 0.0)
    slippage = float(liquidity.get("estimated_slippage", 0.0) or 0.0)
    return _clamp(1.0 - min(1.0, participation_rate * 10.0 + slippage * 5.0), 0.0, 1.0)


def _neighbor_probabilities(symbol: str, normalized_by_symbol: dict, temperature: float) -> dict:
    own = normalized_by_symbol.get(symbol)
    if own is None:
        return {}
    distances = {
        other: _euclidean_distance(own, vector) for other, vector in normalized_by_symbol.items() if other != symbol
    }
    return _softmax_neg_distances(distances, temperature)


def _score_node(
    node: dict,
    normalized_by_symbol: dict,
    prototypes: list,
    distance_scale: float,
    cluster_dominant_regime_label: str,
    cluster_peers: set,
    previous_neighbors: set,
    *,
    temperature: float,
    top_n_neighbors: int,
    min_confidence_for_learned: float,
    max_offset_xy: float,
    max_offset_z: float,
) -> dict:
    """Pure per-node scoring against a trained prototype set. Raises on
    malformed inputs - callers catch and fall back per-node."""
    symbol = node["symbol"]
    own_normalized = normalized_by_symbol[symbol]

    distances = {
        str(prototype.get("label")): _euclidean_distance(own_normalized, prototype.get("centroid") or {})
        for prototype in prototypes
    }
    cluster_probs = _softmax_neg_distances(distances, temperature)
    confidence = max(cluster_probs.values()) if cluster_probs else 0.0
    uncertainty = _normalized_entropy(cluster_probs)
    stress = _clamp(min(distances.values()) / distance_scale, 0.0, 1.0) if distances else 0.0

    nearest_label = max(cluster_probs, key=lambda key: cluster_probs[key]) if cluster_probs else None
    nearest_prototype = next((p for p in prototypes if str(p.get("label")) == nearest_label), {})

    neighbor_probs = _neighbor_probabilities(symbol, normalized_by_symbol, temperature)
    learned_neighbors = sorted(neighbor_probs, key=lambda other: (-neighbor_probs[other], other))[:top_n_neighbors]
    neighbor_shift = _jaccard_distance(set(learned_neighbors), previous_neighbors)

    nearest_regime = nearest_prototype.get("dominant_regime_label", "unknown")
    regime_mismatch = 1.0 if nearest_regime != cluster_dominant_regime_label else 0.0
    peer_overlap_distance = _jaccard_distance(set(learned_neighbors), cluster_peers)
    disagreement = 0.5 * regime_mismatch + 0.5 * peer_overlap_distance

    node = dict(node)
    if confidence >= min_confidence_for_learned:
        node["topology_source"] = "learned"
        offset = nearest_prototype.get("offset") or {}
        node["x"] = _apply_offset(float(node.get("x", 0.0)), float(offset.get("x", 0.0)), confidence, max_offset_xy)
        node["y"] = _apply_offset(float(node.get("y", 0.0)), float(offset.get("y", 0.0)), confidence, max_offset_xy)
        # z is normalized to [-1, 1] by train_topology.py (module
        # docstring above), unlike x/y's already-absolute scene units -
        # scale it into scene units by max_offset_z before the same
        # confidence-weighted clamp x/y already go through.
        node["z"] = _apply_offset(
            float(node.get("z", 0.0)), float(offset.get("z", 0.0)) * max_offset_z, confidence, max_offset_z
        )
    else:
        node["topology_source"] = "fallback"

    node.update(
        cluster_probs=cluster_probs,
        topology_confidence=confidence,
        topology_uncertainty=uncertainty,
        stress_score=stress,
        neighbor_shift_score=neighbor_shift,
        topology_disagreement=disagreement,
        learned_neighbors=learned_neighbors,
    )
    return node, learned_neighbors


def apply_learned_topology(
    deterministic_topology: dict,
    symbol_features: dict[str, dict] | None = None,
    previous_neighbors_by_symbol: dict[str, list[str]] | None = None,
    model: dict | None = None,
    feature_schema: dict | None = None,
    *,
    temperature: float = DEFAULT_TEMPERATURE,
    top_n_neighbors: int = DEFAULT_TOP_N_NEIGHBORS,
    min_confidence_for_learned: float = DEFAULT_MIN_CONFIDENCE_FOR_LEARNED,
    max_offset_xy: float = DEFAULT_MAX_OFFSET_XY,
    max_offset_z: float = DEFAULT_MAX_OFFSET_Z,
) -> dict:
    """Overlay learned cluster probabilities/uncertainty/offsets on top of a
    deterministic MarketTopology.to_dict()-shaped payload.

    Never raises. Falls back to the deterministic node unchanged (position
    untouched, diagnostic fields zeroed) whenever the model is missing, a
    symbol has no current-bar features, or the model's confidence for that
    symbol is below `min_confidence_for_learned`.
    """
    symbol_features = symbol_features or {}
    previous_neighbors_by_symbol = previous_neighbors_by_symbol or {}
    reasons = list(deterministic_topology.get("reasons") or [])

    deterministic_nodes = deterministic_topology.get("nodes") or []
    clusters = deterministic_topology.get("clusters") or []
    cluster_regime_by_id = {cluster.get("cluster_id"): cluster.get("dominant_regime_label", "unknown") for cluster in clusters}
    cluster_members_by_id = {cluster.get("cluster_id"): set(cluster.get("members") or []) for cluster in clusters}

    feature_stats = (feature_schema or {}).get("feature_stats") or {}
    prototypes = (model or {}).get("prototypes") or []
    distance_scale = float((model or {}).get("distance_scale") or 0.0) or 1.0
    model_version_id = (model or {}).get("version_id")
    # development/Problems.md #56: detection hook for the prototypes[].offset
    # format, distinct from model_version_id (a pipeline run identity, not a
    # schema version). None for any model trained before this field existed.
    model_offset_schema = (model or {}).get("offset_schema")

    model_loaded = bool(model) and bool(feature_schema) and bool(prototypes) and bool(feature_stats)
    if not model_loaded:
        reasons.append("learned_topology_model_missing")

    normalized_by_symbol: dict[str, dict] = {}
    if model_loaded:
        for symbol, vector in symbol_features.items():
            try:
                normalized_by_symbol[symbol] = _normalize(vector, feature_stats)
            except Exception:
                continue

    learned_neighbors_by_symbol: dict[str, list[str]] = {}
    nodes_out = []

    for node in deterministic_nodes:
        symbol = node.get("symbol")
        cluster_id = node.get("cluster_id")
        cluster_dominant_regime_label = cluster_regime_by_id.get(cluster_id, node.get("regime_label", "unknown"))
        cluster_peers = cluster_members_by_id.get(cluster_id, set()) - {symbol}

        node = dict(node)
        node["cluster_dominant_regime_label"] = cluster_dominant_regime_label

        if not model_loaded or symbol not in normalized_by_symbol:
            node.update(_FALLBACK_NODE_FIELDS)
            nodes_out.append(node)
            continue

        try:
            previous_neighbors = set(previous_neighbors_by_symbol.get(symbol, []))
            scored_node, learned_neighbors = _score_node(
                node,
                normalized_by_symbol,
                prototypes,
                distance_scale,
                cluster_dominant_regime_label,
                cluster_peers,
                previous_neighbors,
                temperature=temperature,
                top_n_neighbors=top_n_neighbors,
                min_confidence_for_learned=min_confidence_for_learned,
                max_offset_xy=max_offset_xy,
                max_offset_z=max_offset_z,
            )
            learned_neighbors_by_symbol[symbol] = learned_neighbors
            nodes_out.append(scored_node)
        except Exception:
            node.update(_FALLBACK_NODE_FIELDS)
            nodes_out.append(node)

    node_sources = {node.get("topology_source") for node in nodes_out}
    if not nodes_out or not model_loaded or node_sources == {"fallback"}:
        topology_source = "fallback"
    elif node_sources == {"learned"}:
        topology_source = "learned"
    else:
        topology_source = "hybrid"

    result = dict(deterministic_topology)
    result["nodes"] = nodes_out
    result["reasons"] = reasons
    result["topology_source"] = topology_source
    result["model_loaded"] = model_loaded
    result["model_version_id"] = model_version_id
    result["model_offset_schema"] = model_offset_schema
    result["learned_neighbors_by_symbol"] = learned_neighbors_by_symbol
    return result
