"""Shared, pure cross-asset "macro" feature implementations (Phase 1b of
the 5/10 -> 9/10 roadmap, see development/Changelog.md) - deliberate,
explicit signals computed once per bar/date from a small set of fixed
reference tickers (the Phase 1a bond ETF sleeve + the existing crypto
sleeve) and broadcast identically to every asset's model input that
bar/date, mirroring how regime state is already a shared, once-per-bar
feature.

This is distinct from - and additive to - the existing generic
correlation-based peer mechanism (topology/market_topology.py's
top_peers/top_peer_returns): that mechanism already lets a bond or crypto
asset surface as an equity's correlated peer purely incidentally, with no
code change needed. These functions instead compute a small, fixed,
always-present macro state (yield-curve slope, credit spread, crypto risk
appetite) that every asset sees identically regardless of whether it
happens to correlate with any one specific reference ticker that day.

Imported by BOTH train.py (offline, per-date lookup across the whole
universe) and main.py (runtime, once per bar) for parity by construction -
same convention as features/technical_indicators.py.

Each function takes plain optional-float 20-day-momentum inputs (reusing
the existing momentum_20d column/computation already produced by
train.py::engineer_features()/main.py's topology-payload step, rather than
re-deriving returns from scratch) and returns a single scalar float. A
missing/unavailable reference ticker (still warming up, or absent from
this particular universe configuration) neutral-defaults its proxy to 0.0
- never raises - same "missing peer -> 0.0" convention peer-return
features already established.
"""

from __future__ import annotations

YIELD_CURVE_SLOPE_NEUTRAL = 0.0
CREDIT_SPREAD_NEUTRAL = 0.0
CRYPTO_RISK_APPETITE_NEUTRAL = 0.0


def yield_curve_slope_proxy(
    long_duration_momentum_20d: float | None,
    short_duration_momentum_20d: float | None,
) -> float:
    """Relative 20-day momentum spread between a long-duration Treasury
    ETF (e.g. TLT) and a short-duration one (e.g. SHY) - a proxy for
    curve-steepening (positive: long duration outperforming, typically
    falling long yields relative to short) vs. flattening/inverting
    (negative) sentiment, computable from price data alone with no
    separate yield-level data feed. Returns YIELD_CURVE_SLOPE_NEUTRAL (0.0)
    when either input is unavailable (reference ticker missing or still
    warming up)."""
    if long_duration_momentum_20d is None or short_duration_momentum_20d is None:
        return YIELD_CURVE_SLOPE_NEUTRAL
    return long_duration_momentum_20d - short_duration_momentum_20d


def credit_spread_proxy(
    high_yield_momentum_20d: float | None,
    investment_grade_momentum_20d: float | None,
) -> float:
    """Relative 20-day momentum spread between a high-yield corporate bond
    ETF (e.g. HYG) and an investment-grade one (e.g. LQD) - widens
    (negative: high-yield underperforming investment-grade) when credit
    risk appetite deteriorates, a standard risk-off signal. Returns
    CREDIT_SPREAD_NEUTRAL (0.0) when either input is unavailable."""
    if high_yield_momentum_20d is None or investment_grade_momentum_20d is None:
        return CREDIT_SPREAD_NEUTRAL
    return high_yield_momentum_20d - investment_grade_momentum_20d


def crypto_risk_appetite_proxy(crypto_momentum_20d: float | None) -> float:
    """20-day momentum of a liquid crypto reference asset (e.g. BTCUSD) -
    a fast-moving risk-on/risk-off signal distinct from the slower-moving
    bond-based proxies above, given crypto's comparatively higher
    volatility and shorter mean-reversion cycles. Returns
    CRYPTO_RISK_APPETITE_NEUTRAL (0.0) when the reference asset's momentum
    is unavailable."""
    if crypto_momentum_20d is None:
        return CRYPTO_RISK_APPETITE_NEUTRAL
    return crypto_momentum_20d
