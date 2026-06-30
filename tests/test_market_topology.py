from topology import build_market_topology


def _series(values: list[float], length: int = 8) -> list[float]:
    repeats = (length // len(values)) + 1
    return (values * repeats)[:length]


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


def test_regime_labels_aggregate_to_dominant_cluster_label():
    base = _series([0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.03, -0.025])
    returns = {
        "AAA": base,
        "BBB": [value * 1.05 for value in base],
    }
    regime_labels = {"AAA": "bullish", "BBB": "bullish"}

    topology = build_market_topology(returns, regime_labels_by_symbol=regime_labels, correlation_threshold=0.6)

    assert topology.clusters[0].dominant_regime_label == "bullish"
