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


# --- V6.6.4 (B5, Problems #61): the selector end to end on synthetic outcomes ---------------------------------------------------------------------------
# Events -> main() -> artifacts -> score_strategies -> the router's reranking. Everything goes to tmp_path: a model fitted on synthetic rows is never written
# under ml/ and never enabled.

def _outcomes(count_per_strategy: int = 200) -> list[dict]:
    events = []
    for index in range(count_per_strategy):
        risk = (index % 20) / 20.0  # 0.0 .. 0.95
        # iron_condor profits when the regime is calm, straddle when it is stressed
        events.append(_event(strategy_name="iron_condor", realized_pnl=50.0 if risk < 0.5 else -40.0, regime={"risk_score": risk, "trend_score": 0.0}))
        events.append(_event(strategy_name="straddle", realized_pnl=30.0 if risk >= 0.5 else -30.0, regime={"risk_score": risk, "trend_score": 0.0}))
    return events


def _run_main(monkeypatch, tmp_path, events, config_training=None):
    import json
    import sys

    import train_strategy_selector as trainer

    config = {"phase_v2": {"strategy_selector": {"training": config_training or {"min_training_events": 300, "lookback_days": 90, "min_events_per_strategy": 20}}}}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    class FakeConnection:
        def close(self):
            pass

    monkeypatch.setattr("psycopg.connect", lambda *args, **kwargs: FakeConnection())
    monkeypatch.setattr(trainer, "fetch_recent_events", lambda *args, **kwargs: events)
    monkeypatch.setattr(trainer, "ML_DIR", tmp_path / "ml")
    monkeypatch.setattr(sys, "argv", ["train_strategy_selector", "--version-id", "v-test", "--config-path", str(config_path)])
    return trainer.main(), trainer.strategy_selector_candidate_output_paths("v-test")


def test_selector_trains_scores_and_reranks_end_to_end(monkeypatch, tmp_path):
    import json

    from inference.strategy_selector_inference import build_strategy_selector_features, score_strategies
    from portfolio.options_strategy import rerank_enabled_strategies_by_score

    code, paths = _run_main(monkeypatch, tmp_path, _outcomes())
    assert code == 0
    model = json.loads(paths["strategy_selector_model"].read_text(encoding="utf-8"))
    assert set(model["strategy_names"]) == {"iron_condor", "straddle"} and model["feature_keys"] == list(FEATURE_KEYS)
    metrics = json.loads(paths["strategy_selector_training_metrics"].read_text(encoding="utf-8"))
    assert metrics["strategies_scored"] == 2 and metrics["sample_count"] == 400

    calm = build_strategy_selector_features({"regime_signal_risk_score": 0.1, "regime_signal_trend_score": 0.0}, {"correlation_strength": 0.4})
    stressed = build_strategy_selector_features({"regime_signal_risk_score": 0.9, "regime_signal_trend_score": 0.0}, {"correlation_strength": 0.4})
    calm_scores, stressed_scores = score_strategies(model, calm), score_strategies(model, stressed)
    assert calm_scores["iron_condor"] > calm_scores["straddle"], "calm regime prefers the condor"
    assert stressed_scores["straddle"] > stressed_scores["iron_condor"], "stressed regime prefers the straddle"
    names = ["straddle", "iron_condor", "butterfly_call"]
    assert rerank_enabled_strategies_by_score(names, calm_scores) == ["iron_condor", "straddle", "butterfly_call"], "an unscored name sinks, nothing is dropped"
    assert rerank_enabled_strategies_by_score(names, stressed_scores) == ["straddle", "iron_condor", "butterfly_call"]
    assert paths["version_dir"].is_relative_to(tmp_path), "artifacts stay under tmp_path, never under ml/"


def test_selector_writes_nothing_below_the_event_floor_and_scores_nothing_without_a_model(monkeypatch, tmp_path):
    from inference.strategy_selector_inference import score_strategies

    code, paths = _run_main(monkeypatch, tmp_path, _outcomes(count_per_strategy=40))  # 80 events < 300
    assert code == 0 and not paths["strategy_selector_model"].exists()
    assert score_strategies(None, {"regime_risk_score": 0.1}) == {} and score_strategies({"scorers": {}}, {}) == {}


def test_a_strategy_whose_outcomes_never_vary_is_not_scored(monkeypatch, tmp_path):
    import json

    events = _outcomes() + [_event(strategy_name="naked_put", realized_pnl=10.0) for _ in range(50)]  # one outcome class only
    code, paths = _run_main(monkeypatch, tmp_path, events)
    model = json.loads(paths["strategy_selector_model"].read_text(encoding="utf-8"))
    assert code == 0 and "naked_put" not in model["scorers"] and "iron_condor" in model["scorers"]
