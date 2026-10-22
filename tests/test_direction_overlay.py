"""V6.4.0 (lead L2): the direction-probability overlay on the percentile ranks."""

from __future__ import annotations

import pytest

from portfolio.direction_overlay import apply_direction_overlay, calibrate_probability, resolve_direction_overlay

RANKS = {"A": 1.0, "B": 0.8, "C": 0.6, "D": 0.4, "E": 0.2}


def test_disabled_or_malformed_config_resolves_to_none():
    assert resolve_direction_overlay(None) is None
    assert resolve_direction_overlay({"enabled": False, "mode": "blend"}) is None
    assert resolve_direction_overlay({"enabled": True, "mode": "nonsense"}) is None
    assert resolve_direction_overlay({"enabled": True, "mode": "blend", "weight": 0.5})["weight"] == 0.5


def test_no_params_returns_the_ranks_unchanged():
    assert apply_direction_overlay(RANKS, {"A": 0.1}, None) == RANKS


def test_blend_lifts_a_name_the_head_likes_and_stays_a_percentile():
    params = resolve_direction_overlay({"enabled": True, "mode": "blend", "weight": 2.0})
    probabilities = {"A": 0.4, "B": 0.4, "C": 0.9, "D": 0.5, "E": 0.5}
    out = apply_direction_overlay(RANKS, probabilities, params)
    assert out["C"] > RANKS["C"]
    assert 0.0 < min(out.values()) and max(out.values()) == 1.0
    assert set(out) == set(RANKS)


def test_blend_with_no_probabilities_keeps_the_order():
    params = resolve_direction_overlay({"enabled": True, "mode": "blend", "weight": 1.0})
    out = apply_direction_overlay(RANKS, {}, params)
    assert sorted(out, key=out.get) == sorted(RANKS, key=RANKS.get)


def test_agree_filter_sends_a_disagreeing_candidate_to_the_median():
    params = resolve_direction_overlay({"enabled": True, "mode": "agree_filter", "margin": 0.05})
    probabilities = {"A": 0.40, "B": 0.55, "C": 0.5, "D": 0.7, "E": 0.45}
    out = apply_direction_overlay(RANKS, probabilities, params)
    assert out["A"] == pytest.approx(0.6)  # a long candidate with p = 0.40 < 0.45 is moved to the median rank
    assert out["D"] == pytest.approx(0.6)  # a short candidate with p = 0.70 > 0.55
    assert out["B"] == RANKS["B"] and out["E"] == RANKS["E"]  # E: p = 0.45 <= 0.55 agrees with a short


def test_groups_are_handled_separately():
    params = resolve_direction_overlay({"enabled": True, "mode": "blend", "weight": 1.0})
    groups = {"A": "main", "B": "main", "C": "bond", "D": "bond", "E": "bond"}
    ranks = {"A": 1.0, "B": 0.5, "C": 1.0, "D": 0.6666666666666666, "E": 0.3333333333333333}
    out = apply_direction_overlay(ranks, {"A": 0.6, "B": 0.4, "C": 0.5, "D": 0.5, "E": 0.5}, params, groups)
    assert out["A"] > out["B"] and out["C"] > out["D"] > out["E"]


def test_calibration_maps():
    assert calibrate_probability(0.7, None) == pytest.approx(0.7)
    assert calibrate_probability(0.7, {"method": "temperature", "temperature": 1.0}) == pytest.approx(0.7)
    assert calibrate_probability(0.7, {"method": "temperature", "temperature": 2.0}) < 0.7
    iso = {"method": "isotonic", "x": [0.3, 0.5, 0.7], "y": [0.45, 0.5, 0.6]}
    assert calibrate_probability(0.6, iso) == pytest.approx(0.55)
    assert calibrate_probability(0.1, iso) == pytest.approx(0.45) and calibrate_probability(0.9, iso) == pytest.approx(0.6)
    assert calibrate_probability(0.6, {"method": "isotonic", "x": [], "y": []}) == pytest.approx(0.6)
