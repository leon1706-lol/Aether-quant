import math

import pytest

from topology import build_market_topology
from topology.market_topology import _stress_majorize, rank_correlated_peers


def _series(values: list[float], length: int = 8) -> list[float]:
    repeats = (length // len(values)) + 1
    return (values * repeats)[:length]


def _euclidean(a, b) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2)


def test_stable_coordinates_are_deterministic():
    returns = {
        "AAA": _series([0.01, -0.02, 0.015, 0.005, -0.01, 0.02]),
        "BBB": _series([0.012, -0.018, 0.016, 0.004, -0.011, 0.019]),
        "CCC": _series([-0.03, 0.04, -0.02, 0.05, -0.04, 0.03]),
    }

    first = build_market_topology(returns)
    second = build_market_topology(returns)

    assert first.to_dict() == second.to_dict()


def test_correlated_assets_get_stronger_links_and_cluster_together():
    base = _series([0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.03, -0.025])
    returns = {
        "AAA": base,
        "BBB": [value * 1.05 for value in base],
        "CCC": _series([-0.04, 0.05, -0.06, 0.07, -0.03, 0.02, -0.05, 0.04]),
    }

    topology = build_market_topology(returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5)

    nodes_by_symbol = {node.symbol: node for node in topology.nodes}
    assert nodes_by_symbol["AAA"].cluster_id == nodes_by_symbol["BBB"].cluster_id
    assert nodes_by_symbol["CCC"].cluster_id != nodes_by_symbol["AAA"].cluster_id

    ab_link = next(
        link
        for link in topology.links
        if {link.source, link.target} == {"AAA", "BBB"}
    )
    other_links = [
        link for link in topology.links if {link.source, link.target} != {"AAA", "BBB"}
    ]
    assert all(ab_link.correlation > link.correlation for link in other_links)


def test_missing_or_limited_data_does_not_crash():
    returns = {
        "THIN": [0.01, -0.02],
        "EMPTY": [],
    }

    topology = build_market_topology(returns, min_observations=5)

    assert topology.state == "insufficient_data"
    symbols = {node.symbol for node in topology.nodes}
    assert symbols == {"THIN", "EMPTY"}
    assert all(node.topology_risk == "isolated" for node in topology.nodes)
    assert topology.links == []


def test_isolated_singleton_cluster_is_flagged():
    base = _series([0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.03, -0.025])
    returns = {
        "AAA": base,
        "BBB": [value * 1.05 for value in base],
        "LONER": _series([0.002, -0.001, 0.0015, -0.0005, 0.001, -0.002, 0.0008, -0.0012]),
    }

    topology = build_market_topology(returns, correlation_threshold=0.8, link_threshold=0.6, min_observations=5)

    nodes_by_symbol = {node.symbol: node for node in topology.nodes}
    assert nodes_by_symbol["LONER"].topology_risk == "isolated"


def test_correlated_assets_are_spatially_closer_than_uncorrelated_assets():
    """The V2-19.5-follow-up SMACOF embedding: unlike the old index->angle
    cosmetic placement (which only encoded cluster membership), spatial
    distance must now actually reflect correlation distance."""
    base = _series([0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.03, -0.025])
    returns = {
        "AAA": base,
        "BBB": [value * 1.05 for value in base],
        "CCC": _series([-0.04, 0.05, -0.06, 0.07, -0.03, 0.02, -0.05, 0.04]),
    }

    topology = build_market_topology(returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5)
    nodes_by_symbol = {node.symbol: node for node in topology.nodes}

    ab_distance = _euclidean(nodes_by_symbol["AAA"], nodes_by_symbol["BBB"])
    ac_distance = _euclidean(nodes_by_symbol["AAA"], nodes_by_symbol["CCC"])
    bc_distance = _euclidean(nodes_by_symbol["BBB"], nodes_by_symbol["CCC"])

    assert ab_distance < ac_distance
    assert ab_distance < bc_distance


