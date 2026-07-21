"""3D market-topology modeling for Aether Quant V2: correlation-driven
asset clustering and 3D coordinate generation for the runtime market
structure layer consumed by the dashboard and the central market analyzer."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np


ANNUALIZATION_FACTOR = math.sqrt(252)
ELEVATED_VOLATILITY_THRESHOLD = 0.45
NEUTRAL_DIMENSIONS = {"width": 100, "height": 100, "depth": 1}
EMBEDDING_CENTER = 50.0
EMBEDDING_MAX_RADIUS = 42.0
# V4-W3: how far the volatility-derived z seed spreads around
# EMBEDDING_CENTER before SMACOF runs. Only used in 3D mode - a flat seed
# plane would leave the z axis degenerate, since SMACOF can only move
# points along directions its seed already separates them on.
EMBEDDING_Z_SEED_SPREAD = 40.0


def _dimensions_for(embedding_dimensions: int) -> dict:
    """Scene bounds for the active embedding mode. depth stays 1 in 2D
    mode - there z is the volatility encoding on a 0..1 scale, not a
    spatial axis - and becomes 100 in 3D mode, matching width/height so
    the webui's `dimensions`-relative normalization stays isotropic."""
    return {"width": 100, "height": 100, "depth": 100 if embedding_dimensions == 3 else 1}


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
    # Ranked (descending correlation) top-N peer symbols across the WHOLE
    # eligible universe (not just this node's own cluster - a
    # correlation_threshold-defined cluster can be much smaller than
    # top_peers_n) and each peer's own latest available return - a genuine
    # new information channel for the prediction model (see
    # train.py::build_peer_return_features_by_date()), distinct from
    # correlation_strength above (a single mean scalar). Empty for an
    # isolated node (no peers). No lookahead: each peer's latest return is
    # already known as of this node's own current bar.
    top_peers: list[str]
    top_peer_returns: list[float]

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
    # Sparse pairwise Pearson correlations this bar (symbol pair -> value),
    # keyed the same way build_market_topology()'s internal `correlations`
    # dict is - NOT part of to_dict()'s output (tuple keys aren't JSON-safe,
    # and the webui has no use for raw correlations). Exists so a caller
    # (main.py) can pass this bar's result back in as next bar's
    # `previous_correlations` - see build_market_topology()'s
    # correlation_stability_tolerance parameter, development/Problems.md#36.
    correlations: dict[tuple[str, str], float]

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


