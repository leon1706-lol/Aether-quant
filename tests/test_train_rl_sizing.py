"""Tests for train_rl_sizing.py's pure functions (development/Problems.md
#71, Phase 4.12, Component E). Mirrors tests/test_train_topology.py's own
documented convention: only the pure functions are exercised here -
main()'s multitask-model replay and file I/O are left untested at the unit
level (same reasoning: they need a real exported model + real datasets, not
just synthetic fixtures)."""

import numpy as np

from train_rl_sizing import (
    action_distribution,
    compute_action_reward,
    evaluate_policy_expected_reward,
    fit_policy,
    standardize_states,
)


# ---------------------------------------------------------------------------
# compute_action_reward
# ---------------------------------------------------------------------------


def test_compute_action_reward_matches_hand_computation():
    # action=1.0, base_weight=0.1, direction=1.0, forward_return=0.02,
    # prior_action_weight=0.0 (fresh position), no costs.
    reward = compute_action_reward(1.0, 0.1, 1.0, 0.02, 0.0, turnover_cost_bps=0.0, commission_bps=0.0)
    assert reward == 1.0 * 0.1 * 1.0 * 0.02


def test_compute_action_reward_negative_direction_flips_sign():
    reward = compute_action_reward(1.0, 0.1, -1.0, 0.02, 0.0, turnover_cost_bps=0.0, commission_bps=0.0)
    assert reward == -0.1 * 0.02


def test_compute_action_reward_smaller_action_scales_gross_return_down():
    full = compute_action_reward(1.0, 0.1, 1.0, 0.02, 0.0, turnover_cost_bps=0.0, commission_bps=0.0)
    half = compute_action_reward(0.5, 0.1, 1.0, 0.02, 0.0, turnover_cost_bps=0.0, commission_bps=0.0)
    assert half == full / 2.0


def test_compute_action_reward_includes_turnover_cost():
    # Position changes from prior_action_weight=0.0 to sized_weight=0.1 -
    # a real turnover cost must be subtracted.
    no_cost = compute_action_reward(1.0, 0.1, 1.0, 0.02, 0.0, turnover_cost_bps=0.0, commission_bps=0.0)
    with_cost = compute_action_reward(1.0, 0.1, 1.0, 0.02, 0.0, turnover_cost_bps=50.0, commission_bps=0.0)
    assert with_cost < no_cost
    expected_turnover_cost = (50.0 / 1e4) * abs(0.1 - 0.0)
    assert with_cost == no_cost - expected_turnover_cost


def test_compute_action_reward_no_turnover_cost_when_size_unchanged():
    # prior_action_weight already equals this action's sized_weight - no
    # position change, so turnover cost and commission must both be zero.
    reward = compute_action_reward(
        1.0, 0.1, 1.0, 0.02, prior_action_weight=0.1, turnover_cost_bps=50.0, commission_bps=5.0
    )
    assert reward == 1.0 * 0.1 * 1.0 * 0.02


def test_compute_action_reward_commission_only_charged_on_size_change():
    changed = compute_action_reward(1.0, 0.1, 1.0, 0.02, prior_action_weight=0.05, turnover_cost_bps=0.0, commission_bps=5.0)
    unchanged = compute_action_reward(1.0, 0.1, 1.0, 0.02, prior_action_weight=0.1, turnover_cost_bps=0.0, commission_bps=5.0)
    assert changed == unchanged - (5.0 / 1e4)


# ---------------------------------------------------------------------------
# standardize_states
# ---------------------------------------------------------------------------


def test_standardize_states_zero_mean_unit_variance():
    states = np.array([[1.0, 10.0], [2.0, 20.0], [3.0, 30.0]])
    standardized, mean, scale = standardize_states(states)
    assert np.allclose(standardized.mean(axis=0), 0.0, atol=1e-9)
    assert np.allclose(mean, [2.0, 20.0])
    assert scale[0] > 0.0 and scale[1] > 0.0


