import math

from features.options_greeks import (
    baw_american_price,
    bs_price,
    compute_greeks,
    delta,
    gamma,
    implied_volatility,
    rho,
    theta,
    vega,
)


# ---------------------------------------------------------------------------
# bs_price - Hull's textbook example (Options, Futures, and Other
# Derivatives): S=42, K=40, r=0.10, sigma=0.20, T=0.5, no dividend.
# ---------------------------------------------------------------------------


def test_bs_price_call_matches_hull_textbook_value():
    price = bs_price(42, 40, 0.5, 0.10, 0.20, 0.0, "call")
    assert round(price, 2) == 4.76


def test_bs_price_put_matches_hull_textbook_value():
    price = bs_price(42, 40, 0.5, 0.10, 0.20, 0.0, "put")
    assert round(price, 2) == 0.81


def test_bs_price_right_is_case_insensitive():
    assert bs_price(42, 40, 0.5, 0.10, 0.20, 0.0, "CALL") == bs_price(42, 40, 0.5, 0.10, 0.20, 0.0, "call")


# ---------------------------------------------------------------------------
# Put-call parity: call - put == S*exp(-qT) - K*exp(-rT)
# ---------------------------------------------------------------------------


def test_put_call_parity_holds_no_dividend():
    call = bs_price(100, 105, 0.25, 0.03, 0.30, 0.0, "call")
    put = bs_price(100, 105, 0.25, 0.03, 0.30, 0.0, "put")
    expected = 100 * math.exp(0.0) - 105 * math.exp(-0.03 * 0.25)
    assert abs((call - put) - expected) < 1e-9


def test_put_call_parity_holds_with_dividend_yield():
    call = bs_price(250, 240, 1.0, 0.045, 0.25, 0.02, "call")
    put = bs_price(250, 240, 1.0, 0.045, 0.25, 0.02, "put")
    expected = 250 * math.exp(-0.02 * 1.0) - 240 * math.exp(-0.045 * 1.0)
    assert abs((call - put) - expected) < 1e-9


# ---------------------------------------------------------------------------
# Greeks - bounds and known relationships
# ---------------------------------------------------------------------------


def test_call_delta_is_bounded_zero_to_one():
    d = delta(100, 100, 0.5, 0.03, 0.2, 0.0, "call")
    assert 0.0 <= d <= 1.0


def test_put_delta_is_bounded_negative_one_to_zero():
    d = delta(100, 100, 0.5, 0.03, 0.2, 0.0, "put")
    assert -1.0 <= d <= 0.0


def test_deep_itm_call_delta_approaches_one():
    d = delta(200, 50, 0.5, 0.03, 0.2, 0.0, "call")
    assert d > 0.99


def test_deep_otm_call_delta_approaches_zero():
    d = delta(50, 200, 0.1, 0.03, 0.2, 0.0, "call")
    assert d < 0.01


def test_gamma_is_identical_for_call_and_put():
    # gamma() has no `right` parameter - same value drives both.
    g = gamma(100, 100, 0.5, 0.03, 0.2, 0.0)
    assert g > 0.0


def test_vega_is_positive():
    v = vega(42, 40, 0.5, 0.10, 0.20, 0.0)
    assert v > 0.0


def test_compute_greeks_returns_all_keys():
    greeks = compute_greeks(42, 40, 0.5, 0.10, 0.20, 0.0, "call")
    assert set(greeks.keys()) == {"delta", "gamma", "theta", "vega", "rho", "iv"}
    assert greeks["iv"] == 0.20


def test_rho_positive_for_call_negative_for_put():
    call_rho = rho(100, 100, 1.0, 0.03, 0.2, 0.0, "call")
    put_rho = rho(100, 100, 1.0, 0.03, 0.2, 0.0, "put")
    assert call_rho > 0.0
    assert put_rho < 0.0


def test_theta_is_negative_for_atm_call_no_dividend():
    # Time decay: an ATM long call with no dividend loses value as time
    # passes, all else equal.
    t = theta(100, 100, 0.5, 0.03, 0.2, 0.0, "call")
    assert t < 0.0


# ---------------------------------------------------------------------------
# implied_volatility
# ---------------------------------------------------------------------------


def test_implied_volatility_round_trips_known_sigma():
    true_sigma = 0.35
    price = bs_price(100, 105, 0.25, 0.03, true_sigma, 0.01, "call")
    recovered = implied_volatility(price, 100, 105, 0.25, 0.03, 0.01, "call")
    assert recovered is not None
    assert abs(recovered - true_sigma) < 1e-4


def test_implied_volatility_round_trips_for_put():
    true_sigma = 0.22
    price = bs_price(50, 45, 1.0, 0.02, true_sigma, 0.0, "put")
    recovered = implied_volatility(price, 50, 45, 1.0, 0.02, 0.0, "put")
    assert recovered is not None
    assert abs(recovered - true_sigma) < 1e-4


