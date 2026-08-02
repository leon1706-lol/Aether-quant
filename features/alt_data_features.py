"""Shared, pure alternative-data feature implementations (development/
Problems.md #71, Phase 4.12) - additive sibling to features/bond_features.py
and features/macro_features.py, backed by data_pipeline/fred_backfill.py's
implied-volatility and financial-conditions series rather than price data.

Broadcast identically to EVERY asset's model input (date-only, not
asset-specific) - same "compute once per date/bar, every asset sees it"
shape as bond_features.py/macro_features.py.

Imported by BOTH train.py (offline, per-date FRED-series lookup via
data_pipeline.fred_backfill.series_value_asof()/series_change_asof()) and
main.py (runtime, once per bar) for parity by construction - same
convention as features/bond_features.py.

Every function neutral-defaults to 0.0 on missing input - never raises.
The 0.0 default is chosen so it means something PLAUSIBLE, not merely
"absent": implied_volatility_level() is a log-ratio to a reference VIX
level (see VIX_REFERENCE_LEVEL below), so its neutral default corresponds
to "VIX = 20," an unremarkable reading, not "VIX = 0," which cannot
happen. This mirrors every other neutral-default in this codebase
(bond_features.py, macro_features.py) using 0.0 to mean "no signal."

These three features were chosen from a wider candidate list (VIX, VXV,
NFCI, STLFSI4, UMCSENT, TEDRATE, SOFR, BAMLH0A0HYM2, DTWEXBGS) after
live-verifying each one's real 2014-2021 coverage and checking pairwise
collinearity - see data_pipeline/fred_backfill.py's
DEFAULT_ALT_DATA_REFERENCE_SERIES docstring for the rejected candidates
and why. The surviving three are deliberately NOT redundant with each
other or with the existing 8 bond_* features: implied_volatility_level
alone cannot distinguish the 2019-12-27..2020-03-25 COVID-crash era (mean
VIX 28.54) from the immediately-following recovery era (mean VIX 29.24) -
term structure and financial-conditions CHANGE can (measured: term
structure mean +0.013 during the crash vs +0.105 after; NFCI 4-week
change mean +0.154/max +0.608 during the crash vs a total 2014-2019 range
of [-0.091, +0.091]).
"""

from __future__ import annotations

import math

IMPLIED_VOLATILITY_LEVEL_NEUTRAL = 0.0
IMPLIED_VOL_TERM_STRUCTURE_NEUTRAL = 0.0
FINANCIAL_CONDITIONS_CHANGE_NEUTRAL = 0.0
REAL_RATE_CHANGE_NEUTRAL = 0.0
BREAKEVEN_INFLATION_CHANGE_NEUTRAL = 0.0
DOLLAR_INDEX_CHANGE_NEUTRAL = 0.0

# Divisor for implied_volatility_level()'s log-ratio - an unremarkable,
# roughly-median VIX reading (measured p50 15.1 over the 2014-12..2021-03
# common_window), chosen so the neutral default (log(1.0) = 0.0) maps back
# to a plausible market state rather than an impossible one (a raw VIX
# feature's 0.0 default would mean "VIX = 0", which never happens).
VIX_REFERENCE_LEVEL = 20.0

ALT_DATA_FEATURE_NAMES = [
    "alt_implied_volatility_level",
    "alt_implied_vol_term_structure",
    "alt_financial_conditions_change",
]


def implied_volatility_level(vix_close: float | None) -> float:
    """log(VIX / VIX_REFERENCE_LEVEL). VIX is right-skewed (measured p50
    15.1 / p90 26.7 / p99 53.9 over the common_window) - a raw level would
    let extreme prints (82.69 in March 2020) dominate the feature scaler's
    clip/winsorize range; the log compresses that skew the same way
    close_to_close_return features already use log-scale-friendly
    transforms elsewhere in this codebase. Returns
    IMPLIED_VOLATILITY_LEVEL_NEUTRAL (0.0) when vix_close is missing or
    non-positive (a non-positive VIX reading is not physically meaningful
    - never log() a non-positive number)."""
    if vix_close is None or vix_close <= 0.0:
        return IMPLIED_VOLATILITY_LEVEL_NEUTRAL
    return math.log(float(vix_close) / VIX_REFERENCE_LEVEL)


