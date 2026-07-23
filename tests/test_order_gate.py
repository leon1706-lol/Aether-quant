import pytest

from execution import (
    DEFAULT_FILL_SLIPPAGE_SOURCE,
    MAX_LIQUIDITY_SLIPPAGE_BPS,
    VALID_FILL_SLIPPAGE_SOURCES,
    classify_order_status,
    is_real_order_placement,
    liquidity_cost_fraction,
    resolve_fill_slippage,
    resolve_fill_slippage_source,
    resolve_limit_price,
    resolve_order_permission,
    resolve_runtime_mode,
    resolve_slippage_bps,
    simulate_fill,
    slippage_amount,
)


def test_backtest_mode_always_allows_orders():
    allowed, reason = resolve_order_permission(
        mode="backtest",
        allow_live_orders=False,
        broker_config_present=False,
        risk_locks_healthy=False,
    )

    assert allowed is True
    assert reason == "backtest_unrestricted"


def test_observation_mode_never_allows_orders_even_if_flags_true():
    allowed, reason = resolve_order_permission(
        mode="observation",
        allow_live_orders=True,
        broker_config_present=True,
        risk_locks_healthy=True,
    )

    assert allowed is False
    assert reason == "observation_mode_no_real_orders"


def test_paper_mode_requires_both_flag_and_broker_config():
    combinations = [
        (False, False, False),
        (False, True, False),
        (True, False, False),
        (True, True, True),
    ]

    for allow_live_orders, broker_config_present, expected_allowed in combinations:
        allowed, reason = resolve_order_permission(
            mode="paper",
            allow_live_orders=allow_live_orders,
            broker_config_present=broker_config_present,
            risk_locks_healthy=True,
        )

        assert allowed is expected_allowed
        if expected_allowed:
            assert reason == "paper_orders_enabled"
        else:
            assert reason == "paper_orders_blocked_missing_flag_or_broker_config"


def test_live_mode_requires_flag_and_broker_and_healthy_risk_lock():
    for allow_live_orders in (True, False):
        for broker_config_present in (True, False):
            for risk_locks_healthy in (True, False):
                allowed, reason = resolve_order_permission(
                    mode="live",
                    allow_live_orders=allow_live_orders,
                    broker_config_present=broker_config_present,
                    risk_locks_healthy=risk_locks_healthy,
                )

                expected_allowed = allow_live_orders and broker_config_present and risk_locks_healthy
                assert allowed is expected_allowed
                if expected_allowed:
                    assert reason == "live_orders_enabled"
                else:
                    assert reason == "live_orders_blocked_missing_flag_or_broker_config_or_risk_lock"


def test_unknown_mode_defaults_to_blocked():
    allowed, reason = resolve_order_permission(
        mode="banana",
        allow_live_orders=True,
        broker_config_present=True,
        risk_locks_healthy=True,
    )

    assert allowed is False
    assert reason == "unknown_mode_defaults_to_no_orders"


def test_resolve_runtime_mode_falls_back_to_observation_for_missing_or_unknown():
    assert resolve_runtime_mode(None) == "observation"
    assert resolve_runtime_mode("") == "observation"
    assert resolve_runtime_mode("banana") == "observation"


def test_resolve_runtime_mode_passes_through_valid_values():
    for mode in ("backtest", "observation", "paper", "live"):
        assert resolve_runtime_mode(mode) == mode


def test_simulate_fill_computes_expected_quantity_and_notional():
    result = simulate_fill(
        close_price=100.0,
        target_weight=0.25,
        equity=10_000.0,
    )

    assert result["fill_price"] == 100.0
    assert result["notional"] == 2_500.0
    assert result["quantity"] == 25.0


def test_simulate_fill_applies_slippage():
    result = simulate_fill(
        close_price=100.0,
        target_weight=0.10,
        equity=10_000.0,
        slippage_bps=50.0,
    )

    assert round(result["fill_price"], 6) == 100.5
    assert round(result["quantity"], 6) == round(1_000.0 / 100.5, 6)


def test_simulate_fill_handles_non_positive_price_safely():
    result = simulate_fill(
        close_price=0.0,
        target_weight=0.10,
        equity=10_000.0,
    )

    assert result == {"fill_price": 0.0, "notional": 0.0, "quantity": 0.0}


def test_slippage_amount_computes_bps_of_price():
    assert slippage_amount(100.0, 50.0) == 0.5
    assert slippage_amount(200.0, 100.0) == 2.0


