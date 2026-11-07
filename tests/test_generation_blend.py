"""portfolio/generation_blend.py: the owner's 70/30 -> 60/40 -> 0/100, and every way it must fail safe."""

from __future__ import annotations

import ast
import math
import random
from pathlib import Path

import numpy as np
import pytest

from portfolio.generation_blend import (
    GlidePolicy,
    blend_due,
    blend_generation_rows,
    dynamic_generation_shares,
    dynamic_targets,
    ew_sharpe,
    ew_update,
    resolve_glide_policy,
    shrunk_sharpe,
    update_generation_shares,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = GlidePolicy()
STAGES = {"old": "active", "new": "ramping"}
HEALTHY = {"old": "healthy", "new": "healthy"}
NO_CAP = {"old": 1.0, "new": 1.0}


def _glide(shares: dict[str, float], steps: int, *, stages=STAGES, states=HEALTHY, caps=NO_CAP, policy=POLICY) -> list[dict[str, float]]:
    path = [dict(shares)]
    for _ in range(steps):
        path.append(update_generation_shares(path[-1], stages, states, caps, policy))
    return path


def test_a_new_generation_enters_at_its_entry_share():
    out = update_generation_shares({"old": 1.0, "new": 0.0}, STAGES, HEALTHY, NO_CAP, POLICY)
    assert out == pytest.approx({"old": 0.70, "new": 0.30})


def test_the_owners_ladder():
    path = _glide({"old": 0.70, "new": 0.30}, 252)
    per_session = 0.70 / 252.0
    assert path[36]["old"] == pytest.approx(0.70 - 36 * per_session)
    at_sixty_forty = round(0.10 / per_session)
    assert path[at_sixty_forty]["old"] == pytest.approx(0.60, abs=1e-9)
    assert path[at_sixty_forty]["new"] == pytest.approx(0.40, abs=1e-9)
    assert path[-1] == pytest.approx({"old": 0.0, "new": 1.0})


def test_the_ladder_never_moves_capital_backward():
    path = _glide({"old": 0.70, "new": 0.30}, 300)
    assert all(later["new"] >= earlier["new"] - 1e-12 for earlier, later in zip(path, path[1:]))
    assert all(later["old"] <= earlier["old"] + 1e-12 for earlier, later in zip(path, path[1:]))


def test_a_generation_below_its_retire_share_is_gone_and_its_capital_passes_on():
    path = _glide({"old": 0.70, "new": 0.30}, 300)
    assert not any(0.0 < row["old"] < POLICY.retire_share for row in path[1:])
    assert path[-1]["new"] == pytest.approx(1.0)


def test_a_tier_two_cap_holds_and_the_incumbent_keeps_the_rest():
    caps = {"old": 1.0, "new": 0.30}
    path = _glide({"old": 1.0, "new": 0.0}, 100, caps=caps)
    assert path[-1] == pytest.approx({"old": 0.70, "new": 0.30})


def test_a_capped_generation_with_a_dead_incumbent_leaves_the_rest_in_tbills():
    caps = {"old": 1.0, "new": 0.30}
    out = update_generation_shares({"old": 0.70, "new": 0.30}, STAGES, {"old": "dead", "new": "healthy"}, caps, POLICY)
    assert out == pytest.approx({"old": 0.0, "new": 0.30})
    assert sum(out.values()) == pytest.approx(0.30), "the rest is in T-bills, not forced into an unproved generation"


@pytest.mark.parametrize("state", ["dead", "tripped"])
def test_taking_risk_off_is_not_rate_capped(state):
    states = {"old": state, "new": "healthy"}
    out = update_generation_shares({"old": 0.70, "new": 0.30}, STAGES, states, NO_CAP, POLICY)
    assert out["old"] == 0.0


@pytest.mark.parametrize("state", ["dead", "tripped"])
def test_a_ramping_generation_that_trips_drops_at_once_and_stops_gaining(state):
    states = {"old": "healthy", "new": state}
    out = update_generation_shares({"old": 0.60, "new": 0.40}, STAGES, states, NO_CAP, POLICY)
    assert out == pytest.approx({"old": 0.60, "new": 0.0})


@pytest.mark.parametrize("stage", ["retired", "rejected", "shadow", "frozen", "candidate"])
def test_a_generation_out_of_a_holding_stage_holds_nothing(stage):
    out = update_generation_shares({"old": 0.9, "x": 0.1}, {"old": "active", "x": stage}, {}, {}, POLICY)
    assert out["x"] == 0.0


@pytest.mark.parametrize("bad", [
    {"old": math.nan, "new": 0.3},
    {"old": math.inf, "new": 0.3},
    {"old": -0.1, "new": 0.3},
    {"old": 0.9, "new": 0.3},
    {"old": "broken", "new": 0.3},
])
def test_damaged_shares_hold_rather_than_guess(bad):
    out = update_generation_shares(bad, STAGES, HEALTHY, NO_CAP, POLICY)
    assert out["new"] == 0.3, "no step was taken"


def test_only_one_generation_gains_at_a_time():
    stages = {"a": "active", "b": "ramping", "c": "ramping"}
    out = update_generation_shares({"a": 0.5, "b": 0.5, "c": 0.0}, stages, {}, {}, POLICY)
    assert out["b"] > 0.5 and out["c"] == 0.0


def test_hold_on_watch_stops_the_ramp_only_when_asked():
    watch = {"old": "healthy", "new": "watch"}
    held = update_generation_shares({"old": 0.7, "new": 0.3}, STAGES, watch, NO_CAP, GlidePolicy(hold_on_watch=True))
    assert held == pytest.approx({"old": 0.7, "new": 0.3})
    assert update_generation_shares({"old": 0.7, "new": 0.3}, STAGES, watch, NO_CAP, POLICY)["new"] > 0.3


def test_accelerating_on_a_decaying_incumbent_only_when_asked():
    decaying = {"old": "decaying", "new": "healthy"}
    base = update_generation_shares({"old": 0.7, "new": 0.3}, STAGES, decaying, NO_CAP, POLICY)["new"]
    fast = update_generation_shares({"old": 0.7, "new": 0.3}, STAGES, decaying, NO_CAP, GlidePolicy(accelerate_on_decaying=2.0))["new"]
    assert fast - 0.3 == pytest.approx(2.0 * (base - 0.3))


def test_a_step_over_several_sessions_equals_those_sessions_one_at_a_time():
    many = _glide({"old": 0.7, "new": 0.3}, 10)[-1]
    once = update_generation_shares({"old": 0.7, "new": 0.3}, STAGES, HEALTHY, NO_CAP, POLICY, sessions=10)
    assert once == pytest.approx(many)


def test_shares_stay_in_bounds_whatever_happens():
    rng = random.Random(7)
    names = ["a", "b", "c"]
    for _ in range(2000):
        raw = [rng.random() for _ in names]
        total = sum(raw) / rng.uniform(0.2, 1.0)
        shares = {name: value / total for name, value in zip(names, raw)}
        stages = {name: rng.choice(["active", "ramping", "fading", "winding_down", "shadow", "retired"]) for name in names}
        states = {name: rng.choice(["healthy", "watch", "decaying", "dead", "tripped"]) for name in names}
        caps = {name: rng.choice([0.3, 1.0]) for name in names}
        out = update_generation_shares(shares, stages, states, caps, POLICY, sessions=rng.randint(0, 30))
        assert all(0.0 <= value <= 1.0 for value in out.values())
        assert sum(out.values()) <= 1.0 + 1e-9


THREE = {"oldest": "active", "middle": "active", "newest": "ramping"}
DYNAMIC = GlidePolicy(mode="dynamic", half_life_sessions=63, prior_sessions=252.0)


def _record(sharpe, sessions=500, prior=0.5):
    return {"ew_sharpe": sharpe, "sessions": sessions, "prior": prior}


def _glide_dynamic(shares, stages, evidence, steps, *, states=None, caps=None, policy=DYNAMIC):
    path = [dict(shares)]
    for _ in range(steps):
        path.append(dynamic_generation_shares(path[-1], stages, states or {}, evidence, caps or {}, policy))
    return path


def test_three_generations_hold_capital_at_once_while_the_old_ones_still_earn():
    evidence = {"oldest": _record(0.3), "middle": _record(0.6), "newest": _record(None, sessions=0)}
    final = _glide_dynamic({"oldest": 1.0, "middle": 0.0, "newest": 0.0}, THREE, evidence, 800)[-1]
    assert all(final[name] > POLICY.retire_share for name in THREE), final
    assert final["middle"] > final["oldest"], "a better record earns more"
    assert sum(final.values()) == pytest.approx(1.0)


def test_shares_follow_the_scores():
    evidence = {"a": _record(1.0, sessions=10_000), "b": _record(0.5, sessions=10_000)}
    final = _glide_dynamic({"a": 0.5, "b": 0.5}, {"a": "active", "b": "active"}, evidence, 1500)[-1]
    assert final["a"] / final["b"] == pytest.approx(2.0, rel=0.03)


def test_nothing_jumps_a_new_generation_included():
    evidence = {"old": _record(0.5), "new": _record(None, sessions=0, prior=0.5)}
    path = _glide_dynamic({"old": 1.0, "new": 0.0}, STAGES, evidence, 400)
    step = 1.0 - 0.5 ** (1.0 / 63.0)
    assert path[1]["new"] <= step + 1e-12 and path[1]["new"] > 0.0
    biggest = max(abs(later[name] - earlier[name]) for earlier, later in zip(path, path[1:]) for name in STAGES)
    assert biggest <= step + 1e-12, "the ladder's first step is 30% of the book"


def test_a_generation_that_stops_earning_fades_out_and_its_capital_passes_on():
    evidence = {"old": _record(-0.5), "new": _record(0.8)}
    path = _glide_dynamic({"old": 0.7, "new": 0.3}, {"old": "fading", "new": "ramping"}, evidence, 600)
    assert path[-1] == pytest.approx({"old": 0.0, "new": 1.0}, abs=0.01), "a share nears its target and never overshoots"
    falling = [row["old"] for row in path]
    assert all(later <= earlier + 1e-12 for earlier, later in zip(falling, falling[1:]))
    assert not any(0.0 < row["old"] < DYNAMIC.retire_share for row in path)


def test_winding_down_aims_for_nothing_whatever_its_score():
    final = _glide_dynamic({"a": 0.5, "b": 0.5}, {"a": "winding_down", "b": "active"}, {"a": _record(3.0), "b": _record(0.2)}, 600)[-1]
    assert final["a"] == 0.0


def test_no_earner_with_a_record_goes_to_tbills_gradually():
    path = _glide_dynamic({"a": 1.0}, {"a": "active"}, {"a": _record(-1.0, prior=0.0)}, 500)
    assert path[1]["a"] > 0.9 and path[-1]["a"] == 0.0


def test_with_nothing_known_yet_shares_hold():
    path = _glide_dynamic({"a": 1.0}, {"a": "active"}, {"a": _record(None, sessions=3, prior=0.0)}, 10)
    assert path[-1] == {"a": 1.0}, "an installed book with no record isn't sold for lack of one"


@pytest.mark.parametrize("state", ["dead", "tripped"])
def test_dynamic_takes_risk_off_at_once(state):
    out = dynamic_generation_shares({"a": 0.6, "b": 0.4}, {"a": "active", "b": "active"}, {"a": state}, {"a": _record(2.0), "b": _record(0.5)}, {}, DYNAMIC)
    assert out["a"] == 0.0 and out["b"] > 0.4 - 1e-9


def test_a_capped_generation_gives_its_excess_to_the_others_then_tbills():
    assert dynamic_targets({"a": 1.0, "b": 1.0}, {"a": 0.3}, DYNAMIC) == pytest.approx({"a": 0.3, "b": 0.7})
    assert dynamic_targets({"a": 1.0, "b": 0.1}, {"a": 0.3, "b": 0.3}, DYNAMIC) == pytest.approx({"a": 0.3, "b": 0.3}), "the rest stays in T-bills"


def test_only_the_best_few_hold_targets():
    scores = {f"g{index}": float(index + 1) for index in range(6)}
    targets = dynamic_targets(scores, {}, GlidePolicy(max_generations=4))
    assert sum(value > 0.0 for value in targets.values()) == 4 and targets["g0"] == 0.0 and targets["g1"] == 0.0


def test_a_floor_means_barely_profitable_earns_nothing():
    assert dynamic_targets({"a": 0.1, "b": 0.5}, {}, GlidePolicy(score_floor=0.2)) == pytest.approx({"a": 0.0, "b": 1.0})


@pytest.mark.parametrize("bad", [{"a": math.nan}, {"a": -0.1}, {"a": 0.9, "b": 0.9}])
def test_dynamic_damaged_shares_hold(bad):
    out = dynamic_generation_shares(bad, {"a": "active", "b": "active"}, {}, {"a": _record(0.5), "b": _record(0.5)}, {}, DYNAMIC)
    assert sum(1 for name in bad if out[name] != (bad[name] if bad[name] == bad[name] else 0.0)) == 0


def test_a_non_finite_score_earns_no_share_and_stops_nothing():
    out = dynamic_targets({"a": math.nan, "b": 0.5}, {}, DYNAMIC)
    assert out == pytest.approx({"a": 0.0, "b": 1.0})


def test_dynamic_shares_stay_in_bounds_whatever_happens():
    rng = random.Random(11)
    names = [f"g{index}" for index in range(5)]
    for _ in range(1500):
        raw = [rng.random() for _ in names]
        total = sum(raw) / rng.uniform(0.2, 1.0)
        shares = {name: value / total for name, value in zip(names, raw)}
        stages = {name: rng.choice(["active", "ramping", "fading", "winding_down", "shadow", "retired"]) for name in names}
        states = {name: rng.choice(["healthy", "watch", "decaying", "dead", "tripped"]) for name in names}
        evidence = {name: _record(rng.choice([None, rng.uniform(-2.0, 2.0)]), sessions=rng.randint(0, 800), prior=rng.uniform(-0.5, 1.0)) for name in names}
        caps = {name: rng.choice([0.3, 1.0]) for name in names}
        out = dynamic_generation_shares(shares, stages, states, evidence, caps, GlidePolicy(mode="dynamic", half_life_sessions=rng.randint(1, 200)), sessions=rng.randint(0, 30))
        assert all(0.0 <= value <= 1.0 for value in out.values()) and sum(out.values()) <= 1.0 + 1e-9


def test_the_record_matches_the_decay_detectors_figure():
    from evaluation.alpha_decay import _ew_sharpe

    returns = np.random.default_rng(4).normal(0.001, 0.01, 300)
    state = (0.0, 0.0, 0.0, 0)
    for value in returns:
        state = ew_update(state, float(value))
    assert ew_sharpe(state) == pytest.approx(_ew_sharpe(returns), rel=1e-9)
    assert ew_sharpe(ew_update((0.0, 0.0, 0.0, 0), 0.01)) is None, "too short to read"
    assert ew_update(state, math.nan) == state


def test_a_short_record_barely_moves_the_claim():
    assert shrunk_sharpe(3.0, 20, 0.5, 252.0) == pytest.approx((20 * 3.0 + 252 * 0.5) / 272.0)
    assert shrunk_sharpe(None, 500, 0.5, 252.0) == 0.5
    assert shrunk_sharpe(float("nan"), 500, 0.5, 252.0) == 0.5
    assert shrunk_sharpe(1.0, 100_000, 0.0, 252.0) == pytest.approx(1.0, abs=0.01)


def test_the_new_policy_fields_resolve_and_default_to_the_old_behaviour():
    assert GlidePolicy().mode == "ladder" and resolve_glide_policy({"mode": "nonsense"}).mode == "ladder"
    raw = {"mode": "dynamic", "half_life_sessions": 42, "prior_sessions": 126, "score_floor": 0.2, "max_generations": 3, "min_evidence_sessions": 20}
    assert resolve_glide_policy(raw) == GlidePolicy(mode="dynamic", half_life_sessions=42, prior_sessions=126.0, score_floor=0.2, max_generations=3, min_evidence_sessions=20)


def test_blending_at_share_one_returns_the_row_exactly():
    row = {"BTCUSD": 0.0157380712345, "ETHUSD": 0.0114948912345}
    assert blend_generation_rows({"g1": row, "g2": {"XRPUSD": 0.5}}, {"g1": 1.0, "g2": 0.0}) == row


def test_blending_nets_positions_and_drops_a_zero():
    book = blend_generation_rows({"old": {"A": 0.10, "B": -0.05}, "new": {"A": -0.10, "C": 0.20}}, {"old": 0.5, "new": 0.5})
    assert book == pytest.approx({"B": -0.025, "C": 0.10})


def test_a_blend_keeps_any_cap_every_generation_keeps():
    rng = random.Random(3)
    for _ in range(500):
        rows = {name: {ticker: rng.uniform(-0.03, 0.03) for ticker in "ABCDE"} for name in ("x", "y", "z")}
        a, b = sorted((rng.random(), rng.random()))
        shares = {"x": a, "y": b - a, "z": 1.0 - b}
        book = blend_generation_rows(rows, shares)
        assert all(abs(weight) <= 0.03 + 1e-12 for weight in book.values())


def test_a_damaged_weight_counts_as_flat():
    assert blend_generation_rows({"g": {"A": math.nan, "B": 0.1}}, {"g": 1.0}) == {"B": 0.1}


@pytest.mark.parametrize("decided,since,guard,due", [(True, 0, False, True), (False, 21, False, True), (False, 20, False, False), (False, 0, True, True)])
def test_a_row_is_written_only_when_due(decided, since, guard, due):
    assert blend_due(decided_today=decided, sessions_since_blend=since, guard_tripped=guard, policy=POLICY) is due


def test_policy_resolution_keeps_defaults_and_bounds():
    assert resolve_glide_policy(None) == GlidePolicy()
    bad = resolve_glide_policy({"glide_sessions": -5, "entry_share": 7.0, "blend_every": math.nan, "accelerate_on_decaying": 0.1})
    assert bad.glide_sessions == 1 and bad.entry_share == 1.0 and bad.blend_every == 21 and bad.accelerate_on_decaying == 1.0


def test_the_module_stays_stdlib_only():
    tree = ast.parse((ROOT / "portfolio" / "generation_blend.py").read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert imported <= {"__future__", "collections", "dataclasses", "math"}
