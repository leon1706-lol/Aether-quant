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

import math
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


def fee_override_for_security_type(cost_config: dict, security_type: str | None) -> dict | None:
    """`phase_v2.costs.fee_by_type[<security_type>]` when it carries a finite, non-negative `fee_bps`, else None
    (the global commission terms apply, exactly as before the key existed)."""
    if not security_type:
        return None
    override = (cost_config.get("fee_by_type") or {}).get(str(security_type))
    if not isinstance(override, dict):
        return None
    try:
        fee_bps = float(override.get("fee_bps"))
    except (TypeError, ValueError):
        return None
    return override if math.isfinite(fee_bps) and fee_bps >= 0.0 else None


def commission_terms_for_security_type(cost_config: dict, security_type: str | None) -> tuple[float, float]:
    """(commission_bps_per_side, min_commission_usd) for one security type: the per-class override when
    configured (crypto pays a percentage exchange fee with no dollar floor, unlike IB's per-share
    equity commission), else the global terms."""
    override = fee_override_for_security_type(cost_config, security_type)
    if override is None:
        return float(cost_config.get("commission_bps_per_side", 0.0)), float(cost_config.get("min_commission_usd", 0.0))
    return float(override["fee_bps"]), float(override.get("min_usd", 0.0) or 0.0)


