"""Tests for features/alt_data_features.py's pure transforms (development/
Problems.md #71). Mirrors tests/test_bond_features.py's convention: no
mocking, hand-computed expected values, explicit None/missing-input cases."""

import math

from features.alt_data_features import (
    FINANCIAL_CONDITIONS_CHANGE_NEUTRAL,
    IMPLIED_VOL_TERM_STRUCTURE_NEUTRAL,
    IMPLIED_VOLATILITY_LEVEL_NEUTRAL,
    VIX_REFERENCE_LEVEL,
    financial_conditions_change,
    implied_vol_term_structure,
    implied_volatility_level,
)


# ---------------------------------------------------------------------------
# implied_volatility_level
# ---------------------------------------------------------------------------


def test_implied_volatility_level_log_ratio_to_reference():
    assert implied_volatility_level(40.0) == math.log(40.0 / VIX_REFERENCE_LEVEL)


def test_implied_volatility_level_at_reference_level_is_zero():
    assert implied_volatility_level(VIX_REFERENCE_LEVEL) == 0.0


def test_implied_volatility_level_none_returns_neutral():
    assert implied_volatility_level(None) == IMPLIED_VOLATILITY_LEVEL_NEUTRAL


def test_implied_volatility_level_zero_returns_neutral():
    assert implied_volatility_level(0.0) == IMPLIED_VOLATILITY_LEVEL_NEUTRAL


def test_implied_volatility_level_negative_returns_neutral():
    assert implied_volatility_level(-5.0) == IMPLIED_VOLATILITY_LEVEL_NEUTRAL


# ---------------------------------------------------------------------------
# implied_vol_term_structure
# ---------------------------------------------------------------------------


def test_implied_vol_term_structure_contango_is_positive():
    # 3-month implied vol priced ABOVE spot - calm market.
    assert implied_vol_term_structure(vix_close=15.0, vix_3m_close=17.0) > 0.0


def test_implied_vol_term_structure_backwardation_is_negative():
    # 3-month implied vol priced BELOW spot - acute near-term stress.
    assert implied_vol_term_structure(vix_close=60.0, vix_3m_close=45.0) < 0.0


def test_implied_vol_term_structure_matches_hand_computation():
    result = implied_vol_term_structure(vix_close=20.0, vix_3m_close=22.0)
    assert result == (22.0 - 20.0) / 20.0


def test_implied_vol_term_structure_missing_vix_returns_neutral():
    assert implied_vol_term_structure(vix_close=None, vix_3m_close=22.0) == IMPLIED_VOL_TERM_STRUCTURE_NEUTRAL


def test_implied_vol_term_structure_missing_vix_3m_returns_neutral():
    assert implied_vol_term_structure(vix_close=20.0, vix_3m_close=None) == IMPLIED_VOL_TERM_STRUCTURE_NEUTRAL


def test_implied_vol_term_structure_zero_vix_returns_neutral():
    assert implied_vol_term_structure(vix_close=0.0, vix_3m_close=22.0) == IMPLIED_VOL_TERM_STRUCTURE_NEUTRAL


# ---------------------------------------------------------------------------
# financial_conditions_change
# ---------------------------------------------------------------------------


def test_financial_conditions_change_matches_hand_computation():
    assert financial_conditions_change(nfci_now=0.60, nfci_prior=-0.10) == 0.70


def test_financial_conditions_change_negative_when_conditions_ease():
    assert financial_conditions_change(nfci_now=-0.10, nfci_prior=0.20) < 0.0


def test_financial_conditions_change_missing_now_returns_neutral():
    assert financial_conditions_change(nfci_now=None, nfci_prior=0.1) == FINANCIAL_CONDITIONS_CHANGE_NEUTRAL


def test_financial_conditions_change_missing_prior_returns_neutral():
    assert financial_conditions_change(nfci_now=0.1, nfci_prior=None) == FINANCIAL_CONDITIONS_CHANGE_NEUTRAL


def test_financial_conditions_change_both_missing_returns_neutral():
    assert financial_conditions_change(nfci_now=None, nfci_prior=None) == FINANCIAL_CONDITIONS_CHANGE_NEUTRAL