def test_embedding_coordinates_stay_within_neutral_dimensions_bounds():
    base = _series([0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.03, -0.025])
    returns = {
        "AAA": base,
        "BBB": [value * 1.05 for value in base],
        "CCC": _series([-0.04, 0.05, -0.06, 0.07, -0.03, 0.02, -0.05, 0.04]),
        "DDD": _series([0.02, 0.01, -0.03, 0.015, 0.005, -0.02, 0.03, -0.01]),
    }

    topology = build_market_topology(returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5)

    for node in topology.nodes:
        assert 0.0 <= node.x <= 100.0
        assert 0.0 <= node.y <= 100.0


def test_embedding_iterations_actually_affects_layout():
    """Confirms embedding_iterations is genuinely threaded through and used
    -- not a config key that's silently ignored."""
    base = _series([0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.03, -0.025])
    returns = {
        "AAA": base,
        "BBB": [value * 1.05 for value in base],
        "CCC": _series([-0.04, 0.05, -0.06, 0.07, -0.03, 0.02, -0.05, 0.04]),
    }

    zero_iterations = build_market_topology(returns, correlation_threshold=0.6, embedding_iterations=0)
    many_iterations = build_market_topology(returns, correlation_threshold=0.6, embedding_iterations=100)

    zero_nodes = {node.symbol: node for node in zero_iterations.nodes}
    many_nodes = {node.symbol: node for node in many_iterations.nodes}
    assert any(
        (zero_nodes[symbol].x, zero_nodes[symbol].y) != (many_nodes[symbol].x, many_nodes[symbol].y)
        for symbol in zero_nodes
    )


def test_regime_labels_aggregate_to_dominant_cluster_label():
    base = _series([0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.03, -0.025])
    returns = {
        "AAA": base,
        "BBB": [value * 1.05 for value in base],
    }
    regime_labels = {"AAA": "bullish", "BBB": "bullish"}

    topology = build_market_topology(returns, regime_labels_by_symbol=regime_labels, correlation_threshold=0.6)

    assert topology.clusters[0].dominant_regime_label == "bullish"


def test_stress_majorize_matches_pure_python_reference():
    """Parity guard for the numpy vectorization of `_stress_majorize`
    (Part D1 of the latency-optimization pass): these expected values were
    captured from the original pure-Python nested-loop implementation on
    this exact input, run once as a throwaway script before the
    vectorization landed. BLAS reduction order can differ across
    platforms/backends, hence the (still tight) 1e-6 tolerance rather than
    1e-9."""
    symbols = ["AAA", "BBB", "CCC", "DDD"]
    initial_positions = {
        "AAA": (10.0, 20.0),
        "BBB": (30.0, 5.0),
        "CCC": (-15.0, 40.0),
        "DDD": (0.0, 0.0),
    }
    distances = {
        ("AAA", "BBB"): 0.3,
        ("AAA", "CCC"): 0.9,
        ("AAA", "DDD"): 0.5,
        ("BBB", "CCC"): 0.7,
        ("BBB", "DDD"): 0.2,
        ("CCC", "DDD"): 0.6,
    }

    def distance_fn(symbol_a: str, symbol_b: str) -> float:
        if symbol_a == symbol_b:
            return 0.0
        key = (symbol_a, symbol_b) if (symbol_a, symbol_b) in distances else (symbol_b, symbol_a)
        return distances[key]

    expected = {
        "AAA": (6.638068704388609, 16.34692047415163),
        "BBB": (6.340899192710371, 16.388781999201612),
        "CCC": (5.879793332858152, 15.862124525742345),
        "DDD": (6.141238770042861, 16.402173000904398),
    }

    result = _stress_majorize(symbols, distance_fn, initial_positions, iterations=100)

    for symbol in symbols:
        assert result[symbol] == pytest.approx(expected[symbol], abs=1e-6)


def _sample_distance_fn(distances: dict) -> callable:
    def distance_fn(symbol_a: str, symbol_b: str) -> float:
        if symbol_a == symbol_b:
            return 0.0
        key = (symbol_a, symbol_b) if (symbol_a, symbol_b) in distances else (symbol_b, symbol_a)
        return distances[key]

    return distance_fn


