from execution.cost_model import (
    build_net_edge_decision,
    estimate_round_trip_cost_bps,
    expected_edge_bps,
)


def _cost_config(**overrides):
    config = {
        "enabled": True,
        "edge_bps_per_rank_unit": 50.0,
        "holding_bars": 10,
        "horizon_days": 20,
        "commission_bps_per_side": 1.0,
        "min_commission_usd": 1.0,
        "extra_slippage_bps": 0.0,
        "min_net_edge_bps": 0.0,
    }
    config.update(overrides)
    return config


def test_disabled_gate_always_passes():
    decision = build_net_edge_decision(0.9, {"estimated_round_trip_cost": 0.01}, 10_000, _cost_config(enabled=False))
    assert decision.passes is True
    assert decision.reason == "net_edge_gate_disabled"
    assert decision.net_edge_bps == 0.0


def test_uncalibrated_edge_per_rank_unit_always_passes():
    decision = build_net_edge_decision(
        0.9, {"estimated_round_trip_cost": 0.01}, 10_000, _cost_config(edge_bps_per_rank_unit=0.0)
    )
    assert decision.passes is True
    assert decision.reason == "net_edge_gate_disabled"


def test_missing_predicted_rank_always_passes():
    decision = build_net_edge_decision(None, {"estimated_round_trip_cost": 0.01}, 10_000, _cost_config())
    assert decision.passes is True
    assert decision.reason == "net_edge_gate_disabled"


def test_rank_of_exactly_median_has_zero_expected_edge():
    edge = expected_edge_bps(0.5, edge_bps_per_rank_unit=50.0, holding_bars=10, horizon_days=20)
    assert edge == 0.0


def test_edge_scales_linearly_with_rank_deviation():
    edge_top = expected_edge_bps(1.0, edge_bps_per_rank_unit=50.0, holding_bars=20, horizon_days=20)
    edge_mid = expected_edge_bps(0.75, edge_bps_per_rank_unit=50.0, holding_bars=20, horizon_days=20)
    assert edge_top == 50.0
    assert edge_mid == 25.0


def test_edge_scales_down_when_holding_shorter_than_the_horizon():
    full_horizon = expected_edge_bps(1.0, edge_bps_per_rank_unit=50.0, holding_bars=20, horizon_days=20)
    half_horizon = expected_edge_bps(1.0, edge_bps_per_rank_unit=50.0, holding_bars=10, horizon_days=20)
    assert half_horizon == full_horizon / 2.0


def test_bottom_ranked_asset_has_negative_expected_edge():
    edge = expected_edge_bps(0.0, edge_bps_per_rank_unit=50.0, holding_bars=20, horizon_days=20)
    assert edge == -50.0


def test_estimated_round_trip_cost_bps_reads_liquidity_payload_without_recomputing():
    cost = estimate_round_trip_cost_bps(
        {"estimated_round_trip_cost": 0.002},
        commission_bps_per_side=1.0,
        min_commission_usd=1.0,
        order_value=10_000.0,
        extra_slippage_bps=0.0,
    )
    # 0.002 fraction -> 20 bps, plus commission (10000 * 1bps/1e4 = $1.00,
    # already >= min_commission_usd) -> 1 bps effective commission.
    assert cost == 21.0


def test_estimated_round_trip_cost_bps_commission_floor_dominates_small_orders():
    cost = estimate_round_trip_cost_bps(
        {"estimated_round_trip_cost": 0.001},
        commission_bps_per_side=1.0,
        min_commission_usd=5.0,
        order_value=1_000.0,
        extra_slippage_bps=0.0,
    )
    # 1000 * 1bps/1e4 = $0.10, below the $5 floor -> commission floor wins:
    # $5 / $1000 * 1e4 = 50 bps effective commission.
    assert cost == 10.0 + 50.0


def test_estimated_round_trip_cost_bps_smaller_order_value_shows_higher_effective_bps():
    # V5.2.1 (development/Problems.md) - documents WHY main.py's Pass 2 now
    # feeds this function the actual incremental trade size (target minus
    # already-held weight) instead of the full target notional: the SAME
    # dollar-floor commission is a much larger effective bps rate against a
    # small resize than against a large fresh-entry notional, so gating on
    # the wrong (larger) notional understates real cost for exactly the
    # small, frequent resizes should_scale_position() exists to catch.
    liquidity_payload = {"estimated_round_trip_cost": 0.0005}  # 5 bps, identical both times
    full_notional_cost = estimate_round_trip_cost_bps(
        liquidity_payload, commission_bps_per_side=1.0, min_commission_usd=1.0,
        order_value=12_000.0, extra_slippage_bps=0.0,
    )
    small_resize_cost = estimate_round_trip_cost_bps(
        liquidity_payload, commission_bps_per_side=1.0, min_commission_usd=1.0,
        order_value=300.0, extra_slippage_bps=0.0,
    )
    assert small_resize_cost > full_notional_cost


