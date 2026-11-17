"""portfolio/book_construction.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

from portfolio.book_construction import should_rebalance_this_bar


def test_the_first_allocation_always_rebalances_and_then_bars_1_1_plus_n_and_so_on():
    assert should_rebalance_this_bar(0, 5, False) is True
    assert [should_rebalance_this_bar(index, 5, True) for index in range(1, 12)] == [True, False, False, False, False, True, False, False, False, False, True]
    assert should_rebalance_this_bar(1, 5, True, is_trading_day_bar=False) is False
    assert should_rebalance_this_bar(3, 5, True, phase_offset=2) is True


# --- lines the fast coverage gate runs only through this file (V6.6.9) -------------------------------------------------------------


def test_a_book_group_with_no_name_left_for_the_short_leg_or_no_long_name_says_why(monkeypatch):
    import portfolio.book_construction as bc

    why = {}
    assert bc._select_book_group({"A": 0.9, "B": 0.1}, 2, 1, 0.0, veto_reason_out=why) == {} and why["reason"] == "no_short_candidates"
    assert bc._select_book_group({"A": 0.9, "B": 0.1}, 2, 1, 0.0) == {}
    monkeypatch.setattr(bc, "_hysteresis_adjusted_selection", lambda *args: [])
    why = {}
    assert bc._select_book_group({"A": 0.9, "B": 0.1}, 1, 0, 0.0, veto_reason_out=why) == {} and why["reason"] == "no_long_candidates"
    assert bc._select_book_group({"A": 0.9, "B": 0.1}, 1, 0, 0.0) == {}


def test_non_numeric_inputs_degrade_to_no_weight_instead_of_raising():
    from portfolio.book_construction import _is_finite_number, _positive_cap, apply_book_weight_floor

    assert _is_finite_number("x") is False and _is_finite_number(None) is False and _is_finite_number(0.5) is True
    assert apply_book_weight_floor("not a weight", 0.1, 0.5) == 0.0
    assert _positive_cap({"cap": "abc"}, "cap") is None and _positive_cap({"cap": 0.2}, "cap") == 0.2
