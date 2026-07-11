"""Tests for train.py's regime/liquidity/topology-as-input-feature
additions (Phase 1 remainder): add_regime_features(), add_liquidity_features(),
build_topology_features_by_date(), _categorical_feature_names().

Conventions match the rest of this repo's train.py test coverage: no test
classes, module-level helpers, plain dicts/frames. Real train/runtime
parity for these functions was additionally verified manually against
main.py's equivalent runtime logic on the real dataset (see
development/Changelog.md) - not repeated here since that check needs the
real Lean data folder, not just synthetic fixtures.
"""

import math

import numpy as np
import pandas as pd
import pytest

from train import (
    LIQUIDITY_FEATURE_NAMES,
    REGIME_FEATURE_NAMES,
    REGIME_ONEHOT_FEATURE_NAMES,
    TOPOLOGY_FEATURE_NAMES,
    _categorical_feature_names,
    add_liquidity_features,
    add_regime_features,
    build_cross_sectional_rank_targets,
    build_topology_features_by_date,
    peer_return_feature_names,
)
from regime import build_market_regime_vector


# ---------------------------------------------------------------------------
# add_regime_features
# ---------------------------------------------------------------------------


def _sample_engineered_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"momentum_5d": 0.05, "momentum_20d": 0.06, "rolling_volatility_5d": 0.005, "rolling_volatility_20d": 0.005},
            {"momentum_5d": -0.05, "momentum_20d": -0.06, "rolling_volatility_5d": 0.04, "rolling_volatility_20d": 0.04},
            {"momentum_5d": 0.0, "momentum_20d": 0.0, "rolling_volatility_5d": 0.015, "rolling_volatility_20d": 0.015},
        ]
    )


def test_add_regime_features_adds_every_regime_column():
    frame = _sample_engineered_frame()

    result = add_regime_features(frame)

    for name in REGIME_FEATURE_NAMES:
        assert name in result.columns
    assert len(result) == len(frame)


def test_add_regime_features_matches_build_market_regime_vector_directly():
    frame = _sample_engineered_frame()

    result = add_regime_features(frame)

    for index, row in frame.iterrows():
        expected = build_market_regime_vector(
            {
                "momentum_5d": row["momentum_5d"],
                "momentum_20d": row["momentum_20d"],
                "rolling_volatility_5d": row["rolling_volatility_5d"],
                "rolling_volatility_20d": row["rolling_volatility_20d"],
            },
            portfolio_drawdown=0.0,
            average_correlation=0.0,
        )
        assert result.loc[index, "regime_signal_confidence"] == expected.confidence
        assert result.loc[index, "regime_signal_trend_score"] == expected.trend_score
        assert result.loc[index, "regime_signal_risk_score"] == expected.risk_score
        assert result.loc[index, f"regime_trend_{expected.trend_regime}"] == 1.0


def test_add_regime_features_onehot_is_exactly_one_hot_per_row():
    frame = _sample_engineered_frame()
    result = add_regime_features(frame)

    trend_cols = ["regime_trend_bullish", "regime_trend_bearish", "regime_trend_sideways"]
    volatility_cols = ["regime_volatility_low", "regime_volatility_normal", "regime_volatility_high"]
    risk_cols = ["regime_risk_on", "regime_risk_off", "regime_risk_neutral"]

    for cols in (trend_cols, volatility_cols, risk_cols):
        row_sums = result[cols].sum(axis=1)
        assert (row_sums == 1.0).all()


# ---------------------------------------------------------------------------
# add_liquidity_features
# ---------------------------------------------------------------------------


def _sample_raw_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=6, freq="D"),
            "open": [10.0, 11.0, 12.0, 11.5, 12.5, 13.0],
            "high": [11.0, 12.0, 13.0, 12.5, 13.5, 14.0],
            "low": [9.0, 10.0, 11.0, 10.5, 11.5, 12.0],
            "close": [10.0, 12.0, 11.0, 12.0, 13.0, 13.5],
            "volume": [1000.0, 1200.0, 900.0, 1100.0, 1300.0, 1400.0],
        }
    )


def test_add_liquidity_features_adds_both_columns():
    frame = _sample_raw_frame()

    result = add_liquidity_features(frame, "equity")

    for name in LIQUIDITY_FEATURE_NAMES:
        assert name in result.columns
    assert len(result) == len(frame)


