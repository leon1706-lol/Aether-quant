"""portfolio/book_construction.py (V6.6.7: its own test file, the convention in tests/README.md; the deeper cases live in the round files)."""

from __future__ import annotations

from portfolio.book_construction import should_rebalance_this_bar


def test_the_first_allocation_always_rebalances_and_then_bars_1_1_plus_n_and_so_on():
    assert should_rebalance_this_bar(0, 5, False) is True
    assert [should_rebalance_this_bar(index, 5, True) for index in range(1, 12)] == [True, False, False, False, False, True, False, False, False, False, True]
    assert should_rebalance_this_bar(1, 5, True, is_trading_day_bar=False) is False
    assert should_rebalance_this_bar(3, 5, True, phase_offset=2) is True
