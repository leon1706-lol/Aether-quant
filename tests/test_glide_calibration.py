"""evaluation/glide_calibration.py: fixed seeds reproduce, a known case picks the right policy, and no qualifying policy falls back."""

from __future__ import annotations

import numpy as np

from evaluation.glide_calibration import (
    FALLBACK_POLICY,
    default_configs,
    default_policies,
    evaluate_policies,
    glide2_policies,
    oracle_daily,
    pick_glide2,
    pick_policy,
    run_policy,
    simulate_generations,
)

CONFIG = {"sharpe": 1.0, "half_life_years": 2.0, "correlation": 0.3, "zero_alpha_probability": 0.5}


def test_the_grid_is_the_rules():
    assert len(default_configs()) == 2 * 3 * 3 * 2
    names = {policy["name"] for policy in default_policies()}
    assert {"instant", "equal", "fixed_126", "fixed_252", "fixed_504"} <= names


def test_a_world_is_fixed_by_its_seed():
    first, second = simulate_generations(CONFIG, 3), simulate_generations(CONFIG, 3)
    np.testing.assert_array_equal(first["returns"], second["returns"])
    assert not np.array_equal(first["returns"], simulate_generations(CONFIG, 4)["returns"])


def test_a_generation_has_no_alpha_before_it_exists_and_its_alpha_halves():
    world = simulate_generations({**CONFIG, "zero_alpha_probability": 0.0}, 1)
    assert world["true_sharpe"][0, 0] == 1.0
    assert abs(world["true_sharpe"][504, 0] - 0.5) < 1e-9
    assert world["true_sharpe"][0, 1] == 0.0, "the next generation has no alpha before it exists"
    assert world["true_sharpe"][252, 1] == 1.0


def test_a_zero_alpha_generation_claims_the_same_sharpe_as_a_real_one():
    world = simulate_generations({**CONFIG, "zero_alpha_probability": 1.0}, 1)
    assert world["claimed_sharpe"] == 1.0 and not world["has_alpha"][1:].any()


def test_the_oracle_beats_every_policy_on_average():
    worlds = [simulate_generations(CONFIG, seed) for seed in range(6)]
    oracle = np.mean([oracle_daily(world).mean() for world in worlds])
    for policy in default_policies():
        assert oracle >= np.mean([run_policy(world, policy)["daily"].mean() for world in worlds])


def test_instant_switching_chases_zero_alpha_generations_more_than_a_glide():
    worlds = [simulate_generations({**CONFIG, "zero_alpha_probability": 0.8}, seed) for seed in range(6)]
    instant = np.mean([run_policy(world, {"name": "i", "kind": "instant"})["zero_alpha_majority_share"] for world in worlds])
    glide = np.mean([run_policy(world, {"name": "g", "kind": "glide", "glide_sessions": 504})["zero_alpha_majority_share"] for world in worlds])
    assert instant > glide


def test_a_policy_moves_capital_to_a_new_generation():
    world = simulate_generations({**CONFIG, "zero_alpha_probability": 0.0}, 2)
    assert run_policy(world, {"name": "g", "kind": "glide", "glide_sessions": 126})["daily"].std() > 0.0


def test_evaluation_is_reproducible():
    one = evaluate_policies([CONFIG], [{"name": "fixed_252", "kind": "glide", "glide_sessions": 252}], paths=4, seed=2, years=4)
    two = evaluate_policies([CONFIG], [{"name": "fixed_252", "kind": "glide", "glide_sessions": 252}], paths=4, seed=2, years=4)
    assert one == two


def test_picking_by_rule():
    results = {
        "a": {"median_regret": 0.2, "zero_alpha_majority_share": 0.5, "parameters": 0},
        "b": {"median_regret": 0.3, "zero_alpha_majority_share": 0.1, "parameters": 1},
        "c": {"median_regret": 0.301, "zero_alpha_majority_share": 0.1, "parameters": 2},
    }
    assert pick_policy(results)["policy"] == "b", "the lowest regret fails the zero-alpha limit, and a tie goes to fewer parameters"


DYNAMIC = {"name": "dynamic_x", "kind": "dynamic", "half_life_sessions": 63, "prior_sessions": 252.0, "score_floor": 0.0, "blend_every": 21, "max_generations": 4}


def test_the_dynamic_mode_runs_and_holds_several_generations_where_the_ladder_holds_fewer():
    worlds = [simulate_generations({**CONFIG, "zero_alpha_probability": 0.0}, seed) for seed in range(4)]
    dynamic = np.mean([run_policy(world, DYNAMIC)["mean_holders"] for world in worlds])
    ladder = np.mean([run_policy(world, {"name": "g", "kind": "glide", "glide_sessions": 252})["mean_holders"] for world in worlds])
    assert dynamic > ladder and dynamic > 1.5


def test_the_second_grid_is_the_rules():
    policies = glide2_policies()
    assert sum(policy["kind"] == "dynamic" for policy in policies) == 2 * 3 * 2 * 2
    assert {"fixed_252", "equal"} <= {policy["name"] for policy in policies}
    assert all(policy["max_generations"] == 4 for policy in policies if policy["kind"] == "dynamic")


def test_workers_do_not_change_the_answer():
    policies = [{"name": "fixed_252", "kind": "glide", "glide_sessions": 252}, DYNAMIC]
    one = evaluate_policies([CONFIG, {**CONFIG, "sharpe": 0.5}], policies, paths=2, seed=2, years=3, workers=1)
    two = evaluate_policies([CONFIG, {**CONFIG, "sharpe": 0.5}], policies, paths=2, seed=2, years=3, workers=2)
    assert one == two


def _row(regret, zero, turnover=1.0):
    return {"median_regret": regret, "zero_alpha_majority_share": zero, "turnover_per_year": turnover}


def test_dynamic_replaces_the_ladder_only_if_no_worse_on_both_counts():
    base = _row(0.15, 0.50)
    assert pick_glide2({"fixed_252": base, "dynamic_a": _row(0.14, 0.45)})["policy"] == "dynamic_a"
    assert pick_glide2({"fixed_252": base, "dynamic_a": _row(0.155, 0.45)})["policy"] == "dynamic_a", "within the tie"
    worse = pick_glide2({"fixed_252": base, "dynamic_a": _row(0.30, 0.45)})
    assert worse["policy"] == "fixed_252" and worse["adopted"] is False and worse["best_dynamic"] == "dynamic_a"
    more_zero = pick_glide2({"fixed_252": base, "dynamic_a": _row(0.01, 0.51)})
    assert more_zero["policy"] == "fixed_252" and more_zero["eligible"] == [], "less regret can't buy more time on a generation with no alpha"


def test_a_tie_among_dynamic_policies_goes_to_less_turnover():
    results = {"fixed_252": _row(0.15, 0.50), "dynamic_a": _row(0.100, 0.40, turnover=5.0), "dynamic_b": _row(0.103, 0.40, turnover=1.0)}
    assert pick_glide2(results)["policy"] == "dynamic_b"


def test_the_report_says_whether_r_glide1s_limit_is_met():
    assert pick_glide2({"fixed_252": _row(0.15, 0.50), "dynamic_a": _row(0.14, 0.19)})["meets_r_glide1_limit"] == ["dynamic_a"]


def test_nothing_qualifying_falls_back_to_fixed_252():
    results = {"a": {"median_regret": 0.2, "zero_alpha_majority_share": 0.9, "parameters": 0}}
    assert pick_policy(results)["policy"] == FALLBACK_POLICY