def test_add_liquidity_features_log_dollar_volume_matches_hand_computation():
    frame = _sample_raw_frame()

    result = add_liquidity_features(frame, "equity")

    for index, row in frame.iterrows():
        expected = math.log1p(row["close"] * row["volume"])
        assert result.loc[index, "liquidity_log_dollar_volume"] == expected


def test_add_liquidity_features_spread_proxy_never_nan_and_uses_full_raw_window():
    # Regression test for a real bug found via train/runtime parity checking:
    # this must be called on the RAW frame (before engineer_features() drops
    # the first row) so the very first bar's high/low is included in the
    # trailing window - a returns-based feature can't use that first bar
    # (no previous close), but a high/low-based one legitimately can, and
    # main.py's self.symbol_windows does include it.
    frame = _sample_raw_frame()

    result = add_liquidity_features(frame, "equity")

    assert result["liquidity_spread_proxy"].isna().sum() == 0
    assert (result["liquidity_spread_proxy"] >= 0.0).all()


def test_add_liquidity_features_falls_back_to_typical_spread_for_single_bar():
    frame = _sample_raw_frame().iloc[:1]

    result = add_liquidity_features(frame, "crypto")

    # Fewer than 2 bars -> estimate_high_low_spread() can't run -> falls
    # back to TYPICAL_SPREAD_BY_TYPE["crypto"].
    from liquidity import TYPICAL_SPREAD_BY_TYPE

    assert result.loc[0, "liquidity_spread_proxy"] == TYPICAL_SPREAD_BY_TYPE["crypto"]


# ---------------------------------------------------------------------------
# build_topology_features_by_date
# ---------------------------------------------------------------------------


def _returns_frame(dates: list[str], returns: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"date": pd.to_datetime(dates), "close_to_close_return_1d": returns})


def test_build_topology_features_by_date_adds_columns_to_every_asset_frame():
    dates = [f"2020-01-{day:02d}" for day in range(1, 11)]
    asset_frames = {
        "A": _returns_frame(dates, [0.01, 0.02, -0.01, 0.015, 0.005, 0.01, -0.02, 0.03, 0.0, 0.01]),
        "B": _returns_frame(dates, [0.01, 0.021, -0.011, 0.014, 0.006, 0.011, -0.019, 0.031, 0.001, 0.011]),
    }
    config = {"phase_v2": {"topology": {"correlation_threshold": 0.6, "link_threshold": 0.5, "min_observations": 3}}}

    result = build_topology_features_by_date(asset_frames, config)

    for ticker, frame in result.items():
        for name in TOPOLOGY_FEATURE_NAMES:
            assert name in frame.columns
        assert len(frame) == len(asset_frames[ticker])


def test_build_topology_features_by_date_highly_correlated_assets_get_high_correlation_strength():
    dates = [f"2020-01-{day:02d}" for day in range(1, 11)]
    shared_returns = [0.01, 0.02, -0.01, 0.015, 0.005, 0.01, -0.02, 0.03, 0.0, 0.01]
    asset_frames = {
        "A": _returns_frame(dates, shared_returns),
        "B": _returns_frame(dates, shared_returns),  # identical -> perfectly correlated
    }
    config = {"phase_v2": {"topology": {"correlation_threshold": 0.6, "link_threshold": 0.5, "min_observations": 3}}}

    result = build_topology_features_by_date(asset_frames, config)

    last_row_a = result["A"].iloc[-1]
    assert last_row_a["topology_correlation_strength"] > 0.9
    assert last_row_a["topology_risk_normal"] == 1.0


def test_build_topology_features_by_date_single_asset_defaults_to_isolated():
    dates = [f"2020-01-{day:02d}" for day in range(1, 11)]
    asset_frames = {"A": _returns_frame(dates, [0.01] * 10)}
    config = {"phase_v2": {"topology": {"correlation_threshold": 0.6, "link_threshold": 0.5, "min_observations": 3}}}

    result = build_topology_features_by_date(asset_frames, config)

    assert (result["A"]["topology_correlation_strength"] == 0.0).all()
    assert (result["A"]["topology_risk_isolated"] == 1.0).all()


