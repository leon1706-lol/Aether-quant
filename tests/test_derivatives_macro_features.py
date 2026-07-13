from features.derivatives_macro_features import (
    DERIVATIVES_MACRO_FEATURE_NAMES,
    FUTURES_MACRO_FEATURE_NAMES,
    FUTURES_TERM_STRUCTURE_SLOPE_NEUTRAL,
    OPTIONS_IMPLIED_VOL_SKEW_NEUTRAL,
    OPTIONS_MACRO_FEATURE_NAMES,
    OPTIONS_PUT_CALL_RATIO_NEUTRAL,
    futures_term_structure_slope,
    options_implied_vol_skew,
    options_put_call_ratio,
)


# ---------------------------------------------------------------------------
# futures_term_structure_slope
# ---------------------------------------------------------------------------


def test_futures_term_structure_slope_contango_positive():
    slope = futures_term_structure_slope(front_month_price=70.0, next_month_price=71.4)
    assert slope > 0.0


def test_futures_term_structure_slope_backwardation_negative():
    slope = futures_term_structure_slope(front_month_price=71.4, next_month_price=70.0)
    assert slope < 0.0


def test_futures_term_structure_slope_neutral_default_on_missing_input():
    assert futures_term_structure_slope(None, 71.4) == FUTURES_TERM_STRUCTURE_SLOPE_NEUTRAL
    assert futures_term_structure_slope(70.0, None) == FUTURES_TERM_STRUCTURE_SLOPE_NEUTRAL


def test_futures_term_structure_slope_neutral_default_on_zero_front_price():
    assert futures_term_structure_slope(0.0, 71.4) == FUTURES_TERM_STRUCTURE_SLOPE_NEUTRAL


# ---------------------------------------------------------------------------
# options_put_call_ratio (bounded [-1, 1] skew, not a raw ratio)
# ---------------------------------------------------------------------------


def test_options_put_call_ratio_balanced_is_zero():
    assert options_put_call_ratio(put_volume=100, call_volume=100) == 0.0


def test_options_put_call_ratio_put_heavy_is_positive():
    ratio = options_put_call_ratio(put_volume=300, call_volume=100)
    assert ratio > 0.0


def test_options_put_call_ratio_call_heavy_is_negative():
    ratio = options_put_call_ratio(put_volume=100, call_volume=300)
    assert ratio < 0.0


def test_options_put_call_ratio_is_bounded():
    assert options_put_call_ratio(1_000_000, 1) <= 1.0
    assert options_put_call_ratio(1, 1_000_000) >= -1.0


def test_options_put_call_ratio_neutral_default_on_missing_input():
    assert options_put_call_ratio(None, 100) == OPTIONS_PUT_CALL_RATIO_NEUTRAL
    assert options_put_call_ratio(100, None) == OPTIONS_PUT_CALL_RATIO_NEUTRAL


def test_options_put_call_ratio_neutral_default_on_zero_total_volume():
    assert options_put_call_ratio(0, 0) == OPTIONS_PUT_CALL_RATIO_NEUTRAL


# ---------------------------------------------------------------------------
# options_implied_vol_skew
# ---------------------------------------------------------------------------


def test_options_implied_vol_skew_positive_when_puts_more_expensive():
    skew = options_implied_vol_skew(otm_put_iv=0.28, otm_call_iv=0.20)
    assert skew > 0.0


def test_options_implied_vol_skew_neutral_default_on_missing_input():
    assert options_implied_vol_skew(None, 0.20) == OPTIONS_IMPLIED_VOL_SKEW_NEUTRAL
    assert options_implied_vol_skew(0.28, None) == OPTIONS_IMPLIED_VOL_SKEW_NEUTRAL


# ---------------------------------------------------------------------------
# Feature name constants - broadcast-to-all-assets shape / schema stability
# ---------------------------------------------------------------------------


def test_derivatives_macro_feature_names_is_union_of_futures_and_options():
    assert DERIVATIVES_MACRO_FEATURE_NAMES == FUTURES_MACRO_FEATURE_NAMES + OPTIONS_MACRO_FEATURE_NAMES


def test_futures_macro_feature_names_has_one_entry():
    assert FUTURES_MACRO_FEATURE_NAMES == ["futures_term_structure_slope"]


def test_options_macro_feature_names_has_two_entries():
    assert OPTIONS_MACRO_FEATURE_NAMES == ["options_put_call_ratio", "options_implied_vol_skew"]
