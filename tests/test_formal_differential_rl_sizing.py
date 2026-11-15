"""risk/rl_sizing.py against its Lean 4 model (formal/AetherFormal/RlSizing.lean)."""

from __future__ import annotations

import math

import pytest

from aether_quant.formal import load_cases, to_float
from risk.rl_sizing import RL_SIZING_STATE_KEYS, rl_shadow_guard_allows, rl_sizing_multiplier


def _model(raw: float) -> dict:
    keys = list(RL_SIZING_STATE_KEYS)
    return {"state_keys": keys, "actions": [raw], "weights": [[0.0] * len(keys)], "bias": [0.0], "mean": [0.0] * len(keys), "scale": [1.0] * len(keys)}


def _value(rational):
    value = to_float(rational)
    return math.nan if value is None else value


def test_python_matches_the_lean_model():
    state = {key: 0.0 for key in RL_SIZING_STATE_KEYS}
    for index, case in enumerate(load_cases("rl_sizing")["cases"]):
        given, expected = case["input"], case["expected"]
        if case["kind"] == "clamp":
            multiplier, reason = rl_sizing_multiplier(_model(to_float(given["raw"])), state, True, _value(given["min"]), _value(given["max"]))
            assert multiplier == pytest.approx(to_float(expected["multiplier"]), abs=1e-12), index
            assert reason == ("rl_sizing_policy_scaled_sizing" if expected["scaled"] else "rl_sizing_invalid_bounds"), index
        else:
            guard = {"enabled": given["enabled"], "window_bars": given["window_bars"], "tolerance_nav_fraction": to_float(given["tolerance"])}
            assert rl_shadow_guard_allows([to_float(x) for x in given["history"]], guard) is expected["allows"], index
