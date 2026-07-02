from execution import resolve_order_permission, resolve_runtime_mode, simulate_fill


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
