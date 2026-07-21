"""Tests for topology.learned_topology — V2-17.5.

Conventions: no test classes, module-level fixture helpers, plain dicts
(same style as tests/test_market_topology.py and tests/test_triggers.py).
"""

import math

from topology.learned_topology import (
    TOPOLOGY_SOURCES,
    _jaccard_distance,
    _normalized_entropy,
    _softmax_neg_distances,
    apply_learned_topology,
)
from topology.market_topology import build_market_topology


def _series(values: list[float], length: int = 8) -> list[float]:
    repeats = (length // len(values)) + 1
    return (values * repeats)[:length]


def _sample_deterministic_topology() -> dict:
    base = _series([0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.03, -0.025])
    returns = {
        "AAA": base,
        "BBB": [value * 1.05 for value in base],
        "CCC": _series([-0.04, 0.05, -0.06, 0.07, -0.03, 0.02, -0.05, 0.04]),
    }
    regime_labels = {"AAA": "bullish", "BBB": "bullish", "CCC": "bearish"}
    topology = build_market_topology(returns, regime_labels_by_symbol=regime_labels, correlation_threshold=0.6)
    return topology.to_dict()


def _sample_feature_schema() -> dict:
    return {
        "feature_stats": {
            "volatility": {"mean": 0.2, "std": 0.1},
            "momentum": {"mean": 0.0, "std": 0.02},
            "correlation_strength": {"mean": 0.5, "std": 0.2},
            "liquidity_score": {"mean": 0.5, "std": 0.2},
            "regime_risk_score": {"mean": 0.0, "std": 1.0},
        }
    }


def _sample_model(version_id: str = "v1") -> dict:
    return {
        "version_id": version_id,
        "distance_scale": 2.0,
        "prototypes": [
            {
                "label": "proto_risk_on",
                "centroid": {
                    "volatility": -0.5,
                    "momentum": 0.5,
                    "correlation_strength": 0.5,
                    "liquidity_score": 0.5,
                    "regime_risk_score": -0.5,
                },
                "dominant_regime_label": "bullish",
                "offset": {"x": 3.0, "y": -2.0, "z": 0.05},
            },
            {
                "label": "proto_risk_off",
                "centroid": {
                    "volatility": 1.5,
                    "momentum": -1.0,
                    "correlation_strength": -0.5,
                    "liquidity_score": -0.5,
                    "regime_risk_score": 1.0,
                },
                "dominant_regime_label": "bearish",
                "offset": {"x": -3.0, "y": 2.0, "z": -0.05},
            },
        ],
    }


def _sample_symbol_features(topology: dict) -> dict:
    return {
        node["symbol"]: {
            "volatility": node["volatility_pressure"],
            "momentum": 0.01,
            "correlation_strength": node["correlation_strength"],
            "liquidity_score": 0.6,
            "regime_risk_score": -0.4 if node["regime_label"] == "bullish" else 0.6,
        }
        for node in topology["nodes"]
    }


_REQUIRED_TOP_LEVEL_KEYS = {
    "state",
    "nodes",
    "links",
    "clusters",
    "dimensions",
    "reasons",
    "topology_source",
    "model_loaded",
    "model_version_id",
    "learned_neighbors_by_symbol",
}
_REQUIRED_NODE_KEYS = {
    "symbol",
    "cluster_id",
    "x",
    "y",
    "z",
    "topology_source",
    "cluster_probs",
    "topology_confidence",
    "topology_uncertainty",
    "stress_score",
    "neighbor_shift_score",
    "topology_disagreement",
    "learned_neighbors",
    "cluster_dominant_regime_label",
}


def test_apply_learned_topology_returns_stable_schema_with_model():
    topology = _sample_deterministic_topology()
    result = apply_learned_topology(
        topology, _sample_symbol_features(topology), {}, _sample_model(), _sample_feature_schema()
    )

    assert _REQUIRED_TOP_LEVEL_KEYS <= set(result.keys())
    for node in result["nodes"]:
        assert _REQUIRED_NODE_KEYS <= set(node.keys())
    assert result["topology_source"] in TOPOLOGY_SOURCES


def test_apply_learned_topology_returns_stable_schema_without_model():
    topology = _sample_deterministic_topology()
    result = apply_learned_topology(topology, {}, None, None, None)

    assert _REQUIRED_TOP_LEVEL_KEYS <= set(result.keys())
    for node in result["nodes"]:
        assert _REQUIRED_NODE_KEYS <= set(node.keys())
    assert result["topology_source"] in TOPOLOGY_SOURCES


def test_fallback_activates_when_model_missing():
    topology = _sample_deterministic_topology()
    original_positions = {node["symbol"]: (node["x"], node["y"], node["z"]) for node in topology["nodes"]}

    result = apply_learned_topology(topology, _sample_symbol_features(topology), {}, None, None)

    assert result["topology_source"] == "fallback"
    assert result["model_loaded"] is False
    for node in result["nodes"]:
        assert node["topology_source"] == "fallback"
        assert (node["x"], node["y"], node["z"]) == original_positions[node["symbol"]]


def test_fallback_activates_when_confidence_low():
    topology = _sample_deterministic_topology()
    features = _sample_symbol_features(topology)
    equidistant_centroid = {
        "volatility": 0.0,
        "momentum": 0.0,
        "correlation_strength": 0.0,
        "liquidity_score": 0.0,
        "regime_risk_score": 0.0,
    }
    model = {
        "version_id": "v-uniform",
        "distance_scale": 2.0,
        "prototypes": [
            {
                "label": f"proto_{index}",
                "centroid": dict(equidistant_centroid),
                "dominant_regime_label": "unknown",
                "offset": {"x": 0.0, "y": 0.0, "z": 0.0},
            }
            for index in range(6)
        ],
    }

    result = apply_learned_topology(topology, features, {}, model, _sample_feature_schema())

    assert result["model_loaded"] is True
    for node in result["nodes"]:
        assert node["topology_source"] == "fallback"
        assert node["topology_confidence"] < 0.2


def test_topology_source_is_hybrid_when_some_symbols_lack_features():
    topology = _sample_deterministic_topology()
    features = _sample_symbol_features(topology)
    first_symbol = topology["nodes"][0]["symbol"]
    features_missing_one = {symbol: vector for symbol, vector in features.items() if symbol != first_symbol}

    result = apply_learned_topology(topology, features_missing_one, {}, _sample_model(), _sample_feature_schema())

    assert result["topology_source"] == "hybrid"
    fallback_node = next(node for node in result["nodes"] if node["symbol"] == first_symbol)
    assert fallback_node["topology_source"] == "fallback"


def test_softmax_neg_distances_sums_to_one_and_favors_closer_prototype():
    probs = _softmax_neg_distances({"near": 0.1, "far": 5.0}, temperature=0.5)

    assert math.isclose(sum(probs.values()), 1.0, rel_tol=1e-9)
    assert probs["near"] > probs["far"]


def test_softmax_neg_distances_empty_input_returns_empty():
    assert _softmax_neg_distances({}, temperature=0.5) == {}


def test_normalized_entropy_zero_for_single_prototype():
    assert _normalized_entropy({"only": 1.0}) == 0.0


def test_normalized_entropy_is_one_for_uniform_distribution():
    uniform = {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}
    assert math.isclose(_normalized_entropy(uniform), 1.0, rel_tol=1e-9)


def test_normalized_entropy_lower_for_peaked_distribution():
    peaked = {"a": 0.9, "b": 0.05, "c": 0.05}
    uniform = {"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}
    assert _normalized_entropy(peaked) < _normalized_entropy(uniform)


def test_jaccard_distance_identical_sets_is_zero():
    assert _jaccard_distance({"AAA", "BBB"}, {"AAA", "BBB"}) == 0.0


def test_jaccard_distance_disjoint_sets_is_one():
    assert _jaccard_distance({"AAA"}, {"BBB"}) == 1.0


def test_jaccard_distance_empty_sets_is_zero():
    assert _jaccard_distance(set(), set()) == 0.0


def test_stress_score_clamped_to_one_when_far_from_all_prototypes():
    topology = _sample_deterministic_topology()
    features = _sample_symbol_features(topology)
    far_centroid = {
        "volatility": 100.0,
        "momentum": 100.0,
        "correlation_strength": 100.0,
        "liquidity_score": 100.0,
        "regime_risk_score": 100.0,
    }
    model = {
        "version_id": "v-far",
        "distance_scale": 0.001,
        "prototypes": [
            {"label": "far", "centroid": far_centroid, "dominant_regime_label": "unknown", "offset": {"x": 0, "y": 0, "z": 0}}
        ],
    }

    result = apply_learned_topology(topology, features, {}, model, _sample_feature_schema())

    for node in result["nodes"]:
        assert 0.0 <= node["stress_score"] <= 1.0
        assert node["stress_score"] == 1.0


def test_learned_offset_bounded_by_max_shift():
    topology = _sample_deterministic_topology()
    features = _sample_symbol_features(topology)
    model = {
        "version_id": "v-offset",
        "distance_scale": 5.0,
        "prototypes": [
            {
                "label": "only",
                "centroid": {
                    "volatility": 0.0,
                    "momentum": 0.0,
                    "correlation_strength": 0.0,
                    "liquidity_score": 0.0,
                    "regime_risk_score": 0.0,
                },
                "dominant_regime_label": "unknown",
                "offset": {"x": 999.0, "y": -999.0, "z": 999.0},
            }
        ],
    }
    original_by_symbol = {node["symbol"]: node for node in topology["nodes"]}

    result = apply_learned_topology(
        topology, features, {}, model, _sample_feature_schema(), max_offset_xy=6.0, max_offset_z=0.1
    )

    for node in result["nodes"]:
        base = original_by_symbol[node["symbol"]]
        assert node["topology_source"] == "learned"
        assert abs(node["x"] - base["x"]) <= 6.0 + 1e-9
        assert abs(node["y"] - base["y"]) <= 6.0 + 1e-9
        assert abs(node["z"] - base["z"]) <= 0.1 + 1e-9


def test_neighbor_shift_score_is_zero_when_previous_neighbors_match():
    topology = _sample_deterministic_topology()
    features = _sample_symbol_features(topology)
    model = _sample_model()
    schema = _sample_feature_schema()

    first_pass = apply_learned_topology(topology, features, {}, model, schema)
    learned_neighbors = first_pass["learned_neighbors_by_symbol"]

    second_pass = apply_learned_topology(topology, features, learned_neighbors, model, schema)

    for node in second_pass["nodes"]:
        if node["symbol"] in learned_neighbors:
            assert node["neighbor_shift_score"] == 0.0


def test_never_raises_on_malformed_model():
    topology = _sample_deterministic_topology()
    features = _sample_symbol_features(topology)
    malformed_models = [
        {},
        {"prototypes": []},
        {"prototypes": "not-a-list"},
        {"prototypes": [{"label": "x"}]},
        {"prototypes": [{"label": "x", "centroid": {"volatility": "not-a-number"}}]},
        {"prototypes": [{"label": "x", "centroid": {}, "offset": "not-a-dict"}]},
    ]

    for model in malformed_models:
        result = apply_learned_topology(topology, features, {}, model, _sample_feature_schema())
        assert result["topology_source"] in TOPOLOGY_SOURCES
        for node in result["nodes"]:
            assert node["topology_source"] in TOPOLOGY_SOURCES


def test_cluster_dominant_regime_label_present_in_fallback():
    topology = _sample_deterministic_topology()

    result = apply_learned_topology(topology, {}, None, None, None)

    for node in result["nodes"]:
        assert "cluster_dominant_regime_label" in node
        assert node["cluster_dominant_regime_label"]


def test_learned_offset_bounded_when_max_offset_z_is_raised_to_the_xy_scale():
    """V4-W3: in 3D mode main.py passes max_offset_z = max_offset_xy,
    because the configured 0.1 cap is tuned for 2D mode's 0..1 volatility
    z and would be effectively zero on 3D's 0..100 spatial axis. The
    bound must still actually bind at the larger value - raising the cap
    must not turn into "unbounded"."""
    topology = _sample_deterministic_topology()
    features = _sample_symbol_features(topology)
    model = {
        "version_id": "v-offset-3d",
        "distance_scale": 5.0,
        "prototypes": [
            {
                "label": "only",
                "centroid": {
                    "volatility": 0.0,
                    "momentum": 0.0,
                    "correlation_strength": 0.0,
                    "liquidity_score": 0.0,
                    "regime_risk_score": 0.0,
                },
                "dominant_regime_label": "unknown",
                "offset": {"x": 999.0, "y": -999.0, "z": 999.0},
            }
        ],
    }
    original_by_symbol = {node["symbol"]: node for node in topology["nodes"]}

    result = apply_learned_topology(
        topology, features, {}, model, _sample_feature_schema(), max_offset_xy=6.0, max_offset_z=6.0
    )

    for node in result["nodes"]:
        base = original_by_symbol[node["symbol"]]
        assert node["topology_source"] == "learned"
        assert abs(node["z"] - base["z"]) <= 6.0 + 1e-9
        # and the raised cap genuinely lets z move further than the 2D 0.1
        assert abs(node["z"] - base["z"]) > 0.1
