"""V5.3.6 Workstream A - tests for the feature-parity audit core
(evaluation/feature_parity.py). Pure-function coverage: scaler mapping
validation, forward-transform semantics, and replica fidelity against
train.py's own implementations on synthetic data (the same check the CLI
driver performs, pinned here so a future edit to either side fails loudly)."""

import numpy as np
import pandas as pd
import pytest

from features.cross_asset_timing import CrossAssetTimeline

from evaluation.feature_parity import (
    BASE_TECHNICAL_FEATURES,
    DEFAULT_LONG_LOOKBACK_WINDOW_BARS,
    forward_scale,
    load_scaler_mapping,
)


def _scaler_stats():
    return {
        "feature_names": ["f_a", "f_b"],
        "mean": [1.0, -2.0],
        "scale": [4.0, 0.5],
        "clip_sigma": 10.0,
    }


def test_load_scaler_mapping_extracts_triples():
    mapping, uncovered = load_scaler_mapping(_scaler_stats())
    assert uncovered == []
    assert mapping["f_a"] == (1.0, 4.0, 10.0)
    assert mapping["f_b"] == (-2.0, 0.5, 10.0)


def test_forward_scale_matches_manual_transform_and_clips():
    raw = np.array([1.0, 5.0, -39.0, 41.0])  # last two exceed +-10 sigma
    out = forward_scale(raw, mean=1.0, scale=4.0, clip=10.0)
    assert out[0] == pytest.approx(0.0)
    assert out[1] == pytest.approx(1.0)
    assert out[2] == pytest.approx(-10.0)
    assert out[3] == pytest.approx(10.0)


def test_forward_scale_roundtrip_against_train_scaler():
    """The audit's core invariant: train.fit_and_apply_scaler()'s output must
    be reproducible from raw values + the exported stats artifact."""
    import train as train_module

    rng = np.random.default_rng(11)
    frame = pd.DataFrame(
        {
            "split": ["train"] * 200 + ["backtest"] * 50,
            "training_eligible": [True] * 250,
            "feat_x": rng.normal(3.0, 2.0, 250),
        }
    )
    scaled, scaler, clip = train_module.fit_and_apply_scaler(frame.copy(), ["feat_x"])
    stats = {"feature_names": ["feat_x"], "mean": list(scaler.mean_), "scale": list(scaler.scale_), "clip_sigma": clip}
    mapping, _ = load_scaler_mapping(stats)
    mean, scale, clip_value = mapping["feat_x"]

    recomputed = forward_scale(frame["feat_x"].to_numpy(dtype=float), mean, scale, clip_value)
    np.testing.assert_allclose(recomputed, scaled["feat_x_scaled"].to_numpy(dtype=float), atol=1e-12)


def _synthetic_ohlcv(rows: int = 320, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, rows)))
    high = close * (1 + np.abs(rng.normal(0, 0.004, rows)))
    low = close * (1 - np.abs(rng.normal(0, 0.004, rows)))
    open_ = np.clip(close * (1 + rng.normal(0, 0.002, rows)), low, high)
    volume = rng.integers(50_000, 5_000_000, rows).astype(float)
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2019-01-01", periods=rows).strftime("%Y-%m-%d"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


@pytest.mark.parametrize("name", BASE_TECHNICAL_FEATURES)
def test_base_technicals_replica_matches_engineer_features(name):
    """Row-faithful parity with train.py::engineer_features() on every base
    technical - the exact guarantee the live path depends on."""
    import train as train_module

    frame = _synthetic_ohlcv()
    windows = {key: {"start": "1900-01-01", "end": "2099-12-31"} for key in ("training", "validation", "backtest")}
    reference = train_module.engineer_features(frame.copy(), [], windows)
    from evaluation.feature_parity import compute_base_technicals_replica

    replica = compute_base_technicals_replica(frame)
    # engineer_features() drops the LAST row (its shift(-1) target is NaN),
    # so its output aligns with replica rows [:-1].
    ref_col = reference[name].to_numpy(dtype=float)
    rep_col = replica[name][: len(ref_col)]
    assert len(rep_col) == len(ref_col)
    np.testing.assert_allclose(rep_col, ref_col, atol=1e-12, equal_nan=True)