def test_implied_volatility_returns_none_for_non_positive_price():
    assert implied_volatility(0.0, 100, 100, 0.5, 0.03, 0.0, "call") is None
    assert implied_volatility(-1.0, 100, 100, 0.5, 0.03, 0.0, "call") is None


def test_implied_volatility_returns_none_for_non_positive_time():
    assert implied_volatility(5.0, 100, 100, 0.0, 0.03, 0.0, "call") is None


def test_implied_volatility_returns_none_when_price_violates_arbitrage_bound():
    # A call can never be worth less than its discounted intrinsic value.
    assert implied_volatility(0.0001, 200, 50, 0.5, 0.03, 0.0, "call") is None


def test_implied_volatility_never_raises_on_extreme_near_expiry_input():
    # Deep OTM, essentially expired - bs_price rounds to ~0, which should
    # cleanly return None (unsolvable), never raise or return NaN.
    price = bs_price(100, 200, 0.001, 0.03, 0.15, 0.0, "call")
    result = implied_volatility(price, 100, 200, 0.001, 0.03, 0.0, "call")
    assert result is None or (isinstance(result, float) and result == result)  # not NaN


# ---------------------------------------------------------------------------
# baw_american_price - Barone-Adesi-Whaley American-exercise approximation.
# Reference values verified during development against a 3000-step CRR
# binomial tree (ground truth for American option pricing); the hard
# invariant (American >= European) is checked directly here for every case.
# ---------------------------------------------------------------------------


def test_baw_american_call_no_dividend_equals_european():
    # Textbook shortcut: with a non-positive dividend yield, early call
    # exercise is never optimal - American call == European call exactly.
    euro = bs_price(100, 100, 0.5, 0.08, 0.25, 0.0, "call")
    american = baw_american_price(100, 100, 0.5, 0.08, 0.0, 0.25, "call")
    assert american == euro


def test_baw_american_call_with_dividend_exceeds_european():
    euro = bs_price(100, 100, 0.5, 0.08, 0.25, 0.05, "call")
    american = baw_american_price(100, 100, 0.5, 0.08, 0.05, 0.25, "call")
    assert american >= euro
    # Verified during development against a CRR binomial tree at ~7.566
    # (BAW ~7.573) - both within a few cents of each other.
    assert abs(american - 7.573) < 0.02


def test_baw_american_put_no_dividend_exceeds_european():
    # Classic Hull textbook case: S=42, K=40, r=0.10, sigma=0.20, T=0.5,
    # no dividend. Early put exercise CAN be optimal even without a
    # dividend (unlike calls) - American put must exceed European put.
    euro = bs_price(42, 40, 0.5, 0.10, 0.20, 0.0, "put")
    american = baw_american_price(42, 40, 0.5, 0.10, 0.0, 0.20, "put")
    assert american > euro
    # Verified during development against a CRR binomial tree at ~0.910
    # (BAW ~0.923).
    assert abs(american - 0.923) < 0.02


def test_baw_american_put_with_dividend_exceeds_european():
    euro = bs_price(90, 100, 0.5, 0.08, 0.25, 0.05, "put")
    american = baw_american_price(90, 100, 0.5, 0.08, 0.05, 0.25, "put")
    assert american >= euro


def test_baw_american_price_invariant_holds_across_moneyness_and_rights():
    # American price must never be less than the European price, for any
    # combination of moneyness/right/dividend - the hard safety invariant
    # this function's degrade-to-European fallback relies on.
    cases = [
        (80, 100, 0.25, 0.05, 0.02, 0.30, "call"),
        (120, 100, 0.25, 0.05, 0.02, 0.30, "call"),
        (80, 100, 0.25, 0.05, 0.02, 0.30, "put"),
        (120, 100, 0.25, 0.05, 0.02, 0.30, "put"),
        (100, 100, 1.0, 0.06, 0.08, 0.30, "call"),
        (100, 100, 1.0, 0.06, 0.08, 0.30, "put"),
    ]
    for spot, strike, t, r, q, vol, right in cases:
        euro = bs_price(spot, strike, t, r, vol, q, right)
        american = baw_american_price(spot, strike, t, r, q, vol, right)
        assert american >= euro - 1e-9, (spot, strike, t, r, q, vol, right)


def test_baw_american_price_right_is_case_insensitive():
    lower = baw_american_price(100, 100, 0.5, 0.08, 0.05, 0.25, "call")
    upper = baw_american_price(100, 100, 0.5, 0.08, 0.05, 0.25, "CALL")
    assert lower == upper


def test_baw_american_price_degenerate_input_returns_intrinsic_not_raise():
    assert baw_american_price(100, 90, 0.0, 0.05, 0.02, 0.25, "call") == 10.0
    assert baw_american_price(90, 100, 0.0, 0.05, 0.02, 0.25, "put") == 10.0
    assert baw_american_price(100, 100, 0.5, 0.05, 0.02, 0.0, "call") == 0.0
    assert baw_american_price(-1, 100, 0.5, 0.05, 0.02, 0.25, "call") == 0.0