def _distance(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.sqrt(sum((component_a - component_b) ** 2 for component_a, component_b in zip(a, b)))


def _stress_majorize(
    symbols: list[str],
    distance_fn: Callable[[str, str], float],
    initial_positions: dict[str, tuple[float, ...]],
    iterations: int = 100,
    convergence_tolerance: float | None = None,
) -> dict[str, tuple[float, ...]]:
    """Deterministic SMACOF (Scaling by MAjorizing a COmplicated Function):
    iteratively moves each point toward the position implied by every other
    point's target distance (the classical Guttman transform), so the final
    layout's pairwise Euclidean distances approximate the real target
    distances instead of an arbitrary index-based placement.

    Seeded from initial_positions - the existing cosmetic circular layout,
    or (Part D2) the previous bar's converged positions when warm-starting
    is enabled - rather than randomly, so the result is fully deterministic
    given the same inputs. Vectorized with numpy (this was previously pure
    Python, an O(N^2 x iterations) nested loop and the dominant per-bar
    cost in the topology layer) - same inputs/outputs/seeding as the
    pure-Python version when `convergence_tolerance` is None; see
    tests/test_market_topology.py's parity test.

    Dimension-agnostic (V4-W3): the embedding dimensionality is inferred
    from the length of the seed tuples rather than passed as a flag, so
    2-tuple seeds reproduce the original 2D behavior exactly (the parity
    test above is what holds that guarantee) and 3-tuple seeds produce a
    genuine 3D embedding. Every step below is already axis-generic except
    the coincident-point nudge, which is handled explicitly.

    `convergence_tolerance`, when set, exits before `iterations` once every
    point's per-iteration movement drops below it - this is what lets a
    warm start (already close to this bar's stationary point) actually
    finish faster, rather than always spending the full fixed iteration
    budget regardless of how close the seed already is.
    """
    if len(symbols) < 2:
        return dict(initial_positions)

    n = len(symbols)
    denominator = n - 1
    positions = np.array([initial_positions[symbol] for symbol in symbols], dtype=np.float64)
    dimensions = positions.shape[1]
    target_distances = np.array(
        [[distance_fn(symbol_a, symbol_b) for symbol_b in symbols] for symbol_a in symbols],
        dtype=np.float64,
    )
    np.fill_diagonal(target_distances, 0.0)

    for _ in range(iterations):
        diff = positions[:, None, :] - positions[None, :, :]
        current_distance = np.sqrt((diff**2).sum(axis=-1))
        coincident = current_distance <= 1e-9
        safe_distance = np.where(coincident, 1.0, current_distance)
        scale = np.where(coincident, 0.0, target_distances / safe_distance)
        direction = diff * scale[:, :, None]
        # Coincident points (including the i==j diagonal, always coincident
        # with itself): nudge apart along a fixed axis rather than dividing
        # by zero. target_distances' diagonal is 0, so the i==j case
        # naturally contributes an all-zero vector, matching the original
        # loop's `if other == symbol: continue` skip. The nudge goes along
        # axis 0 only, in every dimensionality - identical to the 2D
        # original, which set axis 0 to target_distances and axis 1 to 0.
        direction[..., 0] = np.where(coincident, target_distances, direction[..., 0])
        for axis in range(1, dimensions):
            direction[..., axis] = np.where(coincident, 0.0, direction[..., axis])

        sum_positions = positions.sum(axis=0)
        direction_sum = direction.sum(axis=1)
        new_positions = (sum_positions[None, :] + direction_sum - positions) / denominator

        if convergence_tolerance is not None:
            max_shift = np.sqrt(((new_positions - positions) ** 2).sum(axis=1)).max()
            positions = new_positions
            if max_shift < convergence_tolerance:
                break
        else:
            positions = new_positions

    return {
        symbol: tuple(float(component) for component in positions[index]) for index, symbol in enumerate(symbols)
    }


def _rescale_positions_to_bounds(
    positions: dict[str, tuple[float, ...]],
    center: float = EMBEDDING_CENTER,
    max_radius: float = EMBEDDING_MAX_RADIUS,
) -> dict[str, tuple[float, ...]]:
    """Uniformly scale and re-center the embedding to fit within the
    existing NEUTRAL_DIMENSIONS [0,100]^d bounds.

    A single isometric scale factor (not independent per-axis min-max
    normalization) -- stretching axes independently would distort the very
    relative distances this embedding exists to preserve. Dimension-
    agnostic (V4-W3): the same single factor now covers z too when the
    embedding runs in 3D.
    """
    if not positions:
        return {}

    dimensions = len(next(iter(positions.values())))
    centroid = tuple(_mean([point[axis] for point in positions.values()]) for axis in range(dimensions))
    max_extent = max(
        (_distance(point, centroid) for point in positions.values()),
        default=0.0,
    )
    if max_extent <= 1e-9:
        return {symbol: (center,) * dimensions for symbol in positions}

    scale = max_radius / max_extent
    return {
        symbol: tuple(center + (point[axis] - centroid[axis]) * scale for axis in range(dimensions))
        for symbol, point in positions.items()
    }


def _isolated_node(
    symbol: str,
    returns: list[float],
    cluster_id: str,
    regime_label: str,
    embedding_dimensions: int = 2,
) -> TopologyNode:
    return TopologyNode(
        symbol=symbol,
        cluster_id=cluster_id,
        x=50.0,
        y=50.0,
        # In 3D mode z is a spatial axis on the same 0..100 scale as x/y,
        # so an isolated node sits at the centre like it already does on
        # x/y. In 2D mode z keeps its volatility-encoding meaning.
        z=(
            EMBEDDING_CENTER
            if embedding_dimensions == 3
            else max(0.1, min(0.95, 0.25 + _annualized_volatility(returns)))
        ),
        market_distance=1.0,
        correlation_strength=0.0,
        volatility_pressure=_annualized_volatility(returns),
        topology_risk="isolated",
        regime_label=regime_label,
        top_peers=[],
        top_peer_returns=[],
    )


def rank_correlated_peers(
    symbol: str,
    eligible_symbols: list[str],
    correlation_fn: Callable[[str, str], float],
    top_n: int,
) -> list[str]:
    """Ranks every OTHER eligible symbol by descending correlation to
    `symbol` across the WHOLE eligible universe (not just `symbol`'s own
    cluster - a correlation_threshold-defined cluster can be much smaller
    than top_n), returning up to `top_n` symbols. Ties broken
    alphabetically for determinism (matches this module's existing
    tie-breaking convention, e.g. sorted_roots/nodes.sort() below)."""
    others = [other for other in eligible_symbols if other != symbol]
    ranked = sorted(others, key=lambda other: (-correlation_fn(symbol, other), other))
    return ranked[:top_n]


def build_market_topology(
    returns_by_symbol: dict[str, list[float]],
    regime_labels_by_symbol: dict[str, str] | None = None,
    correlation_threshold: float = 0.6,
    link_threshold: float = 0.5,
    min_observations: int = 5,
    embedding_iterations: int = 100,
    previous_positions: dict[str, tuple[float, ...]] | None = None,
    convergence_tolerance: float | None = None,
    top_peers_n: int = 3,
    previous_correlations: dict[tuple[str, str], float] | None = None,
    correlation_stability_tolerance: float | None = None,
    embedding_dimensions: int = 2,
) -> MarketTopology:
    """`embedding_dimensions` (V4-W3, `phase_v2.topology.embedding_dimensions`,
    default 2) selects how many axes SMACOF embeds. At 2 - the default -
    every coordinate, reason string and dimension is byte-identical to the
    pre-V4 behavior, and z stays the volatility encoding. At 3, z becomes
    a real correlation-distance axis on the same 0..100 scale as x/y, and
    volatility is carried by node radius in the webui instead."""
    regime_labels_by_symbol = regime_labels_by_symbol or {}
    reasons: list[str] = []
    embed_3d = embedding_dimensions == 3

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
                embedding_dimensions,
            )
            for index, symbol in enumerate(sorted(returns_by_symbol))
        ]
        return MarketTopology(
            state="insufficient_data",
            nodes=isolated_nodes,
            links=[],
            clusters=[],
            dimensions=_dimensions_for(embedding_dimensions),
            reasons=reasons,
            correlations={},
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
    seed_positions: dict[str, tuple[float, ...]] = {}
    # Hoisted out of Pass 3 (where it used to be computed) because the 3D
    # seed below needs it too - computing it once keeps the two uses from
    # drifting apart and saves a second pass over every return series.
    volatility_by_symbol = {symbol: _annualized_volatility(returns_by_symbol[symbol]) for symbol in eligible_symbols}

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
            if embed_3d:
                # Seed z from the same volatility value 2D mode encodes
                # there directly, spread across a range comparable to the
                # x/y seed. SMACOF only separates points along directions
                # its seed already separates them on, so seeding z flat
                # (or on the raw 0.1..0.95 volatility scale, which is
                # ~1/100th of the x/y spread) would collapse the third
                # axis - the layout would stay visually 2D.
                volatility_z = max(0.1, min(0.95, 0.25 + volatility_by_symbol[symbol]))
                seed_z = EMBEDDING_CENTER + (volatility_z - 0.5) * EMBEDDING_Z_SEED_SPREAD
                seed_positions[symbol] = (seed_x, seed_y, seed_z)
            else:
                seed_positions[symbol] = (seed_x, seed_y)

    # development/Problems.md#36: skip re-running the expensive Pass 2
    # embedding entirely when correlation structure hasn't materially
    # changed bar-to-bar - reuse the prior bar's already-converged,
    # already-rescaled positions directly instead of paying SMACOF's
    # ~500-600ms/bar cost again for a result that would barely move. Only
    # valid when the eligible-symbol universe is unchanged (a new/dropped
    # symbol always forces a full recompute - set(correlations.keys()) ==
    # set(previous_correlations.keys()) is sufficient to guarantee this,
    # since pair-keys uniquely determine the symbol set once >=2 symbols
    # are eligible) and every pairwise correlation moved by no more than
    # correlation_stability_tolerance. Off by default
    # (correlation_stability_tolerance=None, from main.py's
    # phase_v2.topology.cache_enabled=false) - previous_correlations/
    # correlation_stability_tolerance both being None reproduces today's
    # exact always-fresh-compute behavior, byte-identical, same contract
    # the Part D2 warm-start feature below already guarantees.
    # V4-W3: positions carried over from a run at a different
    # embedding_dimensions (the flag flipped between bars, or a resumed
    # run) have the wrong tuple width - reusing or seeding from them would
    # either drop the z axis or blow up the numpy stack. Treat them as
    # absent, exactly like a symbol the previous bar never saw.
    if previous_positions is not None:
        previous_positions = {
            symbol: point for symbol, point in previous_positions.items() if len(point) == embedding_dimensions
        }
        if not previous_positions:
            previous_positions = None

    can_reuse_previous_embedding = (
        correlation_stability_tolerance is not None
        and previous_correlations is not None
        and previous_positions is not None
        and set(correlations.keys()) == set(previous_correlations.keys())
        and set(eligible_symbols).issubset(previous_positions.keys())
    )
    if can_reuse_previous_embedding:
        max_correlation_change = max(
            (abs(correlations[key] - previous_correlations[key]) for key in correlations),
            default=0.0,
        )
        can_reuse_previous_embedding = max_correlation_change <= correlation_stability_tolerance

    if can_reuse_previous_embedding:
        final_positions = {symbol: previous_positions[symbol] for symbol in eligible_symbols}
        reasons.append("topology_embedding_reused_stable_correlations")
    else:
        # Part D2 warm start: for any eligible symbol present in
        # previous_positions (the prior bar's converged embedding), seed
        # SMACOF from there instead of the cosmetic angle-based layout
        # above - correlations evolve slowly bar to bar, so the prior
        # bar's embedding is typically already close to this bar's
        # stationary point. Symbols absent from previous_positions (new
        # to the universe, or isolated last bar) fall back to the
        # cosmetic seed untouched.
        if previous_positions:
            for symbol in eligible_symbols:
                if symbol in previous_positions:
                    seed_positions[symbol] = previous_positions[symbol]

        # Pass 2: real distance-preserving embedding -- pairwise distance
        # across ALL eligible symbols (not just within-cluster pairs;
        # cross-cluster distance matters for a meaningful layout too),
        # seeded from the cosmetic layout (or the warm-start layout
        # above) so the result is deterministic and converges fast. This
        # is what makes spatial distance actually reflect correlation
        # distance instead of arbitrary index-based placement.
        final_positions = _rescale_positions_to_bounds(
            _stress_majorize(
                eligible_symbols,
                lambda symbol_a, symbol_b: max(0.0, 1.0 - correlation_between(symbol_a, symbol_b)),
                seed_positions,
                iterations=embedding_iterations,
                convergence_tolerance=convergence_tolerance,
            )
        )

    # Pass 3: build nodes from the real embedding + per-symbol metadata.
    default_position = (EMBEDDING_CENTER,) * embedding_dimensions
    for symbol in eligible_symbols:
        position = final_positions.get(symbol, default_position)
        x, y = position[0], position[1]
        volatility_pressure = volatility_by_symbol[symbol]
        # 3D mode: z is the embedding's third axis. 2D mode: z keeps its
        # original volatility encoding, untouched.
        z = position[2] if embed_3d else max(0.1, min(0.95, 0.25 + volatility_pressure))

        if member_count_by_symbol[symbol] == 1:
            topology_risk = "isolated"
        elif volatility_pressure >= ELEVATED_VOLATILITY_THRESHOLD:
            topology_risk = "elevated"
        else:
            topology_risk = "normal"

        top_peer_symbols = rank_correlated_peers(symbol, eligible_symbols, correlation_between, top_peers_n)
        top_peer_returns = [returns_by_symbol[peer][-1] for peer in top_peer_symbols]

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
                top_peers=top_peer_symbols,
                top_peer_returns=top_peer_returns,
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
                embedding_dimensions,
            )
        )

    nodes.sort(key=lambda node: node.symbol)
    links.sort(key=lambda link: (link.source, link.target))

    return MarketTopology(
        state="ready",
        nodes=nodes,
        links=links,
        clusters=clusters,
        dimensions=_dimensions_for(embedding_dimensions),
        reasons=reasons,
        correlations=correlations,
    )
