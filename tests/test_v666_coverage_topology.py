"""The last unreached branches of topology/ (V6.6.6, #359)."""

from __future__ import annotations

from test_learned_topology import _sample_deterministic_topology, _sample_feature_schema, _sample_model, _sample_symbol_features
from topology.learned_topology import _neighbor_probabilities, apply_learned_topology, learned_sizing_inputs
from topology.market_topology import _pearson_correlation, _rescale_positions_to_bounds, _stress_majorize


def test_a_symbol_without_features_has_no_neighbour_probabilities():
    assert _neighbor_probabilities("MISSING", {"A": {}}, 0.35) == {}


def test_a_malformed_vector_gives_the_fallback_not_an_error():
    result = learned_sizing_inputs({"volatility": "not a number"}, _sample_model(), _sample_feature_schema())
    assert result == {"topology_source": "fallback", "topology_confidence": 0.0, "topology_disagreement": 0.0}


def test_a_symbol_whose_vector_cannot_be_normalised_is_left_to_the_deterministic_node():
    topology = _sample_deterministic_topology()
    features = _sample_symbol_features(topology)
    first = next(iter(features))
    features[first] = {"volatility": "bad"}
    result = apply_learned_topology(topology, features, {}, _sample_model(), _sample_feature_schema())
    assert {node["symbol"] for node in result["nodes"]} == {node["symbol"] for node in topology["nodes"]}


def test_degenerate_geometry_degrades_to_something_safe():
    assert _stress_majorize(["A"], lambda a, b: 1.0, {"A": (1.0, 2.0)}) == {"A": (1.0, 2.0)}
    assert _rescale_positions_to_bounds({}) == {}
    same = _rescale_positions_to_bounds({"A": (3.0, 3.0), "B": (3.0, 3.0)}, center=50.0)
    assert same == {"A": (50.0, 50.0), "B": (50.0, 50.0)}
    assert _pearson_correlation([1.0], [1.0]) == 0.0 and _pearson_correlation([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) == 0.0


def test_elevated_volatility_thresholds_by_class_ignore_what_is_not_a_positive_number():
    from topology.market_topology import ELEVATED_VOLATILITY_THRESHOLD, resolve_elevated_volatility_thresholds

    assert resolve_elevated_volatility_thresholds(0.6, {}) == (0.6, {})
    assert resolve_elevated_volatility_thresholds("x", {}) == (ELEVATED_VOLATILITY_THRESHOLD, {})
    assert resolve_elevated_volatility_thresholds(-1.0, {})[0] == ELEVATED_VOLATILITY_THRESHOLD
    raw = {"default": 0.5, "crypto": 1.2, "bad": "x", "negative": -1.0}
    assert resolve_elevated_volatility_thresholds(raw, {"BTC": "crypto", "AAA": "equity", "ZZZ": None}) == (0.5, {"BTC": 1.2})
    assert resolve_elevated_volatility_thresholds({"default": None}, {})[0] == ELEVATED_VOLATILITY_THRESHOLD


def test_a_series_whose_variance_underflows_has_no_correlation():
    assert _pearson_correlation([1e-200, 2e-200, 3e-200], [1e-200, 3e-200, 2e-200]) == 0.0


def test_without_numpy_the_matrix_path_steps_aside(monkeypatch):
    import builtins

    from topology.market_topology import _full_window_correlation_matrix

    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "numpy":
            raise ImportError("no numpy")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    assert _full_window_correlation_matrix({"A": [1.0, 2.0], "B": [2.0, 1.0]}, ["A", "B"]) is None


def test_a_symbol_with_too_little_history_becomes_an_isolated_node():
    from topology.market_topology import build_market_topology

    series = [0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.03, -0.025]
    topology = build_market_topology({"AAA": series, "BBB": [v * 1.1 for v in series], "NEW": [0.01, 0.02]}, min_observations=5).to_dict()
    assert any(node["symbol"] == "NEW" for node in topology["nodes"]) and any("excluded_insufficient_history=NEW" in reason for reason in topology["reasons"])