def test_slippage_amount_is_zero_for_non_positive_price_or_bps():
    assert slippage_amount(0.0, 50.0) == 0.0
    assert slippage_amount(-10.0, 50.0) == 0.0
    assert slippage_amount(100.0, 0.0) == 0.0
    assert slippage_amount(100.0, -5.0) == 0.0


def test_resolve_slippage_bps_looks_up_symbol():
    bps_by_symbol = {"AAPL": 12.5, "MSFT": 3.0}

    assert resolve_slippage_bps("AAPL", bps_by_symbol) == 12.5
    assert resolve_slippage_bps("MSFT", bps_by_symbol) == 3.0


def test_resolve_slippage_bps_missing_symbol_defaults_to_zero():
    assert resolve_slippage_bps("AAPL", {}) == 0.0


def test_resolve_slippage_bps_clamps_to_max():
    bps_by_symbol = {"AAPL": MAX_LIQUIDITY_SLIPPAGE_BPS * 10}

    assert resolve_slippage_bps("AAPL", bps_by_symbol) == MAX_LIQUIDITY_SLIPPAGE_BPS


def test_resolve_slippage_bps_clamps_negative_to_zero():
    bps_by_symbol = {"AAPL": -25.0}

    assert resolve_slippage_bps("AAPL", bps_by_symbol) == 0.0


def test_resolve_fill_slippage_matches_slippage_amount_of_clamped_bps():
    bps_by_symbol = {"AAPL": 50.0}

    result = resolve_fill_slippage("AAPL", 100.0, bps_by_symbol)

    assert result == slippage_amount(100.0, 50.0) == 0.5


def test_resolve_fill_slippage_missing_symbol_is_zero():
    assert resolve_fill_slippage("AAPL", 100.0, {}) == 0.0


def test_resolve_slippage_bps_default_max_bps_matches_module_constant():
    bps_by_symbol = {"AAPL": MAX_LIQUIDITY_SLIPPAGE_BPS * 10}

    assert resolve_slippage_bps("AAPL", bps_by_symbol) == MAX_LIQUIDITY_SLIPPAGE_BPS


def test_resolve_slippage_bps_honors_custom_max_bps():
    bps_by_symbol = {"AAPL": 200.0}

    # A tighter custom ceiling clamps below the estimate.
    assert resolve_slippage_bps("AAPL", bps_by_symbol, max_bps=50.0) == 50.0
    # A looser custom ceiling lets the full estimate through.
    assert resolve_slippage_bps("AAPL", bps_by_symbol, max_bps=1000.0) == 200.0


def test_resolve_slippage_bps_custom_max_bps_still_clamps_negative_to_zero():
    bps_by_symbol = {"AAPL": -25.0}

    assert resolve_slippage_bps("AAPL", bps_by_symbol, max_bps=50.0) == 0.0


def test_resolve_fill_slippage_honors_custom_max_bps():
    bps_by_symbol = {"AAPL": 200.0}

    result = resolve_fill_slippage("AAPL", 100.0, bps_by_symbol, max_bps=50.0)

    assert result == slippage_amount(100.0, 50.0)


def test_resolve_fill_slippage_source_passes_through_valid_values():
    for source in VALID_FILL_SLIPPAGE_SOURCES:
        assert resolve_fill_slippage_source(source) == source


def test_resolve_fill_slippage_source_falls_back_to_default_for_missing_or_unknown():
    assert resolve_fill_slippage_source(None) == DEFAULT_FILL_SLIPPAGE_SOURCE
    assert resolve_fill_slippage_source("") == DEFAULT_FILL_SLIPPAGE_SOURCE
    assert resolve_fill_slippage_source("banana") == DEFAULT_FILL_SLIPPAGE_SOURCE


def test_liquidity_cost_fraction_round_trip_reads_estimated_round_trip_cost():
    liquidity_payload = {"estimated_round_trip_cost": 0.002, "estimated_slippage": 0.0005}

    assert liquidity_cost_fraction(liquidity_payload, "round_trip") == 0.002


def test_liquidity_cost_fraction_impact_only_reads_estimated_slippage():
    liquidity_payload = {"estimated_round_trip_cost": 0.002, "estimated_slippage": 0.0005}

    assert liquidity_cost_fraction(liquidity_payload, "impact_only") == 0.0005


def test_liquidity_cost_fraction_unknown_source_falls_back_to_round_trip():
    liquidity_payload = {"estimated_round_trip_cost": 0.002, "estimated_slippage": 0.0005}

    assert liquidity_cost_fraction(liquidity_payload, "banana") == 0.002