def commission_bps_by_ticker(cost_config: dict, security_type_by_ticker: dict[str, str]) -> dict[str, float]:
    """Per-ticker per-side commission bps for every ticker whose security type has a fee override - the
    offline simulator's `commission_bps_by_ticker`, so it charges the same fee the live gate assumes. An override
    may carry `sim_fee_bps` when a dollar floor (`min_usd`) makes its true cost per fill larger than `fee_bps` at
    realistic order sizes (forex: IB's $2 minimum on ~$2.6k fills is ~7.6 bps) - the simulator has no per-order floor."""
    return {
        ticker: float(override.get("sim_fee_bps", override["fee_bps"]))
        for ticker, security_type in security_type_by_ticker.items()
        if (override := fee_override_for_security_type(cost_config, security_type)) is not None
    }


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
    so it is skipped rather than divided-by-zero.

    V5.4.5 (development/Problems.md #116): the commission leg now covers
    BOTH sides of the round trip. The original math charged exactly one
    side's commission (rate leg and min_commission_usd floor alike) against
    a function whose contract - and this parameter's own name - is per-SIDE
    cost for a ROUND-TRIP estimate, understating expected cost by up to 2x
    and letting trades through whose true net edge was below the gate."""
    round_trip_fraction = float(liquidity_payload.get("estimated_round_trip_cost", 0.0) or 0.0)
    round_trip_bps = round_trip_fraction * 10_000.0

    commission_bps_effective = 0.0
    if order_value > 0.0:
        commission_from_rate_usd = order_value * commission_bps_per_side / 10_000.0
        # Each side's commission = max(rate leg, dollar floor); a round trip
        # pays it twice (entry + exit), same notional both ways.
        per_side_commission_usd = max(commission_from_rate_usd, min_commission_usd)
        round_trip_commission_usd = 2.0 * per_side_commission_usd
        commission_bps_effective = round_trip_commission_usd / order_value * 10_000.0

    return round_trip_bps + commission_bps_effective + extra_slippage_bps


def expected_edge_bps(
    predicted_rank: float | None,
    *,
    edge_bps_per_rank_unit: float,
    holding_bars: int,
    horizon_days: int,
    trade_direction: int = 1,
) -> float:
    """Linear-in-rank-deviation expected edge estimate, measured IN THE
    DIRECTION OF THE TRADE. rank_deviation = (rank - 0.5) * 2 is positive
    for a top-ranked asset (expected to rise) and negative for a
    bottom-ranked one (expected to fall) - `trade_direction` (+1 long, -1
    short) says which side the caller actually intends to trade, so the
    result is the edge realized if that trade is entered, not merely the
    raw long-side edge.

    A rank of 0.5 (median - no view) always has zero expected edge. A rank
    of 1.0/0.0 has the full edge_bps_per_rank_unit magnitude, on whichever
    side the rank itself favors (long the top, short the bottom) - the
    book case, where trade_direction is derived from the same rank that
    picked the side, so the product is always the FULL magnitude,
    never negative. A mismatched trade (e.g. going long a bottom-ranked
    asset) correctly comes out negative and gets vetoed downstream.

    Scaled down by min(1, holding_bars/horizon_days) - the rank head's own
    forward horizon (horizon_days, e.g. 20 for rank_20d) is how long the
    FULL predicted move is expected to take; holding for fewer bars than
    that only captures a fraction of it.

    predicted_rank=None (model unavailable this bar) -> 0.0, the safe
    no-edge default, matching every other "missing prediction never
    changes trading behavior" contract in this codebase.

    GUARDRAIL (Problems.md - net-edge gate blocked 100% of shorts): before
    this parameter existed, the gate measured only the raw long-side edge
    and applied it unconditionally to buy/sell/short decisions alike, so
    every short entry (negative rank_deviation) was vetoed on every bar.
    trade_direction must always be threaded through from the caller's own
    signed intent (e.g. sign of the pre-cost target_weight) - never left
    at the default 1 for a short trade."""
    if predicted_rank is None:
        return 0.0
    rank_deviation = (float(predicted_rank) - 0.5) * 2.0
    # V5.4.5: horizon_days <= 0 is a misconfiguration - previously the
    # else-branch handed back the FULL edge fraction (1.0), maximizing
    # exactly the trade the broken config should have neutralized. A
    # horizon that can't be interpreted conservatively yields NO edge.
    if horizon_days <= 0:
        return 0.0
    horizon_fraction = min(1.0, float(holding_bars) / float(horizon_days))
    direction_sign = 1.0 if trade_direction >= 0 else -1.0
    edge = edge_bps_per_rank_unit * rank_deviation * horizon_fraction * direction_sign
    return edge if math.isfinite(edge) else 0.0


def build_net_edge_decision(
    predicted_rank: float | None,
    liquidity_payload: dict,
    order_value: float,
    cost_config: dict,
    *,
    trade_direction: int = 1,
    security_type: str | None = None,
) -> NetEdgeDecision:
    """The one call site analyzer/market_analyzer.py's Priority 6.5 tier
    and risk/position_sizing.py::cost_sizing_multiplier() both consume.

    `trade_direction` (+1 long, -1 short) must be the sign of the trade
    actually being evaluated - see expected_edge_bps()'s docstring for why
    this parameter exists at all. Defaults to 1 (long) only so callers
    that genuinely never trade short (or existing tests exercising the
    long side) do not need to pass it; every live call site must supply
    the real signed direction.

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
        trade_direction=trade_direction,
    )
    commission_bps_per_side, min_commission_usd = commission_terms_for_security_type(cost_config, security_type)
    expected_cost = estimate_round_trip_cost_bps(
        liquidity_payload,
        commission_bps_per_side=commission_bps_per_side,
        min_commission_usd=min_commission_usd,
        order_value=order_value,
        extra_slippage_bps=float(cost_config.get("extra_slippage_bps", 0.0)),
    )
    # V5.4.5 (development/Problems.md #117): a NaN cost/edge previously
    # flowed straight into the comparison - `nan >= threshold` is False, so
    # the gate still failed closed but with the misleading generic
    # "net_edge_below_min_threshold" reason (indistinguishable from an
    # ordinary signal veto). NaN is now caught explicitly: fail CLOSED with
    # a reason that names the real cause. Reported magnitudes stay finite
    # (1e12 sentinel) so JSON state exports remain valid.
    if not math.isfinite(expected_cost):
        return NetEdgeDecision(
            expected_edge_bps=expected_edge,
            expected_cost_bps=1e12,
            net_edge_bps=-1e12,
            passes=False,
            reason="non_finite_cost_estimate",
        )
    net_edge = expected_edge - expected_cost
    min_net_edge_bps = float(cost_config.get("min_net_edge_bps", 0.0))
    passes = math.isfinite(net_edge) and net_edge >= min_net_edge_bps

    return NetEdgeDecision(
        expected_edge_bps=expected_edge,
        expected_cost_bps=expected_cost,
        net_edge_bps=net_edge if math.isfinite(net_edge) else -1e12,
        passes=passes,
        reason=(
            "net_edge_clears_cost" if passes
            else "non_finite_expected_edge" if not math.isfinite(expected_edge)
            else "net_edge_below_min_threshold"
        ),
    )
