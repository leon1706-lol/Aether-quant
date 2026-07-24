from inference.strategy_selector_inference import (
    FEATURE_KEYS,
    build_strategy_selector_features,
    score_strategies,
)


# ---------------------------------------------------------------------------
# build_strategy_selector_features
# ---------------------------------------------------------------------------


def test_build_strategy_selector_features_extracts_expected_keys():
    base_features = {"regime_signal_risk_score": 0.4, "regime_signal_trend_score": -0.2}
    topology = {"correlation_strength": 0.7}
    result = build_strategy_selector_features(base_features, topology)
    assert result == {
        "regime_risk_score": 0.4,
        "regime_trend_score": -0.2,
        "topology_correlation_strength": 0.7,
    }
    assert set(result.keys()) == set(FEATURE_KEYS)


def test_build_strategy_selector_features_missing_keys_default_to_zero():
    assert build_strategy_selector_features({}, {}) == {
        "regime_risk_score": 0.0,
        "regime_trend_score": 0.0,
        "topology_correlation_strength": 0.0,
    }


def test_build_strategy_selector_features_none_topology_never_raises():
    result = build_strategy_selector_features({"regime_signal_risk_score": 0.1}, None)
    assert result["topology_correlation_strength"] == 0.0


# ---------------------------------------------------------------------------
# score_strategies
# ---------------------------------------------------------------------------


def test_score_strategies_none_model_returns_empty():
    assert score_strategies(None, {"regime_risk_score": 0.5}) == {}


def test_score_strategies_empty_model_returns_empty():
    assert score_strategies({}, {"regime_risk_score": 0.5}) == {}


def test_score_strategies_missing_scorers_key_returns_empty():
    assert score_strategies({"strategy_names": ["iron_condor"]}, {"regime_risk_score": 0.5}) == {}


def test_score_strategies_computes_linear_score():
    model = {
        "scorers": {
            "iron_condor": {"weights": {"regime_risk_score": 2.0, "topology_correlation_strength": 1.0}, "bias": 0.1},
            "short_straddle": {"weights": {"regime_risk_score": -1.0}, "bias": 0.0},
        }
    }
    features = {"regime_risk_score": 0.5, "topology_correlation_strength": 0.2}
    scores = score_strategies(model, features)
    assert abs(scores["iron_condor"] - (0.1 + 2.0 * 0.5 + 1.0 * 0.2)) < 1e-9
    assert abs(scores["short_straddle"] - (0.0 + -1.0 * 0.5)) < 1e-9


def test_score_strategies_missing_feature_key_in_weights_defaults_to_zero_weight():
    model = {"scorers": {"iron_condor": {"weights": {}, "bias": 0.3}}}
    scores = score_strategies(model, {"regime_risk_score": 0.9})
    assert scores["iron_condor"] == 0.3


def test_score_strategies_malformed_scorer_entry_skipped_not_raise():
    model = {
        "scorers": {
            "iron_condor": {"weights": {"regime_risk_score": 1.0}, "bias": 0.0},
            "broken": "not_a_dict",
        }
    }
    scores = score_strategies(model, {"regime_risk_score": 1.0})
    assert scores == {"iron_condor": 1.0}
    assert "broken" not in scores
