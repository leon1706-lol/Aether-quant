"""V4.6 - mispricing detector for the 6 stubbed arbitrage strategies
(development/Problems.md #59/#60, Roadmap "Assets")."""

import math
from datetime import date

import pytest

from portfolio.options_arbitrage_detector import (
    box_spread_fair_value,
    build_arbitrage_position_sizing,
    conversion_parity_value,
    detect_executable_edge,
    detect_mispricing,
    jelly_roll_fair_value,
    select_arbitrage_signal,
)


def _sample_chain(expiries=("2026-08-21",), bid=1.0, ask=1.05) -> list[dict]:
    rows = []
    for expiry in expiries:
        for strike in range(70, 131, 5):
            call_delta = max(0.02, min(0.98, 0.5 + (100 - strike) * 0.02))
            put_delta = call_delta - 1.0
            distance = abs(strike - 100)
            vega = max(0.1, 3.0 - distance * 0.15)
            rows.append({
                "symbol": f"C{strike}_{expiry}", "right": "call", "strike": float(strike), "expiry": expiry,
                "delta": call_delta, "vega": vega, "bid": bid, "ask": ask, "underlying_price": 100.0,
            })
            rows.append({
                "symbol": f"P{strike}_{expiry}", "right": "put", "strike": float(strike), "expiry": expiry,
                "delta": put_delta, "vega": vega, "bid": bid, "ask": ask, "underlying_price": 100.0,
            })
    return rows


def _parity_chain(call_shift: float = 0.0, half_spread: float = 0.05, strikes=(90.0, 100.0, 110.0), rate: float = 0.05) -> list[dict]:
    """A chain priced at put-call parity with no carry skew: spot 100, one expiry a year out; calls moved by `call_shift`."""
    rows = []
    discount = math.exp(-rate)
    for strike in strikes:
        put_value = max(strike * discount - 100.0, 0.0) + 5.0
        call_value = put_value + 100.0 - strike * discount + call_shift
        delta = max(0.05, min(0.95, 0.5 + (100.0 - strike) * 0.02))
        rows.append({"symbol": f"C{strike}", "right": "call", "strike": strike, "expiry": "2027-01-01", "delta": delta, "vega": 1.0,
                     "bid": call_value - half_spread, "ask": call_value + half_spread, "underlying_price": 100.0})
        rows.append({"symbol": f"P{strike}", "right": "put", "strike": strike, "expiry": "2027-01-01", "delta": delta - 1.0, "vega": 1.0,
                     "bid": put_value - half_spread, "ask": put_value + half_spread, "underlying_price": 100.0})
    return rows


NAMES = ("box_spread", "short_box_spread", "conversion", "reverse_conversion")
TODAY = date(2026, 1, 1)


def test_a_fair_priced_chain_is_no_arbitrage_for_any_structure():
    # the first Lean run on real quotes flagged all six at once: the detector compared absolute values, so a short box's
    # credit always looked like a mispricing of twice its notional
    for name in NAMES:
        assert select_arbitrage_signal(name, _parity_chain(), TODAY, 0.05, min_mispricing_bps=5.0) is False, name


def test_rich_calls_are_an_arbitrage_for_the_conversion_only():
    chain = _parity_chain(call_shift=2.0)
    assert select_arbitrage_signal("conversion", chain, TODAY, 0.05, min_mispricing_bps=5.0) is True
    assert select_arbitrage_signal("reverse_conversion", chain, TODAY, 0.05, min_mispricing_bps=5.0) is False


def test_cheap_calls_are_an_arbitrage_for_the_reverse_conversion_only():
    chain = _parity_chain(call_shift=-2.0)
    assert select_arbitrage_signal("reverse_conversion", chain, TODAY, 0.05, min_mispricing_bps=5.0) is True
    assert select_arbitrage_signal("conversion", chain, TODAY, 0.05, min_mispricing_bps=5.0) is False


def test_a_spread_wider_than_the_mispricing_is_no_arbitrage():
    chain = _parity_chain(call_shift=0.2, half_spread=1.0)
    assert select_arbitrage_signal("conversion", chain, TODAY, 0.05, min_mispricing_bps=5.0) is False


