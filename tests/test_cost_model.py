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
