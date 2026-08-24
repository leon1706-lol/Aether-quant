"""V5.4.2 - tests for the Almgren-style market-impact model."""

from __future__ import annotations


import pytest

from evaluation.impact_model import (
    DEFAULT_ETA_BY_SECURITY_TYPE,
    compute_participation_rate,
    compute_sqrt_impact_bps,
)


class TestSqrtImpact:
    def test_impact_scales_with_sqrt_of_participation(self):
        base = compute_sqrt_impact_bps(
            trade_size_fraction=0.01, daily_volatility=0.02,
            avg_daily_dollar_volume=50e6, portfolio_value=1e6, eta=0.5,
        )
        quadrupled = compute_sqrt_impact_bps(
            trade_size_fraction=0.04, daily_volatility=0.02,
            avg_daily_dollar_volume=50e6, portfolio_value=1e6, eta=0.5,
        )
        assert quadrupled == pytest.approx(base * 2.0, rel=0.01)

    def test_zero_trade_size_gives_zero_impact(self):
        assert compute_sqrt_impact_bps(
            trade_size_fraction=0, daily_volatility=0.02,
            avg_daily_dollar_volume=50e6, portfolio_value=1e6, eta=0.5,
        ) == 0.0

    def test_zero_adv_gives_zero_impact(self):
        assert compute_sqrt_impact_bps(
            trade_size_fraction=0.05, daily_volatility=0.02,
            avg_daily_dollar_volume=0, portfolio_value=1e6, eta=0.5,
        ) == 0.0

    def test_zero_volatility_gives_zero_impact(self):
        assert compute_sqrt_impact_bps(
            trade_size_fraction=0.05, daily_volatility=0,
            avg_daily_dollar_volume=50e6, portfolio_value=1e6, eta=0.5,
        ) == 0.0

    def test_higher_eta_means_more_impact(self):
        low = compute_sqrt_impact_bps(
            trade_size_fraction=0.05, daily_volatility=0.02,
            avg_daily_dollar_volume=50e6, portfolio_value=1e6, eta=0.3,
        )
        high = compute_sqrt_impact_bps(
            trade_size_fraction=0.05, daily_volatility=0.02,
            avg_daily_dollar_volume=50e6, portfolio_value=1e6, eta=1.0,
        )
        assert high > low


class TestParticipationRate:
    def test_basic_computation(self):
        rate = compute_participation_rate(
            trade_size_fraction=0.05, portfolio_value=1e6, avg_daily_dollar_volume=10e6
        )
        assert rate == pytest.approx(0.005)


def test_default_eta_by_security_type():
    assert DEFAULT_ETA_BY_SECURITY_TYPE["equity"] == 0.5
    assert DEFAULT_ETA_BY_SECURITY_TYPE["crypto"] > DEFAULT_ETA_BY_SECURITY_TYPE["equity"]