def test_build_topology_features_by_date_early_rows_before_min_observations_default_isolated_not_nan():
    dates = [f"2020-01-{day:02d}" for day in range(1, 11)]
    asset_frames = {
        "A": _returns_frame(dates, [0.01, 0.02, -0.01, 0.015, 0.005, 0.01, -0.02, 0.03, 0.0, 0.01]),
        "B": _returns_frame(dates, [0.011, 0.019, -0.009, 0.016, 0.004, 0.009, -0.021, 0.029, 0.001, 0.011]),
    }
    config = {"phase_v2": {"topology": {"correlation_threshold": 0.6, "link_threshold": 0.5, "min_observations": 5}}}

    result = build_topology_features_by_date(asset_frames, config)

    # First few rows have fewer than min_observations=5 trailing returns for
    # either asset - must default to isolated/zero, never NaN.
    first_row = result["A"].iloc[0]
    assert first_row["topology_correlation_strength"] == 0.0
    assert first_row["topology_risk_isolated"] == 1.0
    assert result["A"]["topology_correlation_strength"].isna().sum() == 0


# ---------------------------------------------------------------------------
# build_topology_features_by_date's peer-return features (Phase 5)
# ---------------------------------------------------------------------------


def test_peer_return_feature_names_is_schema_stable_never_ticker_named():
    names = peer_return_feature_names(3)

    assert names == ["peer_rank1_return_1d", "peer_rank2_return_1d", "peer_rank3_return_1d", "peer_mean_return_1d"]


def test_build_topology_features_by_date_adds_peer_return_columns():
    dates = [f"2020-01-{day:02d}" for day in range(1, 11)]
    asset_frames = {
        "A": _returns_frame(dates, [0.01, 0.02, -0.01, 0.015, 0.005, 0.01, -0.02, 0.03, 0.0, 0.01]),
        "B": _returns_frame(dates, [0.011, 0.019, -0.009, 0.016, 0.004, 0.009, -0.021, 0.029, 0.001, 0.011]),
    }
    config = {"phase_v2": {"topology": {"correlation_threshold": 0.6, "link_threshold": 0.5, "min_observations": 3, "top_peers_n": 2}}}

    result = build_topology_features_by_date(asset_frames, config)

    for name in peer_return_feature_names(2):
        assert name in result["A"].columns
        assert result["A"][name].isna().sum() == 0  # never NaN, missing peer -> 0.0


def test_build_topology_features_by_date_peer_return_matches_peers_own_latest_return():
    dates = [f"2020-01-{day:02d}" for day in range(1, 11)]
    b_returns = [0.011, 0.019, -0.009, 0.016, 0.004, 0.009, -0.021, 0.029, 0.001, 0.011]
    asset_frames = {
        "A": _returns_frame(dates, [0.01, 0.02, -0.01, 0.015, 0.005, 0.01, -0.02, 0.03, 0.0, 0.01]),
        "B": _returns_frame(dates, b_returns),
    }
    config = {"phase_v2": {"topology": {"correlation_threshold": 0.6, "link_threshold": 0.5, "min_observations": 3, "top_peers_n": 1}}}

    result = build_topology_features_by_date(asset_frames, config)

    # A's only possible peer is B - peer_rank1_return_1d on the last row
    # must equal B's own latest (last-row) return, no lookahead.
    last_row = result["A"].iloc[-1]
    assert last_row["peer_rank1_return_1d"] == pytest.approx(b_returns[-1])
    assert last_row["peer_mean_return_1d"] == pytest.approx(b_returns[-1])


def test_build_topology_features_by_date_single_asset_peer_features_are_zero():
    dates = [f"2020-01-{day:02d}" for day in range(1, 11)]
    asset_frames = {"A": _returns_frame(dates, [0.01] * 10)}
    config = {"phase_v2": {"topology": {"correlation_threshold": 0.6, "link_threshold": 0.5, "min_observations": 3}}}

    result = build_topology_features_by_date(asset_frames, config)

    for name in peer_return_feature_names(3):
        assert (result["A"][name] == 0.0).all()


# ---------------------------------------------------------------------------
# build_cross_sectional_rank_targets
# ---------------------------------------------------------------------------


def _rank_target_frame(dates: list[str], returns_5d: list[float], returns_20d: float = 0.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "target_return_5d": returns_5d,
            "target_return_20d": [returns_20d] * len(dates),
        }
    )