def test_liquidity_cost_fraction_missing_field_is_zero():
    assert liquidity_cost_fraction({}, "round_trip") == 0.0
    assert liquidity_cost_fraction({}, "impact_only") == 0.0


def test_resolve_limit_price_buy_sits_below_reference():
    result = resolve_limit_price(100.0, spread_fraction=0.01, is_buy=True)

    assert result < 100.0


def test_resolve_limit_price_sell_sits_above_reference():
    result = resolve_limit_price(100.0, spread_fraction=0.01, is_buy=False)

    assert result > 100.0


def test_resolve_limit_price_offset_is_half_spread_times_multiplier():
    # spread_fraction=0.02 -> half-spread = 0.01 -> offset = 100 * 0.01 * multiplier
    buy_default = resolve_limit_price(100.0, spread_fraction=0.02, is_buy=True, offset_multiplier=1.0)
    assert round(buy_default, 6) == round(100.0 - 1.0, 6)

    sell_default = resolve_limit_price(100.0, spread_fraction=0.02, is_buy=False, offset_multiplier=1.0)
    assert round(sell_default, 6) == round(100.0 + 1.0, 6)


def test_resolve_limit_price_offset_scales_linearly_with_offset_multiplier():
    buy_1x = resolve_limit_price(100.0, spread_fraction=0.02, is_buy=True, offset_multiplier=1.0)
    buy_2x = resolve_limit_price(100.0, spread_fraction=0.02, is_buy=True, offset_multiplier=2.0)

    assert round(100.0 - buy_2x, 6) == round((100.0 - buy_1x) * 2.0, 6)


def test_resolve_limit_price_zero_reference_price_returns_reference_unchanged():
    assert resolve_limit_price(0.0, spread_fraction=0.01, is_buy=True) == 0.0
    assert resolve_limit_price(0.0, spread_fraction=0.01, is_buy=False) == 0.0


def test_resolve_limit_price_zero_spread_fraction_returns_reference_unchanged():
    assert resolve_limit_price(100.0, spread_fraction=0.0, is_buy=True) == 100.0
    assert resolve_limit_price(100.0, spread_fraction=0.0, is_buy=False) == 100.0


def test_resolve_limit_price_negative_spread_fraction_treated_as_no_offset():
    assert resolve_limit_price(100.0, spread_fraction=-0.01, is_buy=True) == 100.0
    assert resolve_limit_price(100.0, spread_fraction=-0.01, is_buy=False) == 100.0


def test_resolve_limit_price_default_offset_multiplier_is_one():
    explicit = resolve_limit_price(100.0, spread_fraction=0.02, is_buy=True, offset_multiplier=1.0)
    implicit = resolve_limit_price(100.0, spread_fraction=0.02, is_buy=True)

    assert explicit == implicit


def test_classify_order_status_filled():
    assert classify_order_status("Filled") == "filled"


def test_classify_order_status_canceled_and_invalid():
    assert classify_order_status("Canceled") == "canceled"
    assert classify_order_status("Invalid") == "canceled"


def test_classify_order_status_pending_variants():
    for status_name in ("New", "Submitted", "PartiallyFilled", "UpdateSubmitted"):
        assert classify_order_status(status_name) == "pending"


def test_classify_order_status_unknown_string_returns_unknown_not_raises():
    assert classify_order_status("SomethingLeanMightActuallyCallIt") == "unknown"
    assert classify_order_status("") == "unknown"


