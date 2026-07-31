"""Expected-net-edge cost model (V5.1 Phase 0/1, item 3 of the V5.1
roadmap - the actual root cause of the fee drag: $2,769 in fees on $3,159
gross profit). Answers the one question nothing in this codebase asked
before: does this trade's expected edge clear its expected cost?

Deliberately its own module in the existing execution/ package (sibling to
order_gate.py, which already owns every other fill/slippage-cost function):
this is the ENTRY-DECISION side of cost-awareness (should we trade at all,
how much edge is left after cost), where order_gate.py is entirely the
FILL side (how the already-decided trade's price gets adjusted). Reuses
order_gate-adjacent liquidity data rather than recomputing it - see
estimate_round_trip_cost_bps()'s docstring.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class NetEdgeDecision:
    expected_edge_bps: float
    expected_cost_bps: float
    net_edge_bps: float
    passes: bool
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def estimate_round_trip_cost_bps(
    liquidity_payload: dict,
    *,
    commission_bps_per_side: float,
    min_commission_usd: float,
    order_value: float,
    extra_slippage_bps: float,
) -> float:
    """Reads liquidity_payload["estimated_round_trip_cost"] - already
    computed by liquidity/market_liquidity.py::build_liquidity_decision()
    (a fraction, e.g. 0.001 = 10bps) - and NEVER recomputes slippage; one
    estimate per bar, consistently used everywhere (the same rule
    main.py:1768-1771's own comment states). Adds the commission leg,
    expressed as bps of order_value with a min_commission_usd dollar floor
    (a small order can be commission-dominated even at a low bps rate),
    plus any extra_slippage_bps buffer (a deliberately simple manual
    safety margin, config-gated, defaults to 0.0).

    order_value <= 0 (no order, or a zero-target-weight decision) returns
    just the liquidity round-trip cost plus extra_slippage_bps - the
    commission-floor conversion to bps is undefined at zero order value,
    so it is skipped rather than divided-by-zero."""
    round_trip_fraction = float(liquidity_payload.get("estimated_round_trip_cost", 0.0) or 0.0)
    round_trip_bps = round_trip_fraction * 10_000.0

    commission_bps_effective = 0.0
    if order_value > 0.0:
        commission_from_rate_usd = order_value * commission_bps_per_side / 10_000.0
        commission_dollars = max(commission_from_rate_usd, min_commission_usd)
        commission_bps_effective = commission_dollars / order_value * 10_000.0

    return round_trip_bps + commission_bps_effective + extra_slippage_bps


def expected_edge_bps(
    predicted_rank: float | None,
    *,
    edge_bps_per_rank_unit: float,
    holding_bars: int,
    horizon_days: int,
) -> float:
    """Linear-in-rank-deviation expected edge estimate: a predicted rank of
    0.5 (median - no view) has zero expected edge; a rank of 1.0 (top of
    the universe) or 0.0 (bottom) has the full edge_bps_per_rank_unit
    magnitude. Scaled down by min(1, holding_bars/horizon_days) - the rank
    head's own forward horizon (horizon_days, e.g. 20 for rank_20d) is how
    long the FULL predicted move is expected to take; holding for fewer
    bars than that only captures a fraction of it.

    predicted_rank=None (model unavailable this bar) -> 0.0, the safe
    no-edge default, matching every other "missing prediction never
    changes trading behavior" contract in this codebase."""
    if predicted_rank is None:
        return 0.0
    rank_deviation = (float(predicted_rank) - 0.5) * 2.0
    horizon_fraction = min(1.0, float(holding_bars) / float(horizon_days)) if horizon_days > 0 else 1.0
    return edge_bps_per_rank_unit * rank_deviation * horizon_fraction


def build_net_edge_decision(
    predicted_rank: float | None,
    liquidity_payload: dict,
    order_value: float,
    cost_config: dict,
) -> NetEdgeDecision:
    """The one call site analyzer/market_analyzer.py's Priority 6.5 tier
    and risk/position_sizing.py::cost_sizing_multiplier() both consume.

    FAIL-OPEN, always: returns passes=True, reason="net_edge_gate_disabled"
    whenever cost_config["enabled"] is false, edge_bps_per_rank_unit is
    0.0 (uncalibrated - see `aq evaluate --calibrate-edge`), or
    predicted_rank is None. An uncalibrated or disabled cost model must
    never block a trade - the exact same "missing/degraded signal never
    changes trading behavior" contract every other optional overlay in
    this codebase (topology_sizing_multiplier(), rank_sizing_multiplier())
    already follows."""
    enabled = bool(cost_config.get("enabled", False))
    edge_bps_per_rank_unit = float(cost_config.get("edge_bps_per_rank_unit", 0.0))

    if not enabled or edge_bps_per_rank_unit == 0.0 or predicted_rank is None:
        return NetEdgeDecision(
            expected_edge_bps=0.0,
            expected_cost_bps=0.0,
            net_edge_bps=0.0,
            passes=True,
            reason="net_edge_gate_disabled",
        )

    expected_edge = expected_edge_bps(
        predicted_rank,
        edge_bps_per_rank_unit=edge_bps_per_rank_unit,
        holding_bars=int(cost_config.get("holding_bars", 10)),
        horizon_days=int(cost_config.get("horizon_days", 20)),
    )
    expected_cost = estimate_round_trip_cost_bps(
        liquidity_payload,
        commission_bps_per_side=float(cost_config.get("commission_bps_per_side", 0.0)),
        min_commission_usd=float(cost_config.get("min_commission_usd", 0.0)),
        order_value=order_value,
        extra_slippage_bps=float(cost_config.get("extra_slippage_bps", 0.0)),
    )
    net_edge = expected_edge - expected_cost
    min_net_edge_bps = float(cost_config.get("min_net_edge_bps", 0.0))
    passes = net_edge >= min_net_edge_bps

    return NetEdgeDecision(
        expected_edge_bps=expected_edge,
        expected_cost_bps=expected_cost,
        net_edge_bps=net_edge,
        passes=passes,
        reason="net_edge_clears_cost" if passes else "net_edge_below_min_threshold",
    )