def test_executable_edge_is_one_sided():
    assert detect_executable_edge(1.0, 5.0, 100.0) is True
    assert detect_executable_edge(-1.0, 5.0, 100.0) is False
    assert detect_executable_edge(1.0, 5.0, 0.0) is False


# ---------------------------------------------------------------------------
# Fair-value formulas (textbook closed-form cross-checks)
# ---------------------------------------------------------------------------


def test_box_spread_fair_value_matches_discounted_payoff():
    fv = box_spread_fair_value(higher_strike=110, lower_strike=90, risk_free_rate=0.05, time_to_expiry_years=0.5)
    assert math.isclose(fv, 20.0 * math.exp(-0.05 * 0.5))


def test_box_spread_fair_value_zero_at_zero_time_to_expiry():
    assert box_spread_fair_value(110, 90, 0.05, 0.0) == 20.0


def test_conversion_parity_value_zero_when_priced_at_exact_parity():
    theoretical = 100.0 - 100.0 * math.exp(-0.05 * 1.0)
    discrepancy = conversion_parity_value(call_price=theoretical, put_price=0.0, spot=100.0, strike=100.0, risk_free_rate=0.05, time_to_expiry_years=1.0)
    assert abs(discrepancy) < 1e-9


def test_conversion_parity_value_nonzero_when_mispriced():
    discrepancy = conversion_parity_value(call_price=10.0, put_price=0.0, spot=100.0, strike=100.0, risk_free_rate=0.05, time_to_expiry_years=1.0)
    assert discrepancy != 0.0


def test_jelly_roll_fair_value_zero_when_expiries_are_identical():
    fv = jelly_roll_fair_value(strike=100.0, risk_free_rate=0.05, near_time_to_expiry_years=0.25, far_time_to_expiry_years=0.25)
    assert abs(fv) < 1e-9


def test_jelly_roll_fair_value_positive_for_normal_upward_discounting():
    fv = jelly_roll_fair_value(strike=100.0, risk_free_rate=0.05, near_time_to_expiry_years=0.25, far_time_to_expiry_years=0.75)
    assert fv > 0.0


# ---------------------------------------------------------------------------
# detect_mispricing threshold predicate
# ---------------------------------------------------------------------------


def test_detect_mispricing_below_threshold_returns_false():
    assert detect_mispricing(actual_net_cost=100.0, fair_value=100.05, min_mispricing_bps=15.0, notional=1000.0) is False


def test_detect_mispricing_above_threshold_returns_true():
    assert detect_mispricing(actual_net_cost=100.0, fair_value=102.0, min_mispricing_bps=15.0, notional=1000.0) is True


def test_detect_mispricing_non_positive_notional_returns_false():
    assert detect_mispricing(100.0, 200.0, min_mispricing_bps=1.0, notional=0.0) is False
    assert detect_mispricing(100.0, 200.0, min_mispricing_bps=1.0, notional=-10.0) is False


# ---------------------------------------------------------------------------
# select_arbitrage_signal - end-to-end per arbitrage family, using the
# real registry-driven selectors (roles resolved from
# MULTI_LEG_STRATEGY_REGISTRY, never hardcoded per strategy_name - the
# real bug this module's own _actual_net_cost()/role-resolution avoids).
# ---------------------------------------------------------------------------


def test_select_arbitrage_signal_box_spread_and_short_box_spread_both_resolve():
    chain = _sample_chain()
    today = date(2026, 7, 21)
    assert select_arbitrage_signal("box_spread", chain, today, 0.045, min_mispricing_bps=1.0) in (True, False)
    assert select_arbitrage_signal("short_box_spread", chain, today, 0.045, min_mispricing_bps=1.0) in (True, False)


def test_select_arbitrage_signal_conversion_and_reverse_conversion_both_resolve():
    chain = _sample_chain()
    today = date(2026, 7, 21)
    assert select_arbitrage_signal("conversion", chain, today, 0.045, min_mispricing_bps=1.0) in (True, False)
    assert select_arbitrage_signal("reverse_conversion", chain, today, 0.045, min_mispricing_bps=1.0) in (True, False)