# ---------------------------------------------------------------------------
# is_real_order_placement — audit-log hook classifier (development/Problems.md #42)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "execution_note",
    [
        "entered_long",
        "entered_short",
        "entered_long_futures",
        "entered_short_futures",
        "submitted_limit_long",
        "submitted_limit_short",
        "submitted_limit_long_futures",
        "submitted_limit_short_futures",
        "liquidated_on_sell",
        # V4.3.0 - allow adding to an existing position (development/
        # Changelog.md). All real order placements: equity/crypto/bond
        # scale-up, futures scale-up, options single-leg scale-up and
        # rotation, options spread scale-up and rotation.
        "scaled_long",
        "scaled_short",
        "submitted_limit_scaled_long",
        "submitted_limit_scaled_short",
        "scaled_long_futures",
        "scaled_short_futures",
        "submitted_limit_scaled_long_futures",
        "submitted_limit_scaled_short_futures",
        "scaled_option_call",
        "scaled_option_put",
        "submitted_limit_scaled_option_call",
        "submitted_limit_scaled_option_put",
        "rotated_option_call",
        "rotated_option_put",
        "submitted_limit_rotated_option_call",
        "submitted_limit_rotated_option_put",
        "scaled_option_multi_leg_bull_call_spread",
        "scaled_option_multi_leg_bear_put_spread",
        "rotated_option_multi_leg_bull_call_spread",
        "rotated_option_multi_leg_bear_put_spread",
        # V4.4 - architecturally-sound options (development/Problems.md):
        # single-leg/spread scale-DOWN (a negative delta reduces an
        # already-open position, no longer a no-op), the multi-position
        # book's "additional position opened under the cap" case, and the
        # new spread combo-limit submission notes.
        "reduced_option_call",
        "reduced_option_put",
        "submitted_limit_reduced_option_call",
        "submitted_limit_reduced_option_put",
        "reduced_option_multi_leg_bull_call_spread",
        "reduced_option_multi_leg_bear_put_spread",
        "opened_additional_option_call",
        "opened_additional_option_put",
        "submitted_limit_opened_additional_option_call",
        "submitted_limit_opened_additional_option_put",
        "opened_additional_option_multi_leg_bull_call_spread",
        "opened_additional_option_multi_leg_bear_put_spread",
        "submitted_limit_option_multi_leg_bull_call_spread",
        "submitted_limit_option_multi_leg_bear_put_spread",
        "submitted_limit_scaled_option_multi_leg_bull_call_spread",
        "submitted_limit_scaled_option_multi_leg_bear_put_spread",
        "submitted_limit_reduced_option_multi_leg_bull_call_spread",
        "submitted_limit_reduced_option_multi_leg_bear_put_spread",
        "submitted_limit_rotated_option_multi_leg_bull_call_spread",
        "submitted_limit_rotated_option_multi_leg_bear_put_spread",
        "submitted_limit_opened_additional_option_multi_leg_bull_call_spread",
        "submitted_limit_opened_additional_option_multi_leg_bear_put_spread",
    ],
)
def test_is_real_order_placement_true_for_real_outcomes(execution_note):
    assert is_real_order_placement(execution_note, orders_allowed=True) is True


@pytest.mark.parametrize(
    "execution_note",
    [
        "kept_long",
        "kept_short",
        "already_flat",
        "cooldown_active",
        "no_action",
        "max_active_positions_reached",
        "futures_zero_contract_count",
        "options_no_usable_contract",
        "options_multi_leg_no_usable_legs",
        "equity_exposure_cap_reached",
        "short_exposure_cap_reached",
        # V4.3.0 - allow adding to an existing position (development/
        # Changelog.md). All safe no-ops: scaling disabled while already
        # invested same-direction, delta rounds to zero, or a drifted
        # contract/spread held with rotate_on_drift off.
        "kept_long_futures",
        "kept_short_futures",
        "futures_zero_delta_kept",
        "options_kept",
        "options_contract_drifted_kept",
        "options_multi_leg_kept",
        "options_multi_leg_mismatch_kept",
        # V4.4 - architecturally-sound options (development/Problems.md):
        # "options_zero_or_negative_delta_kept"/"options_spread_shrink_
        # unsupported" retired - a negative delta is now a REAL reduce
        # order (see the real-outcomes list above), never a no-op.
        "options_zero_delta_kept",
        "options_at_position_cap_kept",
        "options_held_contract_not_in_chain_kept",
        # V4.5 (full OptionStrategies coverage, §9.1) - "spread" retired as
        # a record kind (folded into "multi_leg"); the at-cap re-price
        # search now scopes to same-strategy_name records only, degrading
        # to this distinct no-op when nothing comparable is held.
        "options_no_comparable_position_to_reprice_kept",
    ],
)
def test_is_real_order_placement_false_for_no_op_outcomes(execution_note):
    assert is_real_order_placement(execution_note, orders_allowed=True) is False


def test_is_real_order_placement_false_when_simulated():
    assert is_real_order_placement("entered_long", orders_allowed=False) is False
    assert is_real_order_placement("simulated_entered_long:paper", orders_allowed=True) is False


def test_is_real_order_placement_false_when_orders_not_allowed_even_for_real_looking_note():
    # orders_allowed=False means observation/paper/live-without-permission -
    # a real-shaped execution_note under that mode is a Lean-bug signal, not
    # something to ever audit as a genuine placement.
    assert is_real_order_placement("liquidated_on_sell", orders_allowed=False) is False