def test_warm_started_seed_needs_far_fewer_iterations_to_stay_near_the_fixed_point():
    """Part D2: a seed already at (or near) this bar's stationary point
    should barely move in a handful of iterations, while a cold, far-off
    seed should still be well short of it - this is the property that lets
    convergence_tolerance actually save iterations on a warm start."""
    symbols = ["AAA", "BBB", "CCC", "DDD"]
    distances = {
        ("AAA", "BBB"): 0.3,
        ("AAA", "CCC"): 0.9,
        ("AAA", "DDD"): 0.5,
        ("BBB", "CCC"): 0.7,
        ("BBB", "DDD"): 0.2,
        ("CCC", "DDD"): 0.6,
    }
    distance_fn = _sample_distance_fn(distances)
    cold_seed = {
        "AAA": (10.0, 20.0),
        "BBB": (30.0, 5.0),
        "CCC": (-15.0, 40.0),
        "DDD": (0.0, 0.0),
    }

    converged = _stress_majorize(symbols, distance_fn, cold_seed, iterations=200, convergence_tolerance=1e-9)

    cold_start_few_iterations = _stress_majorize(symbols, distance_fn, cold_seed, iterations=2)
    warm_start_few_iterations = _stress_majorize(symbols, distance_fn, converged, iterations=2)

    def total_distance_to_converged(candidate: dict) -> float:
        return sum(math.dist(candidate[symbol], converged[symbol]) for symbol in symbols)

    assert total_distance_to_converged(warm_start_few_iterations) < total_distance_to_converged(cold_start_few_iterations)


def test_build_market_topology_handles_partial_previous_positions_without_crashing():
    """A symbol new to the universe (or isolated last bar) won't have an
    entry in previous_positions - must fall back to the cosmetic seed for
    that symbol alone, not crash."""
    base = _series([0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.03, -0.025])
    returns = {
        "AAA": base,
        "BBB": [value * 1.05 for value in base],
        "CCC": _series([-0.04, 0.05, -0.06, 0.07, -0.03, 0.02, -0.05, 0.04]),
    }
    partial_previous_positions = {"AAA": (60.0, 40.0)}

    topology = build_market_topology(
        returns,
        correlation_threshold=0.6,
        link_threshold=0.4,
        min_observations=5,
        previous_positions=partial_previous_positions,
    )

    symbols = {node.symbol for node in topology.nodes}
    assert symbols == {"AAA", "BBB", "CCC"}


def test_warm_start_disabled_matches_omitting_previous_positions():
    """previous_positions=None (how main.py calls this when
    phase_v2.topology.warm_start_enabled is false) must reproduce the exact
    D1 (vectorized, pre-warm-start) behavior - the config flag is a genuine
    safe fallback, not a partial behavior change."""
    base = _series([0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.03, -0.025])
    returns = {
        "AAA": base,
        "BBB": [value * 1.05 for value in base],
        "CCC": _series([-0.04, 0.05, -0.06, 0.07, -0.03, 0.02, -0.05, 0.04]),
    }

    without_param = build_market_topology(returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5)
    with_explicit_none = build_market_topology(
        returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5, previous_positions=None
    )

    assert without_param.to_dict() == with_explicit_none.to_dict()


# ---------------------------------------------------------------------------
# previous_correlations / correlation_stability_tolerance (development/
# Problems.md#36 - skip re-running SMACOF when correlation structure hasn't
# materially changed bar-to-bar)
# ---------------------------------------------------------------------------


def _three_symbol_returns() -> dict[str, list[float]]:
    base = _series([0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.03, -0.025])
    return {
        "AAA": base,
        "BBB": [value * 1.05 for value in base],
        "CCC": _series([-0.04, 0.05, -0.06, 0.07, -0.03, 0.02, -0.05, 0.04]),
    }


