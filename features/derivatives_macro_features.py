"""Shared, pure futures-term-structure / options-sentiment "macro" feature
implementations - additive third sibling to features/macro_features.py and
features/bond_features.py, broadcast identically to EVERY asset's model
input (not just futures/options assets themselves).

This is the concrete mechanism satisfying the "the model's cross-asset
macro features should include options/futures/bond-derived signals so any
asset's prediction can be informed by them" requirement - generalized well
beyond any single hardcoded pair (e.g. "predict SPY from QQQ options" was
only ever an illustrative example, not a special case to hardcode).

Every function neutral-defaults to 0.0 on missing input - never raises -
same convention as features/macro_features.py. Since real futures
continuous-contract prices and options chain volumes only exist once IB is
connected (phase_v2.ib.enabled), these features are 0.0 for every asset,
every date, until then - a correctness property, not a bug: "no derivatives
data configured" must be indistinguishable in the model input from "the
signal happens to be neutral today," matching every other missing-
reference-ticker case in this codebase.
"""

from __future__ import annotations

FUTURES_TERM_STRUCTURE_SLOPE_NEUTRAL = 0.0
OPTIONS_PUT_CALL_RATIO_NEUTRAL = 0.0
OPTIONS_IMPLIED_VOL_SKEW_NEUTRAL = 0.0

FUTURES_MACRO_FEATURE_NAMES = ["futures_term_structure_slope"]
OPTIONS_MACRO_FEATURE_NAMES = ["options_put_call_ratio", "options_implied_vol_skew"]
DERIVATIVES_MACRO_FEATURE_NAMES = FUTURES_MACRO_FEATURE_NAMES + OPTIONS_MACRO_FEATURE_NAMES


def futures_term_structure_slope(front_month_price: float | None, next_month_price: float | None) -> float:
    """(next_month - front_month) / front_month - positive = contango
    (next-month more expensive, typical/"normal" market), negative =
    backwardation (front-month more expensive, often a supply-stress or
    high-carry-cost signal). Returns
    FUTURES_TERM_STRUCTURE_SLOPE_NEUTRAL (0.0) when either input is
    missing or front_month_price is zero."""
    if front_month_price is None or next_month_price is None or front_month_price == 0:
        return FUTURES_TERM_STRUCTURE_SLOPE_NEUTRAL
    return (next_month_price - front_month_price) / front_month_price


def options_put_call_ratio(put_volume: float | None, call_volume: float | None) -> float:
    """A bounded [-1, 1] put/call VOLUME skew - (put - call) / (put +
    call), not the raw put/call ratio - chosen specifically so 0.0 is a
    genuinely meaningful neutral value (balanced put/call activity OR no
    chain data available, both correctly represented as "no signal"),
    unlike a raw ratio where 0.0 would ambiguously also mean "zero puts,
    some calls" (a real, non-neutral market state). Positive = put-heavy
    (bearish/hedging-heavy sentiment), negative = call-heavy (bullish
    sentiment). Returns OPTIONS_PUT_CALL_RATIO_NEUTRAL (0.0) when either
    input is missing or both volumes are zero."""
    if put_volume is None or call_volume is None:
        return OPTIONS_PUT_CALL_RATIO_NEUTRAL
    total_volume = put_volume + call_volume
    if total_volume <= 0:
        return OPTIONS_PUT_CALL_RATIO_NEUTRAL
    return (put_volume - call_volume) / total_volume


def options_implied_vol_skew(otm_put_iv: float | None, otm_call_iv: float | None) -> float:
    """OTM put implied vol minus OTM call implied vol (both at a matched
    delta, e.g. 25-delta each, per features/options_greeks.py's
    implied_volatility()) - the standard equity-index "smirk" measure;
    positive (the typical case) means downside protection carries a
    volatility premium over upside calls. Returns
    OPTIONS_IMPLIED_VOL_SKEW_NEUTRAL (0.0) when either input is missing."""
    if otm_put_iv is None or otm_call_iv is None:
        return OPTIONS_IMPLIED_VOL_SKEW_NEUTRAL
    return otm_put_iv - otm_call_iv
