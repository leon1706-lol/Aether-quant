"""Tests for train_strategy_selector.py — V4.7 learned strategy-selector
offline trainer (development/Problems.md #29's own framing).

Conventions: no test classes, module-level helpers, plain dicts. Only the
pure functions are exercised here (feature building, scorer fitting) -
main()'s Postgres connection and file writes are left untested at the
unit level, mirroring tests/test_train_topology.py's own precedent."""

from inference.strategy_selector_inference import FEATURE_KEYS
from train_strategy_selector import (
    build_feature_vector,
    fit_strategy_scorers,
    strategy_selector_candidate_output_paths,
)


def _event(**overrides) -> dict:
    defaults = {
        "event_type": "option_strategy_outcome",
        "strategy_name": "iron_condor",
        "realized_pnl": 50.0,
        "regime": {"risk_score": 0.3, "trend_score": -0.1},
        "topology": {"correlation_strength": 0.4},
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# build_feature_vector
# ---------------------------------------------------------------------------


def test_build_feature_vector_returns_all_feature_keys():
    vector = build_feature_vector(_event())
    assert vector is not None
    assert set(vector.keys()) == set(FEATURE_KEYS)
    assert all(isinstance(value, float) for value in vector.values())


def test_build_feature_vector_matches_expected_values():
    vector = build_feature_vector(_event())
    assert vector == {
        "regime_risk_score": 0.3,
        "regime_trend_score": -0.1,
        "topology_correlation_strength": 0.4,
    }


def test_build_feature_vector_none_when_neither_subpayload_present():
    assert build_feature_vector(_event(regime=None, topology=None)) is None


def test_build_feature_vector_missing_individual_keys_default_to_zero():
    vector = build_feature_vector(_event(regime={}, topology={}))
    assert vector == {"regime_risk_score": 0.0, "regime_trend_score": 0.0, "topology_correlation_strength": 0.0}


def test_build_feature_vector_present_regime_absent_topology_still_usable():
    vector = build_feature_vector(_event(topology=None))
    assert vector is not None
    assert vector["topology_correlation_strength"] == 0.0


# ---------------------------------------------------------------------------
# fit_strategy_scorers
# ---------------------------------------------------------------------------


def _win_loss_vectors(n_win: int, n_loss: int) -> tuple[list[dict], list[int]]:
    vectors = [
        {"regime_risk_score": 0.8, "regime_trend_score": 0.5, "topology_correlation_strength": 0.1}
        for _ in range(n_win)
    ] + [
        {"regime_risk_score": 0.1, "regime_trend_score": -0.5, "topology_correlation_strength": 0.8}
        for _ in range(n_loss)
    ]
    labels = [1] * n_win + [0] * n_loss
    return vectors, labels


def test_fit_strategy_scorers_produces_scorer_when_threshold_met():
    vectors, labels = _win_loss_vectors(15, 15)
    scorers, metrics = fit_strategy_scorers(
        {"iron_condor": vectors}, {"iron_condor": labels}, min_events_per_strategy=20
    )
    assert "iron_condor" in scorers
    assert set(scorers["iron_condor"].keys()) == {"weights", "bias"}
    assert set(scorers["iron_condor"]["weights"].keys()) == set(FEATURE_KEYS)
    assert metrics[0]["scored"] is True
    assert metrics[0]["sample_count"] == 30


def test_fit_strategy_scorers_skips_strategy_below_min_events():
    vectors, labels = _win_loss_vectors(5, 5)
    scorers, metrics = fit_strategy_scorers(
        {"iron_condor": vectors}, {"iron_condor": labels}, min_events_per_strategy=20
    )
    assert scorers == {}
    assert metrics[0]["scored"] is False
    assert metrics[0]["sample_count"] == 10


def test_fit_strategy_scorers_skips_strategy_with_single_outcome_class():
    vectors, labels = _win_loss_vectors(30, 0)  # every sample a win - no losses at all
    scorers, metrics = fit_strategy_scorers(
        {"iron_condor": vectors}, {"iron_condor": labels}, min_events_per_strategy=20
    )
    assert scorers == {}
    assert metrics[0]["scored"] is False
    assert metrics[0]["win_rate"] == 1.0


def test_fit_strategy_scorers_handles_multiple_strategies_independently():
    win_vectors, win_labels = _win_loss_vectors(15, 15)
    thin_vectors, thin_labels = _win_loss_vectors(2, 2)
    scorers, metrics = fit_strategy_scorers(
        {"iron_condor": win_vectors, "short_straddle": thin_vectors},
        {"iron_condor": win_labels, "short_straddle": thin_labels},
        min_events_per_strategy=20,
    )
    assert "iron_condor" in scorers
    assert "short_straddle" not in scorers
    assert len(metrics) == 2


def test_fit_strategy_scorers_never_raises_on_empty_input():
    scorers, metrics = fit_strategy_scorers({}, {}, min_events_per_strategy=20)
    assert scorers == {}
    assert metrics == []


# ---------------------------------------------------------------------------
# strategy_selector_candidate_output_paths
# ---------------------------------------------------------------------------


def test_strategy_selector_candidate_output_paths_shape():
    paths = strategy_selector_candidate_output_paths("abc-123")
    assert paths["strategy_selector_model"].name == "strategy_selector_model.json"
    assert paths["strategy_selector_training_metrics"].name == "strategy_selector_training_metrics.json"
    assert paths["strategy_selector_feature_schema"].name == "strategy_selector_feature_schema.json"
    assert paths["version_dir"].name == "abc-123"
    for key in ("strategy_selector_model", "strategy_selector_training_metrics", "strategy_selector_feature_schema"):
        assert paths[key].parent == paths["version_dir"]
