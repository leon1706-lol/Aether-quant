"""3D market-topology modeling for Aether Quant V2: correlation-driven
asset clustering and 3D coordinate generation for the runtime market
structure layer consumed by the dashboard and the central market analyzer."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Callable


ANNUALIZATION_FACTOR = math.sqrt(252)
ELEVATED_VOLATILITY_THRESHOLD = 0.45
NEUTRAL_DIMENSIONS = {"width": 100, "height": 100, "depth": 1}
EMBEDDING_CENTER = 50.0
EMBEDDING_MAX_RADIUS = 42.0


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


def _distance_2d(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def _stress_majorize_2d(
    symbols: list[str],
    distance_fn: Callable[[str, str], float],
    initial_positions: dict[str, tuple[float, float]],
    iterations: int = 100,
) -> dict[str, tuple[float, float]]:
    """Deterministic SMACOF (Scaling by MAjorizing a COmplicated Function):
    iteratively moves each point toward the position implied by every other
    point's target distance (the classical Guttman transform), so the final
    layout's pairwise Euclidean distances approximate the real target
    distances instead of an arbitrary index-based placement.

    Seeded from initial_positions (the existing cosmetic circular layout)
    rather than randomly, so the result is fully deterministic given the
    same inputs and converges in a fixed number of iterations. Pure Python
    -- no numpy/scipy, matching this module's existing zero-heavy-runtime-
    deps convention (the same reason topology/learned_topology.py stays
    numpy-free).
    """
    if len(symbols) < 2:
        return dict(initial_positions)

    positions = dict(initial_positions)
    denominator = len(symbols) - 1

    for _ in range(iterations):
        new_positions: dict[str, tuple[float, float]] = {}
        for symbol in symbols:
            sum_x, sum_y = 0.0, 0.0
            for other in symbols:
                if other == symbol:
                    continue
                target_distance = distance_fn(symbol, other)
                current_distance = _distance_2d(positions[symbol], positions[other])
                if current_distance > 1e-9:
                    scale = target_distance / current_distance
                    direction_x = (positions[symbol][0] - positions[other][0]) * scale
                    direction_y = (positions[symbol][1] - positions[other][1]) * scale
                else:
                    # Coincident points: nudge apart along a fixed axis
                    # rather than dividing by zero.
                    direction_x, direction_y = target_distance, 0.0
                sum_x += positions[other][0] + direction_x
                sum_y += positions[other][1] + direction_y
            new_positions[symbol] = (sum_x / denominator, sum_y / denominator)
        positions = new_positions

    return positions


def _rescale_positions_to_bounds(
    positions: dict[str, tuple[float, float]],
    center: float = EMBEDDING_CENTER,
    max_radius: float = EMBEDDING_MAX_RADIUS,
) -> dict[str, tuple[float, float]]:
    """Uniformly scale and re-center the embedding to fit within the
    existing NEUTRAL_DIMENSIONS [0,100]x[0,100] bounds.

    A single isometric scale factor (not independent per-axis min-max
    normalization) -- stretching x and y independently would distort the
    very relative distances this embedding exists to preserve.
    """
    if not positions:
        return {}

    mean_x = _mean([point[0] for point in positions.values()])
    mean_y = _mean([point[1] for point in positions.values()])
    max_extent = max(
        (_distance_2d(point, (mean_x, mean_y)) for point in positions.values()),
        default=0.0,
    )
    if max_extent <= 1e-9:
        return {symbol: (center, center) for symbol in positions}

    scale = max_radius / max_extent
    return {
        symbol: (center + (x - mean_x) * scale, center + (y - mean_y) * scale)
        for symbol, (x, y) in positions.items()
    }


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
    embedding_iterations: int = 100,
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

    # Pass 1: cluster structure + per-symbol metadata, and a cosmetic
    # index-based seed layout (the module's previous, sole layout method) --
    # kept only as SMACOF's deterministic starting point below, not as the
    # final coordinates.
    cluster_id_by_symbol: dict[str, str] = {}
    correlation_strength_by_symbol: dict[str, float] = {}
    market_distance_by_symbol: dict[str, float] = {}
    member_count_by_symbol: dict[str, int] = {}
    seed_positions: dict[str, tuple[float, float]] = {}

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
            seed_x = centroid_x + math.cos(within_cluster_angle) * offset_radius
            seed_y = centroid_y + math.sin(within_cluster_angle) * offset_radius

            cluster_id_by_symbol[symbol] = cluster_id
            correlation_strength_by_symbol[symbol] = correlation_strength
            market_distance_by_symbol[symbol] = market_distance
            member_count_by_symbol[symbol] = len(members)
            seed_positions[symbol] = (seed_x, seed_y)

    # Pass 2: real distance-preserving embedding -- pairwise distance across
    # ALL eligible symbols (not just within-cluster pairs; cross-cluster
    # distance matters for a meaningful layout too), seeded from the
    # cosmetic layout above so the result is deterministic and converges
    # fast. This is what makes spatial distance actually reflect
    # correlation distance instead of arbitrary index-based placement.
    final_positions = _rescale_positions_to_bounds(
        _stress_majorize_2d(
            eligible_symbols,
            lambda symbol_a, symbol_b: max(0.0, 1.0 - correlation_between(symbol_a, symbol_b)),
            seed_positions,
            iterations=embedding_iterations,
        )
    )

    # Pass 3: build nodes from the real embedding + per-symbol metadata.
    for symbol in eligible_symbols:
        x, y = final_positions.get(symbol, (EMBEDDING_CENTER, EMBEDDING_CENTER))
        volatility_pressure = _annualized_volatility(returns_by_symbol[symbol])
        z = max(0.1, min(0.95, 0.25 + volatility_pressure))

        if member_count_by_symbol[symbol] == 1:
            topology_risk = "isolated"
        elif volatility_pressure >= ELEVATED_VOLATILITY_THRESHOLD:
            topology_risk = "elevated"
        else:
            topology_risk = "normal"

        nodes.append(
            TopologyNode(
                symbol=symbol,
                cluster_id=cluster_id_by_symbol[symbol],
                x=x,
                y=y,
                z=z,
                market_distance=market_distance_by_symbol[symbol],
                correlation_strength=correlation_strength_by_symbol[symbol],
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
