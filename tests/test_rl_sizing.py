"""Tests for risk/rl_sizing.py (development/Problems.md #71, Phase 4.12,
Component E) - pure runtime inference, mirrors tests/test_learned_topology.py's
convention: no mocking, hand-built model/state dicts, every degrade-to-1.0
path exercised explicitly."""

from risk.rl_sizing import (
    RL_SIZING_STATE_KEYS,
    build_rl_sizing_state,
    load_rl_sizing_model,
    rl_sizing_multiplier,
)


def _valid_model(actions=(0.6, 0.8, 1.0)) -> dict:
    n_features = len(RL_SIZING_STATE_KEYS)
    return {
        "state_keys": list(RL_SIZING_STATE_KEYS),
        "actions": list(actions),
        "weights": [[0.0] * n_features for _ in actions],
        "bias": [0.0] * len(actions),
        "mean": [0.0] * n_features,
        "scale": [1.0] * n_features,
    }


def _valid_state() -> dict:
    return {key: 0.0 for key in RL_SIZING_STATE_KEYS}


# ---------------------------------------------------------------------------
# rl_sizing_multiplier - degrade-to-1.0 paths
# ---------------------------------------------------------------------------


def test_rl_sizing_multiplier_disabled_returns_one():
    multiplier, reason = rl_sizing_multiplier(_valid_model(), _valid_state(), rl_sizing_enabled=False)
    assert multiplier == 1.0
    assert reason == "rl_sizing_disabled_or_absent"


def test_rl_sizing_multiplier_missing_model_returns_one():
    multiplier, reason = rl_sizing_multiplier(None, _valid_state(), rl_sizing_enabled=True)
    assert multiplier == 1.0
    assert reason == "rl_sizing_disabled_or_absent"


def test_rl_sizing_multiplier_missing_state_returns_one():
    multiplier, reason = rl_sizing_multiplier(_valid_model(), None, rl_sizing_enabled=True)
    assert multiplier == 1.0
    assert reason == "rl_sizing_disabled_or_absent"


def test_rl_sizing_multiplier_malformed_model_missing_keys_returns_one_not_raise():
    malformed = {"state_keys": list(RL_SIZING_STATE_KEYS)}  # missing actions/weights/bias/mean/scale
    multiplier, reason = rl_sizing_multiplier(malformed, _valid_state(), rl_sizing_enabled=True)
    assert multiplier == 1.0
    assert reason == "rl_sizing_malformed_model"


def test_rl_sizing_multiplier_mismatched_weight_dimensions_returns_one_not_raise():
    model = _valid_model()
    model["weights"] = [[0.0, 0.0]]  # wrong shape vs state_keys/actions
    multiplier, reason = rl_sizing_multiplier(model, _valid_state(), rl_sizing_enabled=True)
    assert multiplier == 1.0
    assert reason == "rl_sizing_malformed_model"


def test_rl_sizing_multiplier_state_key_mismatch_returns_one():
    model = _valid_model()
    model["state_keys"] = ["some_other_key"]
    multiplier, reason = rl_sizing_multiplier(model, _valid_state(), rl_sizing_enabled=True)
    assert multiplier == 1.0
    assert reason == "rl_sizing_state_key_mismatch"


def test_rl_sizing_multiplier_incomplete_state_returns_one_not_raise():
    incomplete_state = {RL_SIZING_STATE_KEYS[0]: 0.5}  # missing every other key
    multiplier, reason = rl_sizing_multiplier(_valid_model(), incomplete_state, rl_sizing_enabled=True)
    assert multiplier == 1.0
    assert reason == "rl_sizing_malformed_model"


# ---------------------------------------------------------------------------
# rl_sizing_multiplier - real scoring path
# ---------------------------------------------------------------------------


def test_rl_sizing_multiplier_zero_initialized_model_prefers_unit_action():
    # All-zero weights/bias -> every action scores identically -> the
    # argmax tie-break (last-highest-wins) must land on the LARGEST
    # (least-aggressive-shrink) action, i.e. an untrained model is a
    # strict no-op, not an arbitrary shrink.
    multiplier, reason = rl_sizing_multiplier(_valid_model(), _valid_state(), rl_sizing_enabled=True)
    assert multiplier == 1.0
    assert reason == "rl_sizing_policy_scaled_sizing"


