"""Tests for train_topology.py — V2-17.5 learned-topology offline trainer.

Conventions: no test classes, module-level helpers, plain dicts. Only the
pure functions are exercised here (outcome derivation, feature building,
prototype fitting) - main()'s Postgres connection and file writes are left
untested at the unit level, mirroring how train.py's own end-to-end run is
not unit-tested either.
"""

from train_topology import (
    build_feature_vector,
    derive_realized_outcomes,
    fit_prototypes,
    topology_candidate_output_paths,
)
from topology.learned_topology import FEATURE_KEYS


def _event(**overrides) -> dict:
    defaults = {
        "ticker": "AAPL",
        "signal": "hold",
        "action": "observe",
        "probability_up": 0.55,
        "topology": {"volatility_pressure": 0.2, "correlation_strength": 0.4},
        "regime": {"primary_regime": "uptrend_low_vol", "risk_score": 0.3},
        "liquidity": {"participation_rate": 0.01, "estimated_slippage": 0.002},
        "portfolio": {},
    }
    defaults.update(overrides)
    return defaults


def test_derive_realized_outcomes_labels_trade_episode_from_realized_pnl():
    events = [
        _event(ticker="AAPL", action="trade", signal="buy"),
        _event(ticker="AAPL", action="observe", signal="hold"),
        _event(ticker="AAPL", action="observe", signal="hold", portfolio={"last_realized_pnl": 25.0}),
    ]

    outcomes = derive_realized_outcomes(events)

    assert outcomes == ["win", "win", "win"]


def test_derive_realized_outcomes_labels_loss_and_neutral():
    loss_events = [
        _event(ticker="AAPL", action="trade", signal="sell"),
        _event(ticker="AAPL", action="observe", portfolio={"last_realized_pnl": -10.0}),
    ]
    assert derive_realized_outcomes(loss_events) == ["loss", "loss"]

    neutral_events = [
        _event(ticker="AAPL", action="trade", signal="buy"),
        _event(ticker="AAPL", action="observe", portfolio={"last_realized_pnl": 0.0}),
    ]
    assert derive_realized_outcomes(neutral_events) == ["neutral", "neutral"]


def test_derive_realized_outcomes_ignores_unrealized_open_trades():
    events = [
        _event(ticker="AAPL", action="trade", signal="buy"),
        _event(ticker="AAPL", action="observe", signal="hold"),
        _event(ticker="AAPL", action="observe", signal="hold"),
    ]

    outcomes = derive_realized_outcomes(events)

    assert outcomes == [None, None, None]


def test_derive_realized_outcomes_attributes_per_ticker_independently():
    events = [
        _event(ticker="AAPL", action="trade", signal="buy"),
        _event(ticker="BTCUSD", action="trade", signal="sell"),
        _event(ticker="AAPL", action="observe", portfolio={"last_realized_pnl": 15.0}),
        _event(ticker="BTCUSD", action="observe", portfolio={"last_realized_pnl": -5.0}),
    ]

    outcomes = derive_realized_outcomes(events)

    assert outcomes[0] == "win"  # AAPL open
    assert outcomes[1] == "loss"  # BTCUSD open
    assert outcomes[2] == "win"  # AAPL realized
    assert outcomes[3] == "loss"  # BTCUSD realized


def test_build_feature_vector_returns_none_when_topology_missing():
    event = _event(topology=None)

    assert build_feature_vector(event) is None


def test_build_feature_vector_returns_none_when_topology_lacks_volatility_pressure():
    event = _event(topology={"correlation_strength": 0.4})

    assert build_feature_vector(event) is None


def test_build_feature_vector_returns_all_feature_keys():
    vector = build_feature_vector(_event())

    assert vector is not None
    assert set(vector.keys()) == set(FEATURE_KEYS)
    assert all(isinstance(value, float) for value in vector.values())


def test_fit_prototypes_produces_expected_schema():
    feature_vectors = [
        {"volatility": 0.1, "momentum": 0.05, "correlation_strength": 0.6, "liquidity_score": 0.8, "regime_risk_score": -0.2}
        for _ in range(10)
    ] + [
        {"volatility": 0.6, "momentum": -0.1, "correlation_strength": 0.1, "liquidity_score": 0.3, "regime_risk_score": 0.7}
        for _ in range(10)
    ]
    outcome_labels = (["win"] * 10) + (["loss"] * 10)
    regime_labels = (["bullish"] * 10) + (["bearish"] * 10)

    result = fit_prototypes(feature_vectors, outcome_labels, regime_labels, num_prototypes=2, distance_scale_percentile=90)

    assert result["n_clusters"] == 2
    assert len(result["prototypes"]) == 2
    assert result["distance_scale"] > 0.0
    assert set(result["feature_stats"].keys()) == set(FEATURE_KEYS)
    for prototype in result["prototypes"]:
        assert set(prototype["centroid"].keys()) == set(FEATURE_KEYS)
        assert prototype["dominant_regime_label"] in ("bullish", "bearish")
        assert prototype["sample_count"] > 0
        assert 0.0 <= prototype["win_rate"] <= 1.0
        assert set(prototype["offset"].keys()) == {"x", "y", "z"}
        # development/Problems.md #56: z is normalized to [-1, 1]
        # (topology.learned_topology scales it by max_offset_z at apply
        # time), unlike x/y which stay absolute scene units - assert the
        # value, not just the key, so a regression back to the old raw
        # 0..1-scaled formula would be caught here.
        assert -1.0 <= prototype["offset"]["z"] <= 1.0
        expected_z = (prototype["win_rate"] - 0.5) * 2.0
        assert prototype["offset"]["z"] == expected_z

    # The two clusters have win rates on opposite sides of 0.5 (all-win vs
    # all-loss samples) - their z offsets must actually differ, guarding
    # against z collapsing to a binary sign like x/y's offset_sign.
    z_values = {prototype["offset"]["z"] for prototype in result["prototypes"]}
    assert len(z_values) == 2


def test_fit_prototypes_caps_cluster_count_at_sample_count():
    feature_vectors = [
        {"volatility": 0.1, "momentum": 0.0, "correlation_strength": 0.5, "liquidity_score": 0.5, "regime_risk_score": 0.0}
        for _ in range(3)
    ]
    outcome_labels = [None, None, None]
    regime_labels = ["unknown", "unknown", "unknown"]

    result = fit_prototypes(feature_vectors, outcome_labels, regime_labels, num_prototypes=6, distance_scale_percentile=90)

    assert result["n_clusters"] <= 3
    for prototype in result["prototypes"]:
        assert prototype["win_rate"] is None
        assert prototype["offset"]["z"] == 0.0


def test_topology_candidate_output_paths_shape():
    paths = topology_candidate_output_paths("abc-123")

    assert paths["topology_model"].name == "topology_model.json"
    assert paths["topology_training_metrics"].name == "topology_training_metrics.json"
    assert paths["topology_feature_schema"].name == "topology_feature_schema.json"
    assert paths["version_dir"].name == "abc-123"
    for key in ("topology_model", "topology_training_metrics", "topology_feature_schema"):
        assert paths[key].parent == paths["version_dir"]