def implied_vol_term_structure(vix_close: float | None, vix_3m_close: float | None) -> float:
    """(VIX 3-month - VIX) / VIX - positive means contango (the market is
    calm: longer-dated implied vol priced higher than spot), negative
    means backwardation (stress RIGHT NOW: spot implied vol priced above
    the 3-month tenor, since a acute near-term shock is expected to fade).
    Normalized by the spot VIX level so the ratio is comparable across
    vol regimes - the whole reason this feature exists alongside
    implied_volatility_level() rather than instead of it: VIX level alone
    cannot separate the COVID-crash era from the immediately-following
    recovery era (both ~28-29 mean VIX), while term structure can (+0.013
    during the crash vs +0.105 after, with a -0.256 backwardation minimum
    during the crash). Returns IMPLIED_VOL_TERM_STRUCTURE_NEUTRAL (0.0)
    when either leg is missing or vix_close is non-positive."""
    if vix_close is None or vix_3m_close is None or vix_close <= 0.0:
        return IMPLIED_VOL_TERM_STRUCTURE_NEUTRAL
    return (float(vix_3m_close) - float(vix_close)) / float(vix_close)


def financial_conditions_change(nfci_now: float | None, nfci_prior: float | None) -> float:
    """NFCI(t) - NFCI(t - 4 weeks) - the Chicago Fed National Financial
    Conditions Index's own 4-week CHANGE, not its level. The level is
    deliberately not a feature here: measured correlation of rho=0.73
    against the existing bond_credit_spread_level feature (BAA10Y), i.e.
    the model already has substantially the same information via that
    channel. The 4-week CHANGE is a genuinely different signal (rho=0.23
    against bond_credit_spread_level) - a near-binary "conditions are
    tightening violently right now" indicator: measured mean +0.154 (max
    +0.608) during the 2019-12-27..2020-03-25 COVID-crash era, versus a
    total 2014-12..2019-12 pre-COVID range of only [-0.091, +0.091] - the
    crash reading sits roughly 6.7x outside five years of prior variation.
    Returns FINANCIAL_CONDITIONS_CHANGE_NEUTRAL (0.0) when either endpoint
    is missing (e.g. fewer than 4 weeks of history available yet, or the
    series cache is absent)."""
    if nfci_now is None or nfci_prior is None:
        return FINANCIAL_CONDITIONS_CHANGE_NEUTRAL
    return float(nfci_now) - float(nfci_prior)


def real_rate_change(real_rate_now: float | None, real_rate_prior: float | None) -> float:
    """DFII10(t) - DFII10(t - N) - the 10-year TIPS (real) yield's own
    CHANGE, not its level. V5.1 Phase 2 (item 8 / F2, development/
    Problems.md): a stationary driver for
    features/cross_asset_sensitivity.py's per-asset real-rate sensitivity
    beta - a level would be non-stationary and comparing betas fit against
    a trending regressor across different market eras is not meaningful,
    the same reasoning financial_conditions_change() above already
    documents for NFCI. Returns REAL_RATE_CHANGE_NEUTRAL (0.0) when either
    endpoint is missing."""
    if real_rate_now is None or real_rate_prior is None:
        return REAL_RATE_CHANGE_NEUTRAL
    return float(real_rate_now) - float(real_rate_prior)


def breakeven_inflation_change(breakeven_now: float | None, breakeven_prior: float | None) -> float:
    """T10YIE(t) - T10YIE(t - N) - the 10-year breakeven inflation rate's
    own CHANGE. Same stationarity reasoning as real_rate_change() above -
    a driver for features/cross_asset_sensitivity.py, not a broadcast
    level feature. Returns BREAKEVEN_INFLATION_CHANGE_NEUTRAL (0.0) when
    either endpoint is missing."""
    if breakeven_now is None or breakeven_prior is None:
        return BREAKEVEN_INFLATION_CHANGE_NEUTRAL
    return float(breakeven_now) - float(breakeven_prior)


def dollar_index_change(dollar_index_now: float | None, dollar_index_prior: float | None) -> float:
    """DTWEXBGS(t) - DTWEXBGS(t - N) - the trade-weighted dollar index's
    own CHANGE. Same stationarity reasoning as real_rate_change() above -
    a driver for features/cross_asset_sensitivity.py, not a broadcast
    level feature (see data_pipeline/fred_backfill.py's
    DEFAULT_ALT_DATA_REFERENCE_SERIES docstring for why DTWEXBGS is being
    re-added as a sensitivity driver rather than a level, having
    previously been evaluated and left out of the original alt-data
    trio). Returns DOLLAR_INDEX_CHANGE_NEUTRAL (0.0) when either endpoint
    is missing."""
    if dollar_index_now is None or dollar_index_prior is None:
        return DOLLAR_INDEX_CHANGE_NEUTRAL
    return float(dollar_index_now) - float(dollar_index_prior)