def test_rl_sizing_multiplier_is_deterministic_argmax_not_sampled():
    model = _valid_model()
    state = _valid_state()
    results = {rl_sizing_multiplier(model, state, rl_sizing_enabled=True) for _ in range(100)}
    assert len(results) == 1  # same (model, state) in -> same result out, every time


def test_rl_sizing_multiplier_picks_highest_scoring_action():
    model = _valid_model(actions=(0.6, 0.8, 1.0))
    n_features = len(RL_SIZING_STATE_KEYS)
    # Bias strongly favors action index 0 (the 0.6 shrink action).
    model["bias"] = [10.0, 0.0, 0.0]
    model["weights"] = [[0.0] * n_features, [0.0] * n_features, [0.0] * n_features]

    multiplier, reason = rl_sizing_multiplier(model, _valid_state(), rl_sizing_enabled=True)

    assert multiplier == 0.6
    assert reason == "rl_sizing_policy_scaled_sizing"


def test_rl_sizing_multiplier_clamped_to_max_even_if_action_set_exceeds_it():
    model = _valid_model(actions=(1.5,))  # a corrupted/adversarial action table
    n_features = len(RL_SIZING_STATE_KEYS)
    model["weights"] = [[0.0] * n_features]
    model["bias"] = [0.0]

    multiplier, _ = rl_sizing_multiplier(model, _valid_state(), rl_sizing_enabled=True, max_rl_multiplier=1.0)

    assert multiplier == 1.0  # clamped down from 1.5


def test_rl_sizing_multiplier_clamped_to_min():
    model = _valid_model(actions=(0.1,))  # below the configured floor
    n_features = len(RL_SIZING_STATE_KEYS)
    model["weights"] = [[0.0] * n_features]
    model["bias"] = [0.0]

    multiplier, _ = rl_sizing_multiplier(model, _valid_state(), rl_sizing_enabled=True, min_rl_multiplier=0.6)

    assert multiplier == 0.6  # clamped up from 0.1


def test_rl_sizing_multiplier_never_negative_or_zero():
    model = _valid_model(actions=(-5.0, 0.0, 3.0))
    n_features = len(RL_SIZING_STATE_KEYS)
    model["weights"] = [[0.0] * n_features, [0.0] * n_features, [10.0] * n_features]  # favors action index 2
    model["bias"] = [0.0, 0.0, 0.0]
    state = {key: 1.0 for key in RL_SIZING_STATE_KEYS}

    multiplier, _ = rl_sizing_multiplier(model, state, rl_sizing_enabled=True, min_rl_multiplier=0.6, max_rl_multiplier=1.0)

    assert multiplier > 0.0
    assert 0.6 <= multiplier <= 1.0


# ---------------------------------------------------------------------------
# build_rl_sizing_state
# ---------------------------------------------------------------------------


def test_build_rl_sizing_state_returns_all_keys_when_present():
    base_features = {key: 1.5 for key in RL_SIZING_STATE_KEYS if key != "confidence"}
    state = build_rl_sizing_state(base_features, confidence=0.75)
    assert state is not None
    assert set(state.keys()) == set(RL_SIZING_STATE_KEYS)
    assert state["confidence"] == 0.75


def test_build_rl_sizing_state_returns_none_on_missing_key():
    base_features = {key: 1.5 for key in RL_SIZING_STATE_KEYS if key not in ("confidence", "alt_implied_volatility_level")}
    state = build_rl_sizing_state(base_features, confidence=0.5)
    assert state is None


# ---------------------------------------------------------------------------
# load_rl_sizing_model
# ---------------------------------------------------------------------------


def test_load_rl_sizing_model_missing_file_returns_none(tmp_path):
    assert load_rl_sizing_model(tmp_path / "does_not_exist.json") is None


def test_load_rl_sizing_model_malformed_json_returns_none(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("not valid json{{{", encoding="utf-8")
    assert load_rl_sizing_model(path) is None


def test_load_rl_sizing_model_valid_file_round_trips(tmp_path):
    import json

    path = tmp_path / "rl_sizing_model.json"
    model = _valid_model()
    path.write_text(json.dumps(model), encoding="utf-8")
    assert load_rl_sizing_model(path) == model
