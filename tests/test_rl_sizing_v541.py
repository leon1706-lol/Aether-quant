"""V5.4.1 - tests for the RL sizing reward asymmetry fix and regime
conditioning. The root cause of three consecutive honest negatives was a
symmetric reward function that made "do nothing" the optimal strategy."""

import pytest

from train_rl_sizing import compute_action_reward


def test_symmetric_baseline_unchanged_at_default_weight():
    """With asymmetric_penalty_weight=1.0 (default), behavior must be
    identical to the pre-V5.4.1 formula for backwards compatibility."""
    r = compute_action_reward(
        action=0.75, base_weight=0.10, direction=1.0, forward_return=0.02,
        prior_action_weight=0.0, turnover_cost_bps=5.0, commission_bps=1.0,
    )
    expected_gross = 0.75 * 0.10 * 1.0 * 0.02
    expected_turnover = (5.0 / 1e4) * (0.075)
    assert r == pytest.approx(expected_gross - expected_turnover - (1.0 / 1e4), abs=1e-10)


def test_asymmetric_penalty_penalizes_undersizing_winners():
    """A winning trade that gets UNDERSIZED should receive a WORSE reward
    when asymmetric_penalty_weight > 1 than when it equals 1."""
    kwargs = dict(
        action=0.5, base_weight=0.10, direction=1.0, forward_return=0.03,
        prior_action_weight=0.0, turnover_cost_bps=5.0, commission_bps=1.0,
    )
    r_default = compute_action_reward(**kwargs, asymmetric_penalty_weight=1.0)
    r_penalized = compute_action_reward(**kwargs, asymmetric_penalty_weight=2.0)
    assert r_penalized < r_default, "undersizing a winner must be penalized more"


def test_asymmetric_penalty_does_not_fire_for_full_size():
    """When action == 1.0 (full base size), no opportunity cost exists
    regardless of the penalty weight."""
    kwargs = dict(
        action=1.0, base_weight=0.10, direction=1.0, forward_return=0.03,
        prior_action_weight=0.0, turnover_cost_bps=5.0, commission_bps=1.0,
    )
    r_default = compute_action_reward(**kwargs, asymmetric_penalty_weight=1.0)
    r_penalized = compute_action_reward(**kwargs, asymmetric_penalty_weight=3.0)
    assert r_default == pytest.approx(r_penalized)


def test_asymmetric_penalty_fires_for_oversizing_losers():
    """A losing trade that gets OVERSIZED should also be penalized more
    with a higher weight - taking on larger losers is worse too."""
    kwargs = dict(
        action=1.5, base_weight=0.10, direction=-1.0, forward_return=0.02,
        prior_action_weight=0.0, turnover_cost_bps=5.0, commission_bps=1.0,
    )
    # direction=-1 and forward_return>0 means the trade LOSES money.
    r_default = compute_action_reward(**kwargs, asymmetric_penalty_weight=1.0)
    r_penalized = compute_action_reward(**kwargs, asymmetric_penalty_weight=2.0)
    assert r_penalized <= r_default


def test_optimal_action_shifts_toward_full_size_with_penalty():
    """The core V5.4.1 hypothesis: with asymmetric penalty > 1, the optimal
    action for a winning trade should move TOWARD full size (away from
    undersizing), fixing the 'do nothing' convergence problem."""
    base_weight, direction, fwd_ret = 0.10, 1.0, 0.03

    def reward_for(action, weight):
        return compute_action_reward(
            action, base_weight, direction, fwd_ret,
            prior_action_weight=0.0, turnover_cost_bps=5.0, commission_bps=1.0,
            asymmetric_penalty_weight=weight,
        )

    actions = [0.25, 0.50, 0.75, 1.00]
    best_default = max(actions, key=lambda a: reward_for(a, 1.0))
    best_penalized = max(actions, key=lambda a: reward_for(a, 2.0))
    assert best_penalized >= best_default, (
        "asymmetric penalty should push optimal action toward full size"
    )


def test_regime_keys_in_state_vector():
    from risk.rl_sizing import RL_SIZING_STATE_KEYS
    for key in ("regime_trend_bullish", "regime_trend_bearish", "regime_trend_sideways"):
        assert key in RL_SIZING_STATE_KEYS, f"{key} missing from state keys"
