"""Tests for train.py::cross_sectional_residualize()/build_residual_rank_targets()
(V5.1 Phase 2, item 5 of the roadmap). Conventions match the rest of this
repo: no test classes, module-level helpers, plain dicts/DataFrames.
"""

import numpy as np
import pandas as pd
import pytest

from train import build_residual_rank_targets, cross_sectional_residualize


# ---------------------------------------------------------------------------
# cross_sectional_residualize - the pure per-date primitive
# ---------------------------------------------------------------------------


def test_cross_sectional_residualize_recovers_known_noise():
    # A large n (relative to the 2 design columns) so OLS's own finite-
    # sample coefficient-estimation error shrinks toward zero and the
    # residual converges to the TRUE noise - with a small n, an OLS fit's
    # residual is only ever an ESTIMATE of the true noise (the fitted
    # coefficients themselves carry sampling error that leaks into the
    # residual), never an exact recovery - that is a property of
    # regression, not a bug to chase with a tighter tolerance at low n.
    rng = np.random.default_rng(42)
    n = 5000
    intercept = np.ones(n)
    market_term = rng.normal(size=n)
    noise = rng.normal(scale=0.01, size=n)
    returns = 2.0 * market_term + 5.0 + noise

    design_matrix = np.column_stack([intercept, market_term])
    residuals = cross_sectional_residualize(returns, design_matrix)

    # Correlation, not exact equality - even a near-perfect OLS coefficient
    # recovery (verified separately below) leaves each residual carrying a
    # small amount of the fitted coefficients' own sampling error, so
    # residual != noise exactly at any finite n. Correlation is the
    # honest, well-defined statistical claim here.
    assert np.corrcoef(residuals, noise)[0, 1] > 0.999


def test_cross_sectional_residualize_degenerate_date_returns_raw_returns_unchanged():
    # Fewer rows than design columns - genuinely underdetermined.
    returns = np.array([0.01, 0.02])
    design_matrix = np.column_stack([np.ones(2), np.array([1.0, 2.0]), np.array([3.0, 4.0]), np.array([5.0, 6.0])])

    residuals = cross_sectional_residualize(returns, design_matrix)

    assert np.array_equal(residuals, returns)


def test_cross_sectional_residualize_empty_input_never_raises():
    residuals = cross_sectional_residualize(np.array([]), np.zeros((0, 2)))
    assert residuals.size == 0


def test_cross_sectional_residualize_all_factors_disabled_is_a_mean_shift_only():
    # Intercept-only design matrix: OLS fits the mean, so residual =
    # returns - mean(returns) - a per-date shift that NEVER changes rank order.
    returns = np.array([0.05, 0.02, 0.08, 0.01])
    design_matrix = np.ones((4, 1))

    residuals = cross_sectional_residualize(returns, design_matrix)

    assert np.allclose(residuals, returns - returns.mean())
    assert list(pd.Series(residuals).rank()) == list(pd.Series(returns).rank())


# ---------------------------------------------------------------------------
# build_residual_rank_targets - the full per-date/per-horizon pipeline
# ---------------------------------------------------------------------------


