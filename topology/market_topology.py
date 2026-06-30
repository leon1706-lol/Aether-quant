"""3D market-topology modeling for Aether Quant V2: correlation-driven
asset clustering and 3D coordinate generation for the runtime market
structure layer consumed by the dashboard and the central market analyzer."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass


ANNUALIZATION_FACTOR = math.sqrt(252)
ELEVATED_VOLATILITY_THRESHOLD = 0.45
NEUTRAL_DIMENSIONS = {"width": 100, "height": 100, "depth": 1}


@dataclass(frozen=True)
class TopologyNode:
    symbol: str
    cluster_id: str
    x: float
    y: float
    z: float
    market_distance: float
    correlation_strength: float
    volatility_pressure: float
    topology_risk: str
    regime_label: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class TopologyLink:
    source: str
    target: str
    correlation: float
    distance: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class TopologyCluster:
    cluster_id: str
    members: list[str]
    average_correlation: float
    dominant_regime_label: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MarketTopology:
    state: str
    nodes: list[TopologyNode]
    links: list[TopologyLink]
    clusters: list[TopologyCluster]
    dimensions: dict
    reasons: list[str]

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "nodes": [node.to_dict() for node in self.nodes],
            "links": [link.to_dict() for link in self.links],
            "clusters": [cluster.to_dict() for cluster in self.clusters],
            "dimensions": dict(self.dimensions),
            "reasons": list(self.reasons),
        }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _pearson_correlation(series_a: list[float], series_b: list[float]) -> float:
    length = min(len(series_a), len(series_b))
    if length < 2:
        return 0.0
    series_a = series_a[-length:]
    series_b = series_b[-length:]
    mean_a = _mean(series_a)
    mean_b = _mean(series_b)
    covariance = sum((a - mean_a) * (b - mean_b) for a, b in zip(series_a, series_b))
    variance_a = sum((a - mean_a) ** 2 for a in series_a)
    variance_b = sum((b - mean_b) ** 2 for b in series_b)
    denominator = math.sqrt(variance_a * variance_b)
    if denominator == 0:
        return 0.0
    return max(-1.0, min(1.0, covariance / denominator))


def _annualized_volatility(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mean_value = _mean(returns)
    variance = sum((value - mean_value) ** 2 for value in returns) / (len(returns) - 1)
    return math.sqrt(max(variance, 0.0)) * ANNUALIZATION_FACTOR


class _UnionFind:
    def __init__(self, items: list[str]):
        self._parent = {item: item for item in items}

    def find(self, item: str) -> str:
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self._parent[max(root_a, root_b)] = min(root_a, root_b)


def _isolated_node(symbol: str, returns: list[float], cluster_id: str, regime_label: str) -> TopologyNode:
    return TopologyNode(
        symbol=symbol,
        cluster_id=cluster_id,
        x=50.0,
        y=50.0,
        z=max(0.1, min(0.95, 0.25 + _annualized_volatility(returns))),
        market_distance=1.0,
        correlation_strength=0.0,
        volatility_pressure=_annualized_volatility(returns),
        topology_risk="isolated",
        regime_label=regime_label,
    )


def build_market_topology(
    returns_by_symbol: dict[str, list[float]],
    regime_labels_by_symbol: dict[str, str] | None = None,
    correlation_threshold: float = 0.6,
    link_threshold: float = 0.5,
    min_observations: int = 5,
) -> MarketTopology:
    regime_labels_by_symbol = regime_labels_by_symbol or {}
    reasons: list[str] = []

    eligible_symbols = sorted(
        symbol for symbol, returns in returns_by_symbol.items() if len(returns) >= min_observations
    )
    excluded_symbols = sorted(set(returns_by_symbol) - set(eligible_symbols))
    if excluded_symbols:
        reasons.append(f"excluded_insufficient_history={','.join(excluded_symbols)}")

    if len(eligible_symbols) < 2:
        reasons.append("insufficient_eligible_assets_for_correlation")
        isolated_nodes = [
            _isolated_node(
                symbol,
                returns_by_symbol.get(symbol, []),
                f"cluster_{index}",
                regime_labels_by_symbol.get(symbol, "unknown"),
            )
            for index, symbol in enumerate(sorted(returns_by_symbol))
        ]
        return MarketTopology(
            state="insufficient_data",
            nodes=isolated_nodes,
            links=[],
            clusters=[],
            dimensions=dict(NEUTRAL_DIMENSIONS),
            reasons=reasons,
        )

    correlations: dict[tuple[str, str], float] = {}
    for index, symbol_a in enumerate(eligible_symbols):
        for symbol_b in eligible_symbols[index + 1 :]:
            correlations[(symbol_a, symbol_b)] = _pearson_correlation(
                returns_by_symbol[symbol_a], returns_by_symbol[symbol_b]
            )

    def correlation_between(symbol_a: str, symbol_b: str) -> float:
        if symbol_a == symbol_b:
            return 1.0
        key = (symbol_a, symbol_b) if (symbol_a, symbol_b) in correlations else (symbol_b, symbol_a)
        return correlations.get(key, 0.0)

    union_find = _UnionFind(eligible_symbols)
    for (symbol_a, symbol_b), correlation in correlations.items():
        if correlation >= correlation_threshold:
            union_find.union(symbol_a, symbol_b)

    members_by_root: dict[str, list[str]] = {}
    for symbol in eligible_symbols:
        members_by_root.setdefault(union_find.find(symbol), []).append(symbol)

    sorted_roots = sorted(members_by_root, key=lambda root: members_by_root[root])
    cluster_count = len(sorted_roots)

    clusters: list[TopologyCluster] = []
    nodes: list[TopologyNode] = []

    for cluster_index, root in enumerate(sorted_roots):
        members = sorted(members_by_root[root])
        cluster_id = f"cluster_{cluster_index}"
        angle = (2 * math.pi * cluster_index) / max(cluster_count, 1)
        centroid_x = 50.0 + math.cos(angle) * 28.0
        centroid_y = 50.0 + math.sin(angle) * 22.0

        pairwise_in_cluster = [
            correlation_between(a, b) for idx, a in enumerate(members) for b in members[idx + 1 :]
        ]
        cluster_average_correlation = _mean(pairwise_in_cluster) if pairwise_in_cluster else 0.0

        regime_votes: dict[str, int] = {}
        for member in members:
            label = regime_labels_by_symbol.get(member, "unknown")
            regime_votes[label] = regime_votes.get(label, 0) + 1
        dominant_regime_label = max(sorted(regime_votes), key=lambda label: regime_votes[label])

        clusters.append(
            TopologyCluster(
                cluster_id=cluster_id,
                members=members,
                average_correlation=cluster_average_correlation,
                dominant_regime_label=dominant_regime_label,
            )
        )

        for member_index, symbol in enumerate(members):
            peer_correlations = [correlation_between(symbol, other) for other in members if other != symbol]
            correlation_strength = _mean(peer_correlations) if peer_correlations else 0.0
            market_distance = max(0.0, 1.0 - correlation_strength) if peer_correlations else 1.0

            within_cluster_angle = (2 * math.pi * member_index) / max(len(members), 1)
            offset_radius = 4.0 + market_distance * 10.0
            x = centroid_x + math.cos(within_cluster_angle) * offset_radius
            y = centroid_y + math.sin(within_cluster_angle) * offset_radius

            volatility_pressure = _annualized_volatility(returns_by_symbol[symbol])
            z = max(0.1, min(0.95, 0.25 + volatility_pressure))

            if len(members) == 1:
                topology_risk = "isolated"
            elif volatility_pressure >= ELEVATED_VOLATILITY_THRESHOLD:
                topology_risk = "elevated"
            else:
                topology_risk = "normal"

            nodes.append(
                TopologyNode(
                    symbol=symbol,
                    cluster_id=cluster_id,
                    x=x,
                    y=y,
                    z=z,
                    market_distance=market_distance,
                    correlation_strength=correlation_strength,
                    volatility_pressure=volatility_pressure,
                    topology_risk=topology_risk,
                    regime_label=regime_labels_by_symbol.get(symbol, "unknown"),
                )
            )

    links: list[TopologyLink] = [
        TopologyLink(
            source=symbol_a,
            target=symbol_b,
            correlation=correlation,
            distance=max(0.0, 1.0 - correlation),
        )
        for (symbol_a, symbol_b), correlation in correlations.items()
        if correlation >= link_threshold
    ]

    for symbol in excluded_symbols:
        nodes.append(
            _isolated_node(
                symbol,
                returns_by_symbol.get(symbol, []),
                "cluster_unassigned",
                regime_labels_by_symbol.get(symbol, "unknown"),
            )
        )

    nodes.sort(key=lambda node: node.symbol)
    links.sort(key=lambda link: (link.source, link.target))

    return MarketTopology(
        state="ready",
        nodes=nodes,
        links=links,
        clusters=clusters,
        dimensions=dict(NEUTRAL_DIMENSIONS),
        reasons=reasons,
    )
