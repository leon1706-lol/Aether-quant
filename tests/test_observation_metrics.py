"""Tests for experience.observation_metrics — V2-15.

Conventions: no test classes, module-level helpers, plain list[dict] fixtures
(same shape whether sourced from Redis/in-memory logs or Postgres JSONB rows).
"""

from experience.observation_metrics import (
    action_distribution,
    compute_observation_summary,
    count_observations,
    rejected_by_reason,
    signal_distribution,
    simulated_max_drawdown,
    simulated_sharpe,
    simulated_win_loss,
)


def _sample_event(**overrides) -> dict:
    defaults = {
        "event_id": "00000000-0000-0000-0000-000000000001",
        "mode": "observation",
        "symbol": "AAPL R735QTJ8XC9X",
        "ticker": "AAPL",
        "signal": "buy",
        "action": "trade",
        "execution_note": "entered_long",
        "probability_up": 0.61,
        "confidence": 0.22,
        "target_weight": 0.12,
        "market_analysis": {"action": "trade", "reasons": ["trading_eligible_directional_signal_above_confidence_threshold"]},
        "portfolio": {"total_value": 100_000.0, "cash": 50_000.0, "current_drawdown": 0.0, "simulated": True},
    }
    defaults.update(overrides)
    return defaults


def test_count_observations_counts_all_events():
    events = [_sample_event(), _sample_event(), _sample_event()]

    assert count_observations(events) == 3


def test_count_observations_handles_empty_list():
    assert count_observations([]) == 0


def test_signal_distribution_counts_buy_sell_hold():
    events = [
        _sample_event(signal="buy"),
        _sample_event(signal="buy"),
        _sample_event(signal="sell"),
        _sample_event(signal="hold"),
        _sample_event(signal="unknown_value"),
    ]

    assert signal_distribution(events) == {"buy": 2, "sell": 1, "hold": 1}


def test_action_distribution_counts_all_five_actions():
    events = [
        _sample_event(action="trade"),
        _sample_event(action="simulate"),
        _sample_event(action="observe"),
        _sample_event(action="reduce_risk"),
        _sample_event(action="retrain_candidate"),
        _sample_event(action="trade"),
    ]

    assert action_distribution(events) == {
        "observe": 1,
        "simulate": 1,
        "trade": 2,
        "reduce_risk": 1,
        "retrain_candidate": 1,
    }


def test_rejected_by_reason_tallies_market_analysis_reasons():
    events = [
        _sample_event(
            action="simulate",
            market_analysis={"action": "simulate", "reasons": ["liquidity_blocked_insufficient_volume_simulate_instead"]},
        ),
        _sample_event(
            action="simulate",
            market_analysis={"action": "simulate", "reasons": ["confidence_below_trade_threshold_simulate_instead"]},
        ),
        _sample_event(
            action="simulate",
            market_analysis={"action": "simulate", "reasons": ["observation_only_asset_directional_signal_simulate_instead"]},
        ),
        _sample_event(action="trade"),  # not rejected, must be excluded
    ]

    reasons = rejected_by_reason(events)

    assert reasons == {
        "liquidity_blocked_insufficient_volume_simulate_instead": 1,
        "confidence_below_trade_threshold_simulate_instead": 1,
        "observation_only_asset_directional_signal_simulate_instead": 1,
    }


def test_simulated_win_loss_counts_realized_pnl_events():
    events = [
        _sample_event(portfolio={"total_value": 100_000.0, "cash": 50_000.0, "current_drawdown": 0.0, "simulated": True, "last_realized_pnl": 50.0}),
        _sample_event(portfolio={"total_value": 100_050.0, "cash": 50_050.0, "current_drawdown": 0.0, "simulated": True, "last_realized_pnl": -20.0}),
        _sample_event(portfolio={"total_value": 100_030.0, "cash": 50_030.0, "current_drawdown": 0.0, "simulated": True, "last_realized_pnl": None}),
    ]

    result = simulated_win_loss(events)

    assert result == {"wins": 1, "losses": 1, "win_rate": 0.5}


def test_simulated_win_loss_returns_zero_rate_when_no_realized_pnl():
    events = [_sample_event()]

    assert simulated_win_loss(events) == {"wins": 0, "losses": 0, "win_rate": 0.0}


def test_simulated_sharpe_returns_zero_for_fewer_than_two_points():
    events = [_sample_event(portfolio={"total_value": 100_000.0, "simulated": True})]

    assert simulated_sharpe(events) == 0.0


def test_simulated_sharpe_returns_zero_for_empty_list():
    assert simulated_sharpe([]) == 0.0


def test_simulated_sharpe_computes_expected_value_for_known_series():
    equities = [100_000.0, 101_000.0, 100_500.0, 102_000.0]
    events = [_sample_event(portfolio={"total_value": value, "simulated": True}) for value in equities]

    returns = []
    for previous, current in zip(equities, equities[1:]):
        returns.append((current - previous) / previous)
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    expected_sharpe = (mean / variance**0.5) * (252**0.5)

    assert round(simulated_sharpe(events), 6) == round(expected_sharpe, 6)


def test_simulated_max_drawdown_finds_trough_after_peak():
    equities = [100_000.0, 110_000.0, 88_000.0, 95_000.0]
    events = [_sample_event(portfolio={"total_value": value, "simulated": True}) for value in equities]

    assert round(simulated_max_drawdown(events), 6) == round(88_000.0 / 110_000.0 - 1.0, 6)


def test_simulated_max_drawdown_returns_zero_for_empty_list():
    assert simulated_max_drawdown([]) == 0.0


def test_compute_observation_summary_returns_all_keys():
    events = [_sample_event()]

    summary = compute_observation_summary(events)

    for key in (
        "count_observations",
        "signal_distribution",
        "action_distribution",
        "rejected_by_reason",
        "simulated_win_loss",
        "simulated_sharpe",
        "simulated_max_drawdown",
    ):
        assert key in summary


def test_functions_tolerate_missing_keys_on_older_events():
    legacy_event = {"signal": "hold"}  # no action, market_analysis, or portfolio at all

    summary = compute_observation_summary([legacy_event])

    assert summary["count_observations"] == 1
    assert summary["signal_distribution"]["hold"] == 1