def test_build_cross_sectional_rank_targets_best_performer_gets_top_rank():
    dates = [f"2020-01-{day:02d}" for day in range(1, 6)]
    asset_frames = {
        "BEST": _rank_target_frame(dates, [0.05] * 5),
        "MID": _rank_target_frame(dates, [0.01] * 5),
        "WORST": _rank_target_frame(dates, [-0.05] * 5),
    }
    config = {"phase1": {"target": {"ranking": {"min_universe_size": 2}}}}

    result = build_cross_sectional_rank_targets(asset_frames, config)

    assert (result["BEST"]["target_rank_5d"] == 1.0).all()
    assert np.allclose(result["WORST"]["target_rank_5d"].to_numpy(), 1 / 3)
    assert np.allclose(result["MID"]["target_rank_5d"].to_numpy(), 2 / 3)


def test_build_cross_sectional_rank_targets_propagates_nan_return_as_nan_rank():
    dates = [f"2020-01-{day:02d}" for day in range(1, 6)]
    asset_frames = {
        "A": _rank_target_frame(dates, [0.05, 0.03, np.nan, 0.02, 0.04]),
        "B": _rank_target_frame(dates, [0.01] * 5),
        "C": _rank_target_frame(dates, [-0.05, -0.03, -0.02, np.nan, -0.04]),
    }
    config = {"phase1": {"target": {"ranking": {"min_universe_size": 2}}}}

    result = build_cross_sectional_rank_targets(asset_frames, config)

    assert pd.isna(result["A"]["target_rank_5d"].iloc[2])
    assert pd.isna(result["C"]["target_rank_5d"].iloc[3])
    # every other row still has a real rank
    assert result["A"]["target_rank_5d"].notna().sum() == 4


def test_build_cross_sectional_rank_targets_below_min_universe_size_is_nan():
    dates = [f"2020-01-{day:02d}" for day in range(1, 4)]
    asset_frames = {
        "A": _rank_target_frame(dates, [0.05, 0.03, 0.02]),
        "B": _rank_target_frame(dates, [0.01, 0.01, 0.01]),
    }
    # Only 2 assets ever have data - a min_universe_size of 3 excludes every date.
    config = {"phase1": {"target": {"ranking": {"min_universe_size": 3}}}}

    result = build_cross_sectional_rank_targets(asset_frames, config)

    assert result["A"]["target_rank_5d"].isna().all()
    assert result["B"]["target_rank_5d"].isna().all()


def test_build_cross_sectional_rank_targets_uses_config_default_when_ranking_config_absent():
    dates = [f"2020-01-{day:02d}" for day in range(1, 6)]
    asset_frames = {
        "A": _rank_target_frame(dates, [0.05] * 5),
        "B": _rank_target_frame(dates, [0.01] * 5),
    }

    # No phase1.target.ranking key at all - must fall back to
    # DEFAULT_RANKING_MIN_UNIVERSE_SIZE (10), so a 2-asset universe never
    # meets the bar and every rank is NaN (not an error).
    result = build_cross_sectional_rank_targets(asset_frames, {"phase1": {"target": {}}})

    assert result["A"]["target_rank_5d"].isna().all()


def test_build_cross_sectional_rank_targets_computes_both_horizons_independently():
    dates = [f"2020-01-{day:02d}" for day in range(1, 4)]
    asset_frames = {
        "A": pd.DataFrame(
            {"date": pd.to_datetime(dates), "target_return_5d": [0.05] * 3, "target_return_20d": [-0.05] * 3}
        ),
        "B": pd.DataFrame(
            {"date": pd.to_datetime(dates), "target_return_5d": [0.01] * 3, "target_return_20d": [0.09] * 3}
        ),
    }
    config = {"phase1": {"target": {"ranking": {"min_universe_size": 2}}}}

    result = build_cross_sectional_rank_targets(asset_frames, config)

    # A ranks top on the 5d horizon but bottom on the 20d horizon - the two
    # rank columns must be computed independently, not one derived from
    # the other.
    assert (result["A"]["target_rank_5d"] == 1.0).all()
    assert (result["A"]["target_rank_20d"] == 0.5).all()


# ---------------------------------------------------------------------------
# _categorical_feature_names
# ---------------------------------------------------------------------------


def test_categorical_feature_names_returns_only_columns_present_in_dataset():
    dataset = pd.DataFrame({name: [0.0] for name in REGIME_ONEHOT_FEATURE_NAMES[:2]})

    result = _categorical_feature_names(dataset)

    assert result == REGIME_ONEHOT_FEATURE_NAMES[:2]


def test_categorical_feature_names_empty_when_no_categorical_columns_present():
    dataset = pd.DataFrame({"some_other_column": [0.0]})

    result = _categorical_feature_names(dataset)

    assert result == []