def test_estimated_round_trip_cost_bps_zero_order_value_skips_commission_floor():
    cost = estimate_round_trip_cost_bps(
        {"estimated_round_trip_cost": 0.001},
        commission_bps_per_side=1.0,
        min_commission_usd=5.0,
        order_value=0.0,
        extra_slippage_bps=2.0,
    )
    assert cost == 10.0 + 2.0


def test_net_edge_cost_monotone_in_participation_rate():
    low_cost = build_net_edge_decision(0.95, {"estimated_round_trip_cost": 0.0005}, 10_000, _cost_config())
    high_cost = build_net_edge_decision(0.95, {"estimated_round_trip_cost": 0.01}, 10_000, _cost_config())
    assert high_cost.expected_cost_bps > low_cost.expected_cost_bps
    assert high_cost.net_edge_bps < low_cost.net_edge_bps


def test_net_edge_decision_passes_when_edge_clears_the_min_threshold():
    decision = build_net_edge_decision(
        0.95, {"estimated_round_trip_cost": 0.0005}, 10_000, _cost_config(min_net_edge_bps=2.0)
    )
    assert decision.passes is True
    assert decision.reason == "net_edge_clears_cost"


def test_net_edge_decision_fails_when_cost_swamps_the_edge():
    decision = build_net_edge_decision(
        0.95, {"estimated_round_trip_cost": 0.02}, 10_000, _cost_config(min_net_edge_bps=2.0)
    )
    assert decision.passes is False
    assert decision.reason == "net_edge_below_min_threshold"


def test_net_edge_decision_to_dict_shape():
    decision = build_net_edge_decision(0.9, {"estimated_round_trip_cost": 0.001}, 10_000, _cost_config())
    payload = decision.to_dict()
    assert set(payload) == {"expected_edge_bps", "expected_cost_bps", "net_edge_bps", "passes", "reason"}


def test_trade_direction_defaults_to_long_reproducing_today_exactly():
    edge = expected_edge_bps(0.0, edge_bps_per_rank_unit=50.0, holding_bars=20, horizon_days=20)
    assert edge == -50.0


def test_bottom_ranked_short_has_positive_edge_in_the_direction_of_the_trade():
    # A bottom-ranked asset (expected to fall) traded SHORT profits from
    # that fall - the edge in the direction of the trade is positive, even
    # though the raw long-side rank_deviation is negative.
    edge = expected_edge_bps(0.0, edge_bps_per_rank_unit=50.0, holding_bars=20, horizon_days=20, trade_direction=-1)
    assert edge == 50.0


def test_top_ranked_long_has_positive_edge_in_the_direction_of_the_trade():
    edge = expected_edge_bps(1.0, edge_bps_per_rank_unit=50.0, holding_bars=20, horizon_days=20, trade_direction=1)
    assert edge == 50.0


def test_mismatched_direction_has_negative_edge():
    # Going long a bottom-ranked asset (or short a top-ranked one) is
    # against the rank's own view - the gate should see negative edge and
    # veto it, not silently ignore direction.
    edge = expected_edge_bps(0.0, edge_bps_per_rank_unit=50.0, holding_bars=20, horizon_days=20, trade_direction=1)
    assert edge == -50.0


def test_build_net_edge_decision_short_side_passes_when_rank_supports_it():
    # The regression this fixes: previously every short was vetoed
    # unconditionally because the gate only ever measured raw long-side
    # edge. A bottom-ranked (rank=0.02) short with a real calibrated edge
    # must now be able to pass, exactly like an equivalent long does.
    short_decision = build_net_edge_decision(
        0.02, {"estimated_round_trip_cost": 0.0005}, 10_000, _cost_config(min_net_edge_bps=2.0), trade_direction=-1
    )
    long_decision = build_net_edge_decision(
        0.98, {"estimated_round_trip_cost": 0.0005}, 10_000, _cost_config(min_net_edge_bps=2.0), trade_direction=1
    )
    assert short_decision.passes is True
    assert short_decision.expected_edge_bps == long_decision.expected_edge_bps
    assert short_decision.net_edge_bps == long_decision.net_edge_bps


def test_build_net_edge_decision_short_side_still_blocked_without_direction_fix():
    # Same short candidate, but with the (wrong) default trade_direction=1
    # - reproduces the pre-fix bug so a future regression here is caught.
    decision = build_net_edge_decision(
        0.02, {"estimated_round_trip_cost": 0.0005}, 10_000, _cost_config(min_net_edge_bps=2.0)
    )
    assert decision.passes is False