def test_topology_cache_disabled_matches_omitting_previous_correlations():
    """correlation_stability_tolerance=None (how main.py calls this when
    phase_v2.topology.cache_enabled is false) must reproduce the exact
    pre-caching behavior, even when previous_correlations/previous_positions
    ARE supplied - tolerance=None is what gates the whole feature off, same
    contract test_warm_start_disabled_matches_omitting_previous_positions
    already guarantees for the warm-start feature."""
    returns = _three_symbol_returns()
    first = build_market_topology(returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5)
    previous_positions = {node.symbol: (node.x, node.y) for node in first.nodes}

    without_cache_params = build_market_topology(
        returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5,
        previous_positions=previous_positions,
    )
    with_correlations_but_no_tolerance = build_market_topology(
        returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5,
        previous_positions=previous_positions, previous_correlations=first.correlations,
        correlation_stability_tolerance=None,
    )

    assert without_cache_params.to_dict() == with_correlations_but_no_tolerance.to_dict()


def test_topology_cache_reuses_previous_positions_when_correlations_stable():
    returns = _three_symbol_returns()
    first = build_market_topology(returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5)
    previous_positions = {node.symbol: (node.x, node.y) for node in first.nodes}

    second = build_market_topology(
        returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5,
        previous_positions=previous_positions, previous_correlations=first.correlations,
        correlation_stability_tolerance=0.001,  # identical returns -> 0.0 change, well within tolerance
    )

    for node in second.nodes:
        assert (node.x, node.y) == previous_positions[node.symbol]
    assert "topology_embedding_reused_stable_correlations" in second.reasons


def test_topology_cache_skips_stress_majorize_when_reusing(monkeypatch):
    """Proves the expensive embedding call was actually skipped, not just
    that the result happens to match (SMACOF re-converging to an identical
    fixed point would look the same from the output alone)."""
    import topology.market_topology as market_topology_module

    returns = _three_symbol_returns()
    first = build_market_topology(returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5)
    previous_positions = {node.symbol: (node.x, node.y) for node in first.nodes}

    call_count = {"n": 0}
    real_stress_majorize = market_topology_module._stress_majorize

    def _counting_stress_majorize(*args, **kwargs):
        call_count["n"] += 1
        return real_stress_majorize(*args, **kwargs)

    monkeypatch.setattr(market_topology_module, "_stress_majorize", _counting_stress_majorize)

    market_topology_module.build_market_topology(
        returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5,
        previous_positions=previous_positions, previous_correlations=first.correlations,
        correlation_stability_tolerance=0.001,
    )

    assert call_count["n"] == 0


def test_topology_cache_recomputes_when_correlation_change_exceeds_tolerance():
    returns = _three_symbol_returns()
    first = build_market_topology(returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5)
    previous_positions = {node.symbol: (node.x, node.y) for node in first.nodes}
    # Fabricate a "previous bar" correlation snapshot far from the real one -
    # forces max_correlation_change well above any reasonable tolerance.
    far_previous_correlations = {key: -value for key, value in first.correlations.items()}

    second = build_market_topology(
        returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5,
        previous_positions=previous_positions, previous_correlations=far_previous_correlations,
        correlation_stability_tolerance=0.001,
    )

    assert "topology_embedding_reused_stable_correlations" not in second.reasons


def test_topology_cache_recomputes_when_eligible_universe_changed():
    """A new eligible symbol this bar (absent from previous_correlations)
    must force a full recompute, even with a very generous tolerance -
    reusing stale positions for a symbol previous_positions never saw would
    be silently wrong, not just imprecise."""
    returns = _three_symbol_returns()
    two_symbol_returns = {"AAA": returns["AAA"], "BBB": returns["BBB"]}
    first = build_market_topology(two_symbol_returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5)
    previous_positions = {node.symbol: (node.x, node.y) for node in first.nodes}

    second = build_market_topology(
        returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5,  # CCC newly eligible this bar
        previous_positions=previous_positions, previous_correlations=first.correlations,
        correlation_stability_tolerance=1.0,  # maximally generous - would always pass on value alone
    )

    assert "topology_embedding_reused_stable_correlations" not in second.reasons


def test_topology_cache_recomputes_when_previous_correlations_missing():
    returns = _three_symbol_returns()
    first = build_market_topology(returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5)
    previous_positions = {node.symbol: (node.x, node.y) for node in first.nodes}

    second = build_market_topology(
        returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5,
        previous_positions=previous_positions, previous_correlations=None,
        correlation_stability_tolerance=1.0,
    )

    assert "topology_embedding_reused_stable_correlations" not in second.reasons