def _synthetic_universe(*, num_dates=90, seed=7, tickers_per_sector=40):
    """A universe where forward return is EXACTLY beta_i * market_return_t +
    sector_effect(i) + noise_i,t - the plan's own required test fixture.
    3 sectors x `tickers_per_sector` tickers each, plus a dedicated "MKT"
    market-proxy ticker. tickers_per_sector defaults high (40, well above
    min_universe_size) so each PER-DATE regression (intercept + market +
    2 sector dummies = 4 parameters) has a generous observations-to-
    parameters ratio - OLS's own finite-sample estimation noise (see
    test_cross_sectional_residualize_recovers_known_noise's docstring)
    would otherwise dominate a thin per-date cross-section and mask the
    true recovery this test exists to demonstrate. Includes a
    liquidity_log_dollar_volume column (varies per asset, fixed across
    dates) so the size term has something real to z-score, though the
    core recovery assertions run with size disabled to isolate market/
    sector recovery cleanly."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=num_dates)
    sectors = {}
    betas = {}
    tickers = []
    for sector_index, sector_name in enumerate(["SecA", "SecB", "SecC"]):
        sector_effect = (sector_index - 1) * 0.002  # -0.002, 0.0, +0.002
        for i in range(tickers_per_sector):
            ticker = f"{sector_name}_{i}"
            tickers.append(ticker)
            sectors[ticker] = (sector_name, sector_effect)
            betas[ticker] = 0.5 + (i % 10) * 0.1  # spread of betas within each sector

    market_returns = rng.normal(scale=0.01, size=num_dates)
    noise_by_ticker: dict[str, np.ndarray] = {}
    frames: dict[str, pd.DataFrame] = {}

    for ticker in tickers:
        sector_name, sector_effect = sectors[ticker]
        beta = betas[ticker]
        # Noise scale deliberately comparable to the market term's own
        # scale (beta * market_returns, ~0.005-0.014) - a MUCH smaller
        # noise (e.g. 20x smaller) would make the residual dominated by
        # the whole-history beta ESTIMATE's own small sampling error
        # (empirical_duration_beta() estimates beta from data too, it
        # cannot know the true generating beta), not by the noise this
        # test exists to recover. This is a real property of the two-stage
        # estimator (whole-history beta, then per-date cross-sectional
        # fit), not a bug - see the correlation threshold below.
        noise = rng.normal(scale=0.004, size=num_dates)
        noise_by_ticker[ticker] = noise
        forward_return = beta * market_returns + sector_effect + noise
        frames[ticker] = pd.DataFrame(
            {
                "date": dates,
                "target_return_5d": forward_return,
                "target_return_20d": forward_return,
                "liquidity_log_dollar_volume": np.log(1e6 + hash(ticker) % 1000 * 1e4),
            }
        )

    frames["MKT"] = pd.DataFrame(
        {
            "date": dates,
            "target_return_5d": market_returns,
            "target_return_20d": market_returns,
            "liquidity_log_dollar_volume": np.log(5e7),
        }
    )
    return frames, sectors, betas, noise_by_ticker, tickers


def _config(**residual_overrides):
    residual_neutral = {
        "enabled": True, "market": True, "sector": True, "size": False,
        "size_proxy_column": "liquidity_log_dollar_volume",
        "market_ticker": "MKT", "min_universe_size": 20, "min_beta_observations": 30,
    }
    residual_neutral.update(residual_overrides)
    return {"phase1": {"target": {"ranking": {"residual_neutral": residual_neutral}}}}


def test_build_residual_rank_targets_residual_correlates_with_noise_not_beta():
    frames, sectors, betas, noise_by_ticker, tickers = _synthetic_universe()
    config = _config()

    result = build_residual_rank_targets(frames, config)

    rows = []
    for ticker in tickers:
        frame = result[ticker]
        for date, residual_rank, noise in zip(frame["date"], frame["target_residual_rank_20d"], noise_by_ticker[ticker]):
            if pd.isna(residual_rank):
                continue
            rows.append({"ticker": ticker, "date": date, "residual_rank": residual_rank, "noise": noise, "beta": betas[ticker]})

    combined = pd.DataFrame(rows)
    assert len(combined) > 1000  # sanity: most rows survived the min_universe_size gate

    # Per-date rank of the TRUE noise, for a fair rank-vs-rank comparison.
    combined["noise_rank"] = combined.groupby("date")["noise"].rank(pct=True)
    noise_correlation = combined["residual_rank"].corr(combined["noise_rank"])
    beta_correlation = combined["residual_rank"].corr(combined["beta"])

    assert noise_correlation > 0.5, f"expected strong correlation with the true noise, got {noise_correlation}"
    assert abs(beta_correlation) < 0.1, f"expected near-zero correlation with beta, got {beta_correlation}"


def test_build_residual_rank_targets_disabled_writes_all_nan_columns_only():
    frames, *_ = _synthetic_universe(num_dates=30)
    config = _config(enabled=False)

    result = build_residual_rank_targets(frames, config)

    for ticker, frame in result.items():
        assert frame["target_residual_rank_5d"].isna().all()
        assert frame["target_residual_rank_20d"].isna().all()
        # Every pre-existing column is untouched.
        assert "target_return_5d" in frame.columns
        assert (frame["target_return_5d"] == frames[ticker]["target_return_5d"]).all()


def test_build_residual_rank_targets_all_factors_disabled_matches_plain_rank():
    frames, *_ = _synthetic_universe(num_dates=30)
    config = _config(market=False, sector=False, size=False)

    result = build_residual_rank_targets(frames, config)

    # With every factor off, the design matrix is intercept-only - a
    # per-date mean shift never changes rank order, so residual rank must
    # equal the plain per-date percentile rank of the raw forward return.
    long_rows = []
    for ticker, frame in frames.items():
        for date, value in zip(frame["date"], frame["target_return_20d"]):
            long_rows.append({"ticker": ticker, "date": date, "value": value})
    plain = pd.DataFrame(long_rows)
    plain["plain_rank"] = plain.groupby("date")["value"].rank(pct=True)
    plain_lookup = plain.set_index(["ticker", "date"])["plain_rank"].to_dict()

    for ticker, frame in result.items():
        for date, residual_rank in zip(frame["date"], frame["target_residual_rank_20d"]):
            if pd.isna(residual_rank):
                continue
            assert abs(residual_rank - plain_lookup[(ticker, date)]) < 1e-9


def test_build_residual_rank_targets_thin_date_degrades_to_nan_not_a_crash():
    # A universe far below min_universe_size on every date.
    dates = pd.bdate_range("2020-01-01", periods=10)
    frames = {
        "A": pd.DataFrame({"date": dates, "target_return_5d": 0.01, "target_return_20d": 0.01, "liquidity_log_dollar_volume": 10.0}),
        "B": pd.DataFrame({"date": dates, "target_return_5d": 0.02, "target_return_20d": 0.02, "liquidity_log_dollar_volume": 10.0}),
    }
    config = _config(market=False, sector=False, size=False)
    config["phase1"]["target"]["ranking"]["residual_neutral"]["min_universe_size"] = 20

    result = build_residual_rank_targets(frames, config)

    for ticker, frame in result.items():
        assert frame["target_residual_rank_5d"].isna().all()
        assert frame["target_residual_rank_20d"].isna().all()


def test_build_residual_rank_targets_single_sector_date_does_not_crash():
    # Every ticker in the SAME sector on every date - drop_first sector
    # dummies collapse to zero columns; must still resolve gracefully.
    dates = pd.bdate_range("2020-01-01", periods=40)
    rng = np.random.default_rng(1)
    frames = {}
    for i in range(25):
        frames[f"T{i}"] = pd.DataFrame(
            {
                "date": dates,
                "target_return_5d": rng.normal(scale=0.01, size=40),
                "target_return_20d": rng.normal(scale=0.01, size=40),
                "liquidity_log_dollar_volume": 15.0,
            }
        )
    config = _config(market=False, size=False)  # sector=True, but sector_by_ticker is {} (no mapping file) -> all "Unknown"

    result = build_residual_rank_targets(frames, config)

    for ticker, frame in result.items():
        assert frame["target_residual_rank_20d"].notna().any()


def test_build_residual_rank_targets_missing_market_ticker_falls_back_gracefully():
    frames, *_ = _synthetic_universe(num_dates=30)
    del frames["MKT"]
    config = _config(sector=False, size=False)  # market=True but no market_ticker frame present

    result = build_residual_rank_targets(frames, config)

    # Degrades to market_term == 0 for everyone (never raises) - still
    # produces a well-defined (though market-uninformed) residual rank.
    for ticker, frame in result.items():
        assert frame["target_residual_rank_20d"].notna().any()