def test_standardize_states_constant_column_does_not_divide_by_zero():
    states = np.array([[5.0, 1.0], [5.0, 2.0], [5.0, 3.0]])
    standardized, mean, scale = standardize_states(states)
    assert np.all(np.isfinite(standardized))
    assert scale[0] == 1.0  # fallback for the zero-variance column
    assert np.allclose(standardized[:, 0], 0.0)


# ---------------------------------------------------------------------------
# fit_policy - the load-bearing tests: prove the optimizer actually works.
# ---------------------------------------------------------------------------


def test_policy_gradient_recovers_known_optimal_action_on_synthetic_data():
    # Two states (a one-hot indicator), 2 actions. In state 0, action 0 is
    # strictly better; in state 1, action 1 is strictly better - a policy
    # that actually learns should pick differently per state.
    rng = np.random.default_rng(0)
    n_per_state = 500
    states = np.vstack([
        np.tile([1.0, 0.0], (n_per_state, 1)),
        np.tile([0.0, 1.0], (n_per_state, 1)),
    ])
    rewards = np.vstack([
        np.tile([1.0, -1.0], (n_per_state, 1)),  # state 0: action 0 wins
        np.tile([-1.0, 1.0], (n_per_state, 1)),  # state 1: action 1 wins
    ])
    noise = rng.normal(0.0, 0.01, size=rewards.shape)
    rewards = rewards + noise

    standardized, mean, scale = standardize_states(states)
    fit_result = fit_policy(standardized, rewards, learning_rate=0.5, epochs=300, l2=0.0, entropy_bonus=0.0)
    weights = np.asarray(fit_result["weights"])
    bias = np.asarray(fit_result["bias"])

    # Re-standardize a fresh point the same way the training data was.
    probe_0 = (np.asarray([1.0, 0.0]) - mean) / scale
    probe_1 = (np.asarray([0.0, 1.0]) - mean) / scale
    assert (probe_0 @ weights.T + bias).argmax() == 0
    assert (probe_1 @ weights.T + bias).argmax() == 1

    # Expected reward must have improved over training (learned something).
    assert fit_result["history"][-1] > fit_result["history"][0]


def test_policy_gradient_zero_signal_data_converges_to_smallest_action():
    # No state dependence at all - action 0 (smallest multiplier, e.g.
    # 0.6) is uniformly best everywhere. A correctly-optimizing policy
    # should converge toward always picking it, not a degenerate wrong
    # answer or an unstable oscillation.
    rng = np.random.default_rng(1)
    n_rows = 1000
    states = rng.normal(0.0, 1.0, size=(n_rows, 3))
    # 3 actions: reward decreases as action increases (smaller size wins).
    base_rewards = np.tile([0.05, -0.05, -0.2], (n_rows, 1))
    rewards = base_rewards + rng.normal(0.0, 0.01, size=base_rewards.shape)

    standardized, _, _ = standardize_states(states)
    fit_result = fit_policy(standardized, rewards, learning_rate=0.3, epochs=300, l2=0.001, entropy_bonus=0.0)
    weights = np.asarray(fit_result["weights"])
    bias = np.asarray(fit_result["bias"])

    distribution = action_distribution(standardized, weights, bias, n_actions=3)
    # Overwhelming majority should land on action 0 (index 0), not the
    # worst action (index 2).
    assert distribution[0] > distribution[2]
    assert distribution[0] / n_rows > 0.8


def test_evaluate_policy_expected_reward_uses_argmax_not_softmax_average():
    # A policy with weights=0/bias favoring action 1 should be evaluated
    # by picking action 1 deterministically for every row, not blending.
    states = np.zeros((4, 2))
    rewards = np.array([[0.0, 1.0], [0.0, 1.0], [0.0, 1.0], [0.0, 1.0]])
    weights = np.zeros((2, 2))
    bias = np.array([0.0, 1.0])  # action 1 always wins the argmax

    result = evaluate_policy_expected_reward(states, rewards, weights, bias)

    assert result == 1.0


def test_action_distribution_sums_to_row_count():
    states = np.array([[1.0], [-1.0], [0.5]])
    weights = np.array([[1.0], [-1.0]])
    bias = np.array([0.0, 0.0])

    distribution = action_distribution(states, weights, bias, n_actions=2)

    assert sum(distribution) == len(states)