def test_topology_correlations_field_populated_on_ready_state_and_empty_on_insufficient_data():
    returns = _three_symbol_returns()
    ready = build_market_topology(returns, min_observations=5)
    assert ready.state == "ready"
    assert len(ready.correlations) == 3  # 3 symbols -> 3 unique pairs

    insufficient = build_market_topology({"AAA": returns["AAA"]}, min_observations=5)
    assert insufficient.state == "insufficient_data"
    assert insufficient.correlations == {}


# ---------------------------------------------------------------------------
# rank_correlated_peers / TopologyNode.top_peers/top_peer_returns
# ---------------------------------------------------------------------------


def test_rank_correlated_peers_orders_by_descending_correlation():
    correlations = {("A", "B"): 0.9, ("A", "C"): 0.2, ("A", "D"): 0.5}

    def correlation_fn(symbol_a, symbol_b):
        if symbol_a == symbol_b:
            return 1.0
        key = (symbol_a, symbol_b) if (symbol_a, symbol_b) in correlations else (symbol_b, symbol_a)
        return correlations.get(key, 0.0)

    result = rank_correlated_peers("A", ["A", "B", "C", "D"], correlation_fn, top_n=2)

    assert result == ["B", "D"]


def test_rank_correlated_peers_excludes_self():
    correlations = {}

    def correlation_fn(symbol_a, symbol_b):
        return 1.0 if symbol_a == symbol_b else correlations.get((symbol_a, symbol_b), 0.0)

    result = rank_correlated_peers("A", ["A", "B"], correlation_fn, top_n=5)

    assert "A" not in result


def test_rank_correlated_peers_breaks_ties_alphabetically():
    def correlation_fn(symbol_a, symbol_b):
        return 0.5  # every pair tied

    result = rank_correlated_peers("A", ["A", "C", "B", "D"], correlation_fn, top_n=2)

    assert result == ["B", "C"]


def test_build_market_topology_nodes_carry_ranked_peers_and_returns():
    base = _series([0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.03, -0.025])
    returns = {
        "AAA": base,
        "BBB": [value * 1.05 for value in base],  # near-perfectly correlated with AAA
        "CCC": _series([-0.04, 0.05, -0.06, 0.07, -0.03, 0.02, -0.05, 0.04]),
    }

    topology = build_market_topology(returns, min_observations=5, top_peers_n=2)

    aaa_node = next(node for node in topology.nodes if node.symbol == "AAA")
    assert aaa_node.top_peers[0] == "BBB"  # most correlated peer ranked first
    assert len(aaa_node.top_peers) == 2
    assert len(aaa_node.top_peer_returns) == 2
    assert aaa_node.top_peer_returns[0] == returns["BBB"][-1]  # peer's own latest return, no lookahead


def test_build_market_topology_isolated_node_has_no_peers():
    topology = build_market_topology({"AAA": _series([0.01, -0.02, 0.015])}, min_observations=5)

    aaa_node = next(node for node in topology.nodes if node.symbol == "AAA")
    assert aaa_node.top_peers == []
    assert aaa_node.top_peer_returns == []


def test_build_market_topology_pads_fewer_peers_than_top_peers_n():
    base = _series([0.01, -0.02, 0.015, 0.005, -0.01, 0.02])
    returns = {"AAA": base, "BBB": [value * 1.05 for value in base]}

    topology = build_market_topology(returns, min_observations=5, top_peers_n=5)

    aaa_node = next(node for node in topology.nodes if node.symbol == "AAA")
    # Only 1 possible peer (BBB) exists, even though top_peers_n=5 was requested.
    assert aaa_node.top_peers == ["BBB"]
    assert len(aaa_node.top_peer_returns) == 1