def test_base_technicals_warmup_and_clamp_conventions():
    from evaluation.feature_parity import compute_base_technicals_replica

    frame = _synthetic_ohlcv(rows=60, seed=3)
    replica = compute_base_technicals_replica(frame)
    # First row NaN everywhere (train's [np.nan] seed convention).
    for name in BASE_TECHNICAL_FEATURES:
        assert np.isnan(replica[name][0])
    # Volatility degrades to exactly 0.0 under two observations.
    assert replica["rolling_volatility_5d"][1] == 0.0
    # Volume clamp bounds honored somewhere in a chaotic series.
    assert np.nanmax(replica["volume_change_1d"]) <= 20.0
    assert np.nanmin(replica["volume_change_1d"]) >= -1.0


def test_long_window_constant_is_the_shared_default():
    # Both sides cap macd/dist at this window; if either changes silently the
    # audit driver picks it up via this pin.
    import train as train_module

    assert getattr(train_module, "LONG_LOOKBACK_WINDOW_BARS", DEFAULT_LONG_LOOKBACK_WINDOW_BARS) == 260


def test_macro_and_rank_replicas_match_train_builders_on_mixed_calendars():
    """The audit replicas are independent of CrossAssetTimeline (Problems.md #135): they must still agree with
    train.py row for row, including a 7-day crypto calendar and forex's next-midnight availability."""
    import train as train_module
    from evaluation.feature_parity import compute_cs_momentum_rank_replica, compute_macro_proxies_replica

    rng = np.random.default_rng(5)
    calendar = pd.date_range("2020-01-01", periods=60, freq="D")
    weekdays = calendar[calendar.dayofweek < 5]
    specs = {
        "TLT": ("equity", weekdays), "SHY": ("equity", weekdays), "HYG": ("equity", weekdays), "LQD": ("equity", weekdays),
        "AAPL": ("equity", weekdays[2:]), "BTCUSD": ("crypto", calendar), "EURUSD": ("forex", weekdays),
    }
    frames, types = {}, {}
    for ticker, (security_type, dates) in specs.items():
        frames[ticker] = pd.DataFrame({"date": dates, "close": 100.0 * np.cumprod(1.0 + rng.normal(0, 0.01, len(dates)))})
        types[ticker] = security_type
    timeline = CrossAssetTimeline.from_frames(frames, types)
    macro = train_module.build_macro_features_by_date(frames, {}, timeline)
    rank = train_module.build_cross_sectional_momentum_rank_features(frames, timeline)

    # stored momentum_20d = close / close 20 bars back (short history: vs the first bar), as engineer_features() writes it;
    # forex pairs carry it on Lean's fill-forward calendar, which build_momentum_pool() re-derives with the filler rows
    from evaluation.feature_parity import build_momentum_pool

    momentum_frames = {
        ticker: frame.assign(momentum_20d=[
            frame["close"].iloc[i] / frame["close"].iloc[max(0, i - 20)] - 1.0 if i else float("nan") for i in range(len(frame))
        ])
        for ticker, frame in frames.items()
    }
    dataset_like = pd.concat([frame.assign(ticker=ticker) for ticker, frame in momentum_frames.items()], ignore_index=True)
    momentum_long = build_momentum_pool(dataset_like, types)
    macro_replica = compute_macro_proxies_replica(momentum_long, types).set_index(["ticker", "date"])
    rank_replica = compute_cs_momentum_rank_replica(momentum_long, types).set_index(["ticker", "date"])
    for ticker, frame in frames.items():
        for index, stamp in enumerate(frame["date"]):
            for column in ("macro_yield_curve_slope_proxy", "macro_credit_spread_proxy", "macro_crypto_risk_appetite_proxy"):
                assert macro[ticker].iloc[index][column] == pytest.approx(macro_replica.loc[(ticker, stamp), column], abs=1e-12)
            assert rank[ticker].iloc[index]["cs_momentum_rank_20"] == pytest.approx(
                rank_replica.loc[(ticker, stamp), "cs_momentum_rank_recomputed"], abs=1e-12
            )