def test_select_arbitrage_signal_jelly_roll_needs_two_expiries():
    single_expiry_chain = _sample_chain(("2026-08-21",))
    two_expiry_chain = _sample_chain(("2026-08-21", "2026-09-18"))
    today = date(2026, 7, 21)
    assert select_arbitrage_signal("jelly_roll", single_expiry_chain, today, 0.045, min_mispricing_bps=1.0) is False
    assert select_arbitrage_signal("jelly_roll", two_expiry_chain, today, 0.045, min_mispricing_bps=1.0) in (True, False)
    assert select_arbitrage_signal("short_jelly_roll", two_expiry_chain, today, 0.045, min_mispricing_bps=1.0) in (True, False)


def test_select_arbitrage_signal_huge_threshold_never_fires():
    chain = _sample_chain()
    today = date(2026, 7, 21)
    for name in ("box_spread", "short_box_spread", "conversion", "reverse_conversion"):
        assert select_arbitrage_signal(name, chain, today, 0.045, min_mispricing_bps=1_000_000.0) is False


def test_select_arbitrage_signal_none_current_date_returns_false():
    chain = _sample_chain()
    assert select_arbitrage_signal("box_spread", chain, None, 0.045, min_mispricing_bps=1.0) is False


def test_select_arbitrage_signal_unknown_strategy_name_returns_false():
    chain = _sample_chain()
    today = date(2026, 7, 21)
    assert select_arbitrage_signal("bull_call_spread", chain, today, 0.045, min_mispricing_bps=1.0) is False


# ---------------------------------------------------------------------------
# build_arbitrage_position_sizing
# ---------------------------------------------------------------------------


def test_build_arbitrage_position_sizing_sizes_when_mispriced():
    chain = _sample_chain()
    today = date(2026, 7, 21)
    decision = build_arbitrage_position_sizing("box_spread", chain, today, 0.045, min_mispricing_bps=1.0)
    assert decision is not None
    assert decision.contracts == 1
    assert decision.sizing_reason == "arbitrage_mispricing_fixed_size_sizing"
    assert decision.strategy_name == "box_spread"


def test_build_arbitrage_position_sizing_none_when_not_mispriced():
    chain = _sample_chain()
    today = date(2026, 7, 21)
    assert build_arbitrage_position_sizing("box_spread", chain, today, 0.045, min_mispricing_bps=1_000_000.0) is None


def test_build_arbitrage_position_sizing_respects_max_contracts_per_signal():
    chain = _sample_chain()
    today = date(2026, 7, 21)
    decision = build_arbitrage_position_sizing("box_spread", chain, today, 0.045, min_mispricing_bps=1.0, max_contracts_per_signal=3)
    assert decision is not None
    assert decision.contracts == 3


def test_build_arbitrage_position_sizing_non_positive_max_contracts_returns_none():
    chain = _sample_chain()
    today = date(2026, 7, 21)
    assert build_arbitrage_position_sizing("box_spread", chain, today, 0.045, min_mispricing_bps=1.0, max_contracts_per_signal=0) is None


def test_dividends_make_a_reverse_conversion_fair_on_a_dividend_payer():
    from portfolio.options_arbitrage_detector import pv_dividends_to_expiry

    expiry = "2024-07-19"
    today = date(2024, 1, 2)
    payments = [("2024-02-09", 2.0), ("2024-05-10", 2.0), ("2024-08-09", 2.0), ("2023-11-10", 2.0)]
    pv = pv_dividends_to_expiry(payments, today, expiry, 0.0)
    assert pv == pytest.approx(4.0), "only the dividends going ex before expiry"
    assert pv_dividends_to_expiry(None, today, expiry, 0.05) == 0.0
    assert pv_dividends_to_expiry([("bad", "x")], today, expiry, 0.05) == 0.0
    assert pv_dividends_to_expiry(payments, today, expiry, 0.05) < 4.0


def test_parity_accounts_for_dividends():
    assert conversion_parity_value(6.0, 10.0, 100.0, 100.0, 0.0, 0.5, pv_dividends=4.0) == pytest.approx(0.0)
    assert conversion_parity_value(6.0, 10.0, 100.0, 100.0, 0.0, 0.5) == pytest.approx(-4.0)
    assert conversion_parity_value(10.0, 6.0, 100.0, 100.0, 0.0, 0.5, pv_dividends=4.0) == pytest.approx(8.0)