def test_build_market_topology_peers_are_not_filtered_by_asset_class():
    # Locks in (documents, doesn't just incidentally exercise) a real
    # property this function already has: build_market_topology()/
    # rank_correlated_peers() take plain symbol->returns dicts with no
    # security_type concept anywhere - a bond ETF or crypto asset's return
    # series can surface as an equity's top_peers purely on correlation,
    # the moment it exists in the universe. This is exactly the mechanism
    # Phase 1b (5/10 -> 9/10 roadmap, see development/Changelog.md) relies
    # on for "no new engineering needed" cross-asset-class relational
    # features once the bond ETF sleeve was added - see also
    # features/macro_features.py for the deliberate, explicit macro
    # features layered on top of this incidental mechanism.
    base = _series([0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.03, -0.025])
    returns = {
        "AAPL": base,  # equity
        "TLT": [value * 1.05 for value in base],  # bond ETF, near-perfectly correlated with AAPL
        "BTCUSD": _series([-0.04, 0.05, -0.06, 0.07, -0.03, 0.02, -0.05, 0.04]),  # crypto, uncorrelated
    }

    topology = build_market_topology(returns, min_observations=5, top_peers_n=2)

    aapl_node = next(node for node in topology.nodes if node.symbol == "AAPL")
    assert aapl_node.top_peers[0] == "TLT"  # a bond ETF ranked as the equity's top peer
    assert "BTCUSD" in aapl_node.top_peers  # the crypto asset also eligible, just ranked lower


# ---------------------------------------------------------------------------
# V4-W3: embedding_dimensions - genuine 3D SMACOF embedding.
#
# The contract these guard: at the default embedding_dimensions=2 nothing
# whatsoever changes (z stays the volatility encoding, depth stays 1, every
# coordinate is byte-identical), and at 3 z becomes a real distance-
# preserving axis on the same 0..100 scale as x/y. The pure-Python parity
# test above is the other half of the 2D guarantee.
# ---------------------------------------------------------------------------


def _three_dimensional_returns() -> dict[str, list[float]]:
    base = _series([0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.03, -0.025], length=24)
    return {
        "AAA": base,
        "BBB": [value * 1.05 for value in base],  # near-perfectly correlated with AAA
        "CCC": [-value for value in base],  # anti-correlated with AAA
        "DDD": _series([-0.04, 0.05, -0.06, 0.07, -0.03, 0.02, -0.05, 0.04], length=24),
    }


def test_embedding_dimensions_two_matches_omitting_the_parameter():
    """The default must be a no-op: same posture as
    test_warm_start_disabled_matches_omitting_previous_positions, so
    shipping this feature cannot move a single existing coordinate."""
    returns = _three_dimensional_returns()

    without_param = build_market_topology(returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5)
    with_explicit_two = build_market_topology(
        returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5, embedding_dimensions=2
    )

    assert without_param.to_dict() == with_explicit_two.to_dict()
    assert without_param.dimensions["depth"] == 1


def test_embedding_dimensions_three_produces_a_non_degenerate_z_axis():
    """The whole point of the feature: z must actually vary. Seeding the
    third axis flat (or on the raw 0.1..0.95 volatility scale, ~1/100th of
    the x/y spread) would leave SMACOF unable to separate points along z
    and the layout would stay visually 2D despite claiming 3 dimensions."""
    returns = _three_dimensional_returns()

    topology = build_market_topology(
        returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5, embedding_dimensions=3
    )

    z_values = [node.z for node in topology.nodes]
    assert topology.dimensions["depth"] == 100
    assert max(z_values) - min(z_values) > 1.0  # genuinely spread, not a flat plane
    assert all(0.0 <= z <= 100.0 for z in z_values)  # on the same scale as x/y


def test_embedding_dimensions_three_is_deterministic():
    """Same guarantee test_stable_coordinates_are_deterministic makes for
    2D - SMACOF is seeded, never randomized, in either dimensionality."""
    returns = _three_dimensional_returns()
    kwargs = dict(correlation_threshold=0.6, link_threshold=0.4, min_observations=5, embedding_dimensions=3)

    assert build_market_topology(returns, **kwargs).to_dict() == build_market_topology(returns, **kwargs).to_dict()


