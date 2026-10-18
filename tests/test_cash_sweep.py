"""portfolio/cash_sweep.py (V6.2.0): the T-bill sweep's size under the no-borrow and margin limits."""

from __future__ import annotations

import math

import pytest

from portfolio.cash_sweep import (
    advance_strategy_value,
    cash_sweep_target_weight,
    margin_fraction,
    resolve_cash_sweep_config,
    strategy_reserve,
    sweep_order_needed,
)

CONFIG = resolve_cash_sweep_config({"enabled": True})
NO_RESERVE = {"long": 0.0, "short": 0.0, "margin": 0.0}


def test_defaults_are_off_and_bad_numbers_fall_back():
    assert resolve_cash_sweep_config(None)["enabled"] is False
    assert resolve_cash_sweep_config({})["ticker"] == "BIL"
    bad = resolve_cash_sweep_config({"max_weight": 3.0, "margin_buffer": float("nan"), "ticker": "sgov"})
    assert bad["max_weight"] == 0.9 and bad["margin_buffer"] == 0.1 and bad["ticker"] == "SGOV"


def test_an_empty_book_with_nothing_to_reserve_holds_the_maximum():
    assert cash_sweep_target_weight(long_weight=0.0, short_weight=0.0, margin_used=0.0, reserve=NO_RESERVE, config=CONFIG) == 0.9


def test_the_no_borrow_limit_counts_short_proceeds_and_the_reserve():
    # long 0.5 / short 0.3 holds 0.8 cash; nothing reserved -> 1 - 0.5 + 0.3 - 0.02 = 0.78
    target = cash_sweep_target_weight(long_weight=0.5, short_weight=0.3, margin_used=0.4, reserve=NO_RESERVE, config=CONFIG)
    assert target == pytest.approx(0.78)
    reserve = {"long": 0.3, "short": 0.0, "margin": 0.0}
    assert cash_sweep_target_weight(long_weight=0.5, short_weight=0.3, margin_used=0.4, reserve=reserve,
                                    config=CONFIG) == pytest.approx(0.48)


def test_the_margin_limit_leaves_room_for_the_next_sessions_orders():
    # margin 0.27 held; a fresh book reserves 0.4, the legacy 0.05 at 1x, a 0.10 neutral sleeve 0.05:
    # 2 x (0.9 - 0.27 - 0.5) = 0.26
    reserve = strategy_reserve(rebalance_next=True, book_gross_cap=1.0, max_short_exposure=0.3, formed_long=0.0,
                               formed_short=0.0, book_long=0.0, book_short=0.0, other_budget_remaining=0.05,
                               neutral_budget=0.10)
    assert reserve == {"long": pytest.approx(0.6), "short": pytest.approx(0.35), "margin": pytest.approx(0.5)}
    target = cash_sweep_target_weight(long_weight=0.28, short_weight=0.26, margin_used=0.27, reserve=reserve, config=CONFIG)
    assert target == pytest.approx(0.26)
    # between rebalances only the formed book's unfilled part is reserved
    calm = strategy_reserve(rebalance_next=False, book_gross_cap=1.0, max_short_exposure=0.3, formed_long=0.3,
                            formed_short=0.3, book_long=0.28, book_short=0.26, other_budget_remaining=0.15)
    assert calm["long"] == pytest.approx(0.17) and calm["short"] == pytest.approx(0.04)
    assert cash_sweep_target_weight(long_weight=0.28, short_weight=0.26, margin_used=0.27, reserve=calm,
                                    config=CONFIG) > target


def test_margin_follows_leans_default_leverage_and_bad_inputs_give_no_sweep():
    assert margin_fraction([("equity", 0.4), ("crypto", -0.05), ("forex", 0.5)]) == pytest.approx(0.2 + 0.05 + 0.01)
    assert cash_sweep_target_weight(long_weight=math.nan, short_weight=0.0, margin_used=0.0, reserve=NO_RESERVE,
                                    config=CONFIG) == 0.0
    over = {"long": 2.0, "short": 0.0, "margin": 2.0}
    assert cash_sweep_target_weight(long_weight=0.0, short_weight=0.0, margin_used=0.0, reserve=over, config=CONFIG) == 0.0


def test_orders_only_for_real_moves_but_every_cut_and_the_risk_value():
    assert not sweep_order_needed(0.60, 0.63, 0.05)
    assert sweep_order_needed(0.60, 0.66, 0.05)
    assert sweep_order_needed(0.60, 0.59, 0.05)  # above target: always cut


def test_unfilled_short_proceeds_never_fund_the_sweep_beyond_the_longs_they_pair_with():
    # held long 0.2 / short 0.0; the formed book still owes 0.3 of shorts and nothing long
    reserve = {"long": 0.0, "short": 0.3, "margin": 0.15}
    target = cash_sweep_target_weight(long_weight=0.2, short_weight=0.0, margin_used=0.1, reserve=reserve, config=CONFIG)
    assert target == pytest.approx(1.0 - 0.2 - 0.02)


def test_the_risk_value_compounds_strategy_pnl_over_the_total_it_is_sized_on():
    state, value = advance_strategy_value(None, 100_000.0, 0.0)
    assert value == 100_000.0
    # +8k of carry, then the strategy loses 1% of the TOTAL (1,080 on 108k): the risk value falls exactly 1%,
    # where "total minus carry" (100k base) would have shown -1.08%
    state, value = advance_strategy_value(state, 108_000.0, 8_000.0)
    assert value == pytest.approx(100_000.0)
    state, value = advance_strategy_value(state, 106_920.0, 8_000.0)
    assert value == pytest.approx(99_000.0)
    # the sweep's own move never reaches it; a bad reading keeps the last value
    state, value = advance_strategy_value(state, 107_020.0, 8_100.0)
    assert value == pytest.approx(99_000.0)
    assert advance_strategy_value(state, math.nan, 8_100.0)[1] == pytest.approx(99_000.0)
    assert advance_strategy_value(None, 0.0, 0.0)[0] is None