def test_embedding_dimensions_three_preserves_correlation_distance_in_3d():
    """Positions must be meaningful in all three axes, not just x/y: the
    near-perfectly correlated pair has to end up closer in full 3D space
    than the anti-correlated pair does."""
    returns = _three_dimensional_returns()

    topology = build_market_topology(
        returns, correlation_threshold=0.6, link_threshold=0.4, min_observations=5, embedding_dimensions=3
    )
    node_by_symbol = {node.symbol: node for node in topology.nodes}

    def distance_3d(a, b) -> float:
        return math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))

    correlated = distance_3d(node_by_symbol["AAA"], node_by_symbol["BBB"])
    anti_correlated = distance_3d(node_by_symbol["AAA"], node_by_symbol["CCC"])

    assert correlated < anti_correlated


def test_embedding_dimensions_three_warm_starts_from_three_tuples():
    """main.py stores 3-tuples when running in 3D. Feeding them back in as
    previous_positions must work - a crash or a silent dimensionality drop
    here would disable warm start on every bar."""
    returns = _three_dimensional_returns()
    kwargs = dict(correlation_threshold=0.6, link_threshold=0.4, min_observations=5, embedding_dimensions=3)

    first = build_market_topology(returns, **kwargs)
    previous_positions = {node.symbol: (node.x, node.y, node.z) for node in first.nodes}

    second = build_market_topology(returns, previous_positions=previous_positions, **kwargs)

    assert {node.symbol for node in second.nodes} == {node.symbol for node in first.nodes}
    assert all(0.0 <= node.z <= 100.0 for node in second.nodes)


def test_mismatched_previous_position_width_is_ignored_not_fatal():
    """Flipping embedding_dimensions between bars (or resuming a run under
    a changed config) leaves stale positions of the wrong tuple width in
    hand. They must be dropped like an unseen symbol - stacking them into
    numpy alongside correct-width tuples would raise."""
    returns = _three_dimensional_returns()
    stale_two_dimensional = {symbol: (60.0, 40.0) for symbol in returns}

    topology = build_market_topology(
        returns,
        correlation_threshold=0.6,
        link_threshold=0.4,
        min_observations=5,
        embedding_dimensions=3,
        previous_positions=stale_two_dimensional,
    )

    assert {node.symbol for node in topology.nodes} == set(returns)
    assert all(0.0 <= node.z <= 100.0 for node in topology.nodes)


def test_embedding_dimensions_three_insufficient_data_centres_z():
    """The <2-eligible-symbols early return builds nodes via _isolated_node,
    which has its own z branch - it must follow the active mode's scale,
    not emit a 0..1 volatility z into a 0..100 scene."""
    topology = build_market_topology(
        {"AAA": [0.01, -0.02, 0.015]}, min_observations=5, embedding_dimensions=3
    )

    assert topology.state == "insufficient_data"
    assert topology.dimensions["depth"] == 100
    assert all(0.0 <= node.z <= 100.0 for node in topology.nodes)


@pytest.mark.parametrize("embedding_dimensions", [2, 3])
def test_node_z_over_declared_depth_is_a_zero_to_one_fraction(embedding_dimensions):
    """The invariant main.py::_build_scene_payload() relies on.

    That payload's z is a 0..1 scale (portfolio_core sits at 0.95), but it
    sources asset z straight from topology - which is 0..1 only in 2D
    mode and 0..100 in 3D. It divides by the topology's own declared
    `dimensions.depth` to reconcile the two, so `z / depth` must land in
    [0, 1] in BOTH modes or the Overview scene collapses onto a plane.

    Asserted here rather than against _build_scene_payload directly
    because main.py subclasses QCAlgorithm and is not importable outside
    the Lean runtime - no test in this suite imports it.
    """
    returns = _three_dimensional_returns()

    topology = build_market_topology(
        returns,
        correlation_threshold=0.6,
        link_threshold=0.4,
        min_observations=5,
        embedding_dimensions=embedding_dimensions,
    )

    depth = topology.dimensions["depth"]
    assert depth >= 1
    assert all(0.0 <= node.z / depth <= 1.0 for node in topology.nodes)
