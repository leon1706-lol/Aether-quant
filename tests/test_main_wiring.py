"""Wiring tests for main.py's V5.5.0 fixes, run against a MINIMAL Lean stub.

main.py cannot be imported normally - `from AlgorithmImports import *` only
resolves inside a Lean process - so it has had zero unit coverage by design
and every fix was verified only by a pure-function test plus a structural
"main.py still calls it" guard. This closes the remaining gap for the methods
that matter: a stub `AlgorithmImports` exposing just `QCAlgorithm` lets
main.py import, and an instance built with `object.__new__` (skipping
`initialize()`) gets only the attributes each method reads. That is enough to
drive `_apply_signal`, `_try_submit_limit_order`, `_open_order_quantity`,
`_short_exposure`, `_update_position_exit_tracking`, `_track_slippage_divergence`
and `on_end_of_algorithm` end to end - the order-path bugs of Problems.md #128.

It is NOT a Lean simulator: nothing here proves fill timing or Lean API
semantics (that stays the owner-run backtest's job). It proves the decisions
this repo makes around those APIs are the ones its pure functions promise.

Conventions match the rest of this repo: no test classes, module-level helpers.
"""

from __future__ import annotations

import datetime
import sys
import types
from types import SimpleNamespace

import pytest


@pytest.fixture(scope="module")
def main_module():
    stub = types.ModuleType("AlgorithmImports")
    stub.QCAlgorithm = type("QCAlgorithm", (), {})
    stub.time = datetime.time  # Lean's star import exports this and SHADOWS the stdlib `time` module (V5.5.0 bar-1 crash)
    patcher = pytest.MonkeyPatch()
    patcher.setitem(sys.modules, "AlgorithmImports", stub)
    patcher.delitem(sys.modules, "main", raising=False)
    import main  # noqa: PLC0415 - must happen after the stub is installed

    yield main
    sys.modules.pop("main", None)
    patcher.undo()


class _Portfolio:
    """Just enough of Lean's SecurityPortfolioManager."""

    def __init__(self, holdings: dict | None = None, total: float = 100_000.0):
        self._holdings = holdings or {}
        self.TotalPortfolioValue = total
        self.Values = list(self._holdings.values())

    def __getitem__(self, symbol):
        return self._holdings.get(str(symbol), SimpleNamespace(Quantity=0.0, HoldingsValue=0.0, AveragePrice=0.0, Invested=False))


def _holding(symbol, quantity, value=0.0, average_price=0.0):
    return SimpleNamespace(
        Symbol=symbol, Quantity=quantity, HoldingsValue=value, AveragePrice=average_price, Invested=quantity != 0
    )


def _algorithm(main_module, **overrides):
    algorithm = object.__new__(main_module.AetherQuantAlgorithm)
    defaults = dict(
        bar_index=100,
        trade_cooldown_bars=10,
        latest_signal_state={},
        last_trade_bar_by_symbol={},
        asset_lookup={"EURUSD": {"asset_class": "forex", "security_type": "forex"}, "AMZN": {"asset_class": "equity", "security_type": "equity"}},
        max_active_positions=100,
        max_equity_exposure=0.65,
        max_short_exposure=0.30,
        max_forex_short_exposure=0.15,
        exposure_caps_by_asset_class={"forex": 0.15, "equity": 0.65},
        position_scaling_enabled=True,
        position_scaling_rebalance_threshold_weight=0.01,
        forex_resize_min_fraction=0.0,
        limit_orders_enabled=True,
        limit_orders_asset_classes={"equity"},
        limit_order_offset_multiplier=1.0,
        limit_order_unfilled_timeout_bars=3,
        pending_limit_orders={},
        latest_liquidity_by_symbol={},
        _pending_entries_this_bar=set(),
        _simulated_portfolio=None,
        Portfolio=_Portfolio(),
        Transactions=SimpleNamespace(GetOpenOrderTickets=lambda symbol: []),
    )
    defaults.update(overrides)
    for name, value in defaults.items():
        setattr(algorithm, name, value)
    algorithm.market_orders = []
    algorithm.liquidated = []
    algorithm.debug_lines = []
    algorithm._order_permission = lambda: (True, "ok")
    algorithm._is_invested = lambda symbol, orders_allowed: str(symbol) in algorithm.Portfolio._holdings
    algorithm._active_position_count = lambda *a, **k: 0
    algorithm._asset_class_exposure = lambda *a, **k: 0.0
    algorithm._short_exposure = lambda *a, **k: 0.0
    algorithm._forex_order_units_for_weight = lambda weight, price, allowed: 1000 if weight >= 0 else -1000
    algorithm._log_forex_order_sizing_diagnostic = lambda *a, **k: None
    algorithm._liquidate_position = lambda symbol: algorithm.liquidated.append(str(symbol))
    algorithm.MarketOrder = lambda symbol, quantity: algorithm.market_orders.append((str(symbol), quantity))
    algorithm.Debug = lambda message: algorithm.debug_lines.append(str(message))
    for name, value in overrides.items():
        setattr(algorithm, name, value)
    return algorithm


# ---------------------------------------------------------------- forex: pending-aware, rebalance-gated, capped


def _forex(algorithm, signal="buy", weight=0.05, **kwargs):
    return algorithm._apply_signal("EURUSD", signal, weight, 1.1, {}, **kwargs)


def test_forex_order_in_flight_on_the_equity_tick_is_not_stacked_on_the_forex_tick(main_module):
    """The 60%-short bug: held quantity is 0 until the order fills, so held-only sizing re-submitted
    the whole target on the second tick of the same day."""
    pending = SimpleNamespace(QuantityRemaining=1000.0)
    algorithm = _algorithm(main_module, Transactions=SimpleNamespace(GetOpenOrderTickets=lambda symbol: [pending]))
    assert _forex(algorithm) == "order_already_open"  # the generic in-flight guard (#133) fires before forex sizing
    assert algorithm.market_orders == []


def test_forex_enters_when_nothing_is_held_or_in_flight(main_module):
    algorithm = _algorithm(main_module)
    assert _forex(algorithm) == "entered_long_forex"
    assert algorithm.market_orders == [("EURUSD", 1000)]


def test_forex_resize_of_a_book_member_waits_for_the_rebalance_bar(main_module):
    held = _Portfolio({"EURUSD": _holding("EURUSD", 500.0, value=550.0)})
    algorithm = _algorithm(main_module, Portfolio=held)
    assert _forex(algorithm, is_book_selected=True, is_rebalance_bar=False) == "kept_long_forex"
    assert algorithm.market_orders == []
    assert _forex(algorithm, is_book_selected=True, is_rebalance_bar=True) == "scaled_long_forex"
    assert algorithm.market_orders == [("EURUSD", 500)]  # on the rebalance bar the same resize goes through


def test_forex_resize_of_a_non_book_symbol_is_ungated_as_before(main_module):
    held = _Portfolio({"EURUSD": _holding("EURUSD", 500.0, value=550.0)})
    algorithm = _algorithm(main_module, Portfolio=held)
    _forex(algorithm, is_book_selected=False, is_rebalance_bar=False)
    assert algorithm.market_orders == [("EURUSD", 500)]  # delta toward the 1000-unit target


def test_forex_resize_deadband_suppresses_dust_orders(main_module):
    held = _Portfolio({"EURUSD": _holding("EURUSD", 950.0, value=1045.0)})
    algorithm = _algorithm(main_module, Portfolio=held, forex_resize_min_fraction=0.10)
    assert _forex(algorithm) == "forex_resize_deadband_kept"
    assert algorithm.market_orders == []
    algorithm_off = _algorithm(main_module, Portfolio=held, forex_resize_min_fraction=0.0)
    _forex(algorithm_off)
    assert algorithm_off.market_orders == [("EURUSD", 50)]  # default 0.0 = the pre-V5.5.0 behavior


def test_forex_shorts_have_their_own_budget(main_module):
    seen = {}

    def short_exposure(allowed, exclude_symbol=None, asset_class=None):
        seen.setdefault("calls", []).append(asset_class)
        return 0.15 if asset_class == "forex" else 0.0

    algorithm = _algorithm(main_module, _short_exposure=short_exposure)
    assert _forex(algorithm, signal="short", weight=-0.05) == "forex_short_exposure_cap_reached"
    assert "forex" in seen["calls"]
    assert algorithm.market_orders == []


def test_forex_short_inside_its_budget_still_trades(main_module):
    algorithm = _algorithm(main_module, _short_exposure=lambda allowed, exclude_symbol=None, asset_class=None: 0.01)
    note = _forex(algorithm, signal="short", weight=-0.05)
    assert note == "entered_short_forex"
    assert algorithm.market_orders == [("EURUSD", -1000)]


def test_short_exposure_can_be_filtered_to_one_asset_class(main_module):
    holdings = {
        "EURUSD": _holding("EURUSD", -1000.0, value=-12_000.0),
        "AMZN": _holding("AMZN", -10.0, value=-8_000.0),
        "AUDUSD": _holding("AUDUSD", 500.0, value=3_000.0),
    }
    algorithm = _algorithm(
        main_module,
        Portfolio=_Portfolio(holdings),
        asset_lookup={
            "EURUSD": {"asset_class": "forex"}, "AMZN": {"asset_class": "equity"}, "AUDUSD": {"asset_class": "forex"},
        },
    )
    del algorithm._short_exposure  # drop the instance stub so the real method runs
    assert algorithm._short_exposure(True) == pytest.approx(0.20)  # every short, all classes
    assert algorithm._short_exposure(True, asset_class="forex") == pytest.approx(0.12)  # only the forex short
    assert algorithm._short_exposure(True, asset_class="crypto") == 0.0
    assert algorithm._short_exposure(True, exclude_symbol="EURUSD", asset_class="forex") == 0.0


def test_open_order_quantity_sums_signed_remaining_quantity_and_never_raises(main_module):
    tickets = [SimpleNamespace(QuantityRemaining=5.0), SimpleNamespace(QuantityRemaining=-2.0)]
    algorithm = _algorithm(main_module, Transactions=SimpleNamespace(GetOpenOrderTickets=lambda symbol: tickets))
    assert algorithm._open_order_quantity("X") == 3.0

    def explode(symbol):
        raise RuntimeError("lean api changed")

    broken = _algorithm(main_module, Transactions=SimpleNamespace(GetOpenOrderTickets=explode))
    assert broken._open_order_quantity("X") == 0.0
    assert _algorithm(main_module, Transactions=SimpleNamespace())._open_order_quantity("X") == 0.0


# ---------------------------------------------------------------- cooldown applies to entries, never to exits


def test_a_forced_exit_is_not_blocked_by_the_trade_cooldown(main_module):
    held = _Portfolio({"AMZN": _holding("AMZN", 10.0, value=1000.0)})
    algorithm = _algorithm(
        main_module, Portfolio=held,
        latest_signal_state={"AMZN": "buy"}, last_trade_bar_by_symbol={"AMZN": 98},  # 2 bars ago, inside the 10-bar cooldown
    )
    assert algorithm._apply_signal("AMZN", "sell", 0.0, 100.0, is_forced_exit=True) == "liquidated_on_sell"
    assert algorithm.liquidated == ["AMZN"]


def test_a_plain_legacy_sell_signal_is_still_rate_limited_by_the_cooldown(main_module):
    """#133: exempting every sell let the legacy signal flip positions out within a day (230 of 355 trades)."""
    held = _Portfolio({"AMZN": _holding("AMZN", 10.0, value=1000.0)})
    algorithm = _algorithm(
        main_module, Portfolio=held, latest_signal_state={"AMZN": "buy"}, last_trade_bar_by_symbol={"AMZN": 98}
    )
    assert algorithm._apply_signal("AMZN", "sell", 0.0, 100.0) == "cooldown_active"
    assert algorithm.liquidated == []


def test_an_entry_is_still_blocked_by_the_trade_cooldown(main_module):
    algorithm = _algorithm(
        main_module, latest_signal_state={"AMZN": "sell"}, last_trade_bar_by_symbol={"AMZN": 98}
    )
    assert algorithm._apply_signal("AMZN", "buy", 0.05, 100.0) == "cooldown_active"


def test_selling_a_symbol_that_is_not_held_still_respects_the_cooldown(main_module):
    """Exempt means 'exit of an OPEN position' - a sell signal on a flat symbol is not an exit."""
    algorithm = _algorithm(main_module, latest_signal_state={"AMZN": "buy"}, last_trade_bar_by_symbol={"AMZN": 98})
    assert algorithm._apply_signal("AMZN", "sell", 0.0, 100.0) == "cooldown_active"


# ---------------------------------------------------------------- one pending limit order per symbol


def _limit_algorithm(main_module, **overrides):
    submitted, cancelled = [], []

    def make_ticket(symbol, quantity, price):
        ticket = SimpleNamespace(Cancel=lambda: cancelled.append(len(submitted)), QuantityRemaining=quantity)
        submitted.append((str(symbol), quantity, price))
        return ticket

    algorithm = _algorithm(
        main_module, LimitOrder=make_ticket, CalculateOrderQuantity=lambda symbol, weight: 10, **overrides
    )
    algorithm.submitted, algorithm.cancelled = submitted, cancelled
    return algorithm


def _place(algorithm, is_buy=True):
    return algorithm._try_submit_limit_order("AMZN", "AMZN", "equity", is_buy=is_buy, target_weight=0.05, close_price=100.0)


def test_a_second_buy_on_a_symbol_with_an_order_in_flight_is_not_submitted(main_module):
    """The AMZN bug: 3 limit orders, 689 shares, ~3x target - each bar re-submitted and overwrote the record."""
    algorithm = _limit_algorithm(main_module)
    assert _place(algorithm) is True
    for bar in (101, 102):
        algorithm.bar_index = bar
        assert _place(algorithm) is True  # reports "an order is working" without sending another
    assert len(algorithm.submitted) == 1
    assert algorithm.pending_limit_orders["AMZN"]["submitted_bar"] == 100  # the clock was NOT reset


def test_a_kept_order_is_flagged_so_the_audit_log_does_not_record_a_placement(main_module):
    algorithm = _limit_algorithm(main_module, _limit_order_kept_flag=False)
    _place(algorithm)
    assert algorithm._limit_order_kept_flag is False  # a genuinely new order is not "kept"
    algorithm.bar_index = 101
    _place(algorithm)
    assert algorithm._limit_order_kept_flag is True


def test_an_order_past_its_timeout_is_cancelled_and_replaced(main_module):
    algorithm = _limit_algorithm(main_module)
    _place(algorithm)
    algorithm.bar_index = 103  # 3 bars on = timeout
    assert _place(algorithm) is True
    assert len(algorithm.submitted) == 2 and algorithm.cancelled == [1]
    assert algorithm.pending_limit_orders["AMZN"]["submitted_bar"] == 103


def test_an_opposite_direction_order_cancels_the_old_one_first(main_module):
    algorithm = _limit_algorithm(main_module)
    _place(algorithm, is_buy=True)
    algorithm.bar_index = 101
    assert _place(algorithm, is_buy=False) is True
    assert len(algorithm.submitted) == 2 and algorithm.cancelled == [1]
    assert algorithm.pending_limit_orders["AMZN"]["direction"] == "sell"


def test_limit_orders_stay_off_for_asset_classes_not_configured(main_module):
    algorithm = _limit_algorithm(main_module)
    assert algorithm._try_submit_limit_order("EURUSD", "EURUSD", "forex", is_buy=True, target_weight=0.05, close_price=1.1) is False
    assert algorithm.submitted == []


# ---------------------------------------------------------------- exit tracking adopts fills that land a bar late


def _tracking_algorithm(main_module, holding):
    return _algorithm(
        main_module,
        Portfolio=_Portfolio({"AMZN": holding}),
        _position_entry_bar_index={}, _position_entry_price={},
        _position_peak_price_since_entry={}, _position_direction_by_symbol={},
    )


def test_a_short_that_filled_a_bar_late_is_adopted_with_the_right_direction(main_module):
    algorithm = _tracking_algorithm(main_module, _holding("AMZN", -10.0, value=-1000.0, average_price=100.0))
    algorithm._update_position_exit_tracking("AMZN", True, True, 101.0, "hold", symbol="AMZN")
    assert algorithm._position_direction_by_symbol == {"AMZN": "short"}
    assert algorithm._position_entry_bar_index == {"AMZN": 100}
    assert algorithm._position_entry_price == {"AMZN": 100.0}


def test_an_already_tracked_position_just_updates_its_peak(main_module):
    algorithm = _tracking_algorithm(main_module, _holding("AMZN", 10.0, value=1000.0, average_price=100.0))
    algorithm._position_entry_bar_index["AMZN"] = 90
    algorithm._position_peak_price_since_entry["AMZN"] = 100.0
    algorithm._position_direction_by_symbol["AMZN"] = "long"
    algorithm._update_position_exit_tracking("AMZN", True, True, 110.0, "buy", symbol="AMZN")
    assert algorithm._position_entry_bar_index["AMZN"] == 90  # not re-adopted
    assert algorithm._position_peak_price_since_entry["AMZN"] == 110.0


def test_a_flat_symbol_with_no_state_stays_untracked(main_module):
    algorithm = _tracking_algorithm(main_module, _holding("AMZN", 0.0))
    algorithm._update_position_exit_tracking("AMZN", False, False, 100.0, "hold", symbol="AMZN")
    assert algorithm._position_entry_bar_index == {}


def test_a_closed_positions_stale_entry_state_is_cleared_when_the_symbol_is_flat(main_module):
    """#134: the closing fill lands a bar late, so was_invested is already False when the flat symbol is seen."""
    algorithm = _tracking_algorithm(main_module, _holding("AMZN", 0.0))
    algorithm._position_entry_bar_index["AMZN"] = 40
    algorithm._position_entry_price["AMZN"] = 100.0
    algorithm._position_peak_price_since_entry["AMZN"] = 90.0
    algorithm._position_direction_by_symbol["AMZN"] = "short"
    algorithm._update_position_exit_tracking("AMZN", False, False, 100.0, "hold", symbol="AMZN")
    assert algorithm._position_entry_bar_index == {}
    assert algorithm._position_peak_price_since_entry == {}
    assert algorithm._position_direction_by_symbol == {}


def test_a_re_entry_is_adopted_fresh_and_not_force_exited_the_next_day(main_module):
    algorithm = _tracking_algorithm(main_module, _holding("AMZN", -10.0, value=-1000.0, average_price=100.0))
    algorithm.exits_enabled = True
    algorithm.exits_max_holding_bars = 20
    algorithm.exits_trailing_stop_pct = 0.15
    # first holding: entered at bar 5, closed, the closing fill observed flat at bar 30
    algorithm._position_entry_bar_index["AMZN"] = 5
    algorithm._position_peak_price_since_entry["AMZN"] = 50.0
    algorithm._position_direction_by_symbol["AMZN"] = "short"
    algorithm.Portfolio = _Portfolio({})
    algorithm._update_position_exit_tracking("AMZN", False, False, 100.0, "hold", symbol="AMZN")
    # second holding fills a bar after its order: first seen invested at bar 100
    algorithm.Portfolio = _Portfolio({"AMZN": _holding("AMZN", -10.0, value=-1000.0, average_price=100.0)})
    algorithm._update_position_exit_tracking("AMZN", True, True, 100.0, "hold", symbol="AMZN")
    assert algorithm._position_entry_bar_index == {"AMZN": 100}
    assert algorithm._check_non_model_exit("AMZN", 100.0) is None


# ---------------------------------------------------------------- slippage divergence vs the fill bar's open


def _fill_event(price, status="Filled", symbol="AMZN"):
    return SimpleNamespace(Status=SimpleNamespace(name=status), Symbol=symbol, FillPrice=price)


def _divergence_algorithm(main_module, open_price):
    return _algorithm(
        main_module,
        _expected_cost_by_symbol={"AMZN": {"expected_cost_bps": 10.0, "reference_price": 95.0}},
        Securities={"AMZN": SimpleNamespace(Open=open_price)},
        symbol_key_by_option_contract_symbol={},
        _slippage_divergence_history=[],
    )


def test_divergence_is_measured_against_the_fill_bar_open_not_the_prior_close(main_module):
    algorithm = _divergence_algorithm(main_module, open_price=100.0)
    algorithm._track_slippage_divergence(_fill_event(100.10))  # 10 bps over the open
    # one side vs HALF the 10 bps round trip -> 10 - 5. Against the stale 95.0 close it would read ~537 bps.
    assert algorithm._slippage_divergence_history == [pytest.approx(5.0, abs=1e-6)]


def test_divergence_records_nothing_when_the_open_is_unavailable(main_module):
    algorithm = _divergence_algorithm(main_module, open_price=0.0)
    algorithm._track_slippage_divergence(_fill_event(100.10))
    assert algorithm._slippage_divergence_history == []
    broken = _divergence_algorithm(main_module, open_price=100.0)
    broken.Securities = {}  # KeyError inside the guarded read
    broken._track_slippage_divergence(_fill_event(100.10))
    assert broken._slippage_divergence_history == []


def test_only_a_full_fill_counts(main_module):
    algorithm = _divergence_algorithm(main_module, open_price=100.0)
    algorithm._track_slippage_divergence(_fill_event(100.10, status="PartiallyFilled"))
    assert algorithm._slippage_divergence_history == []
    assert "AMZN" in algorithm._expected_cost_by_symbol  # left for the completing fill


# ---------------------------------------------------------------- teardown probe and cleanup experiment


def _teardown_algorithm(main_module, *, cleanup, timing):
    from performance_probe import TimingProbe

    probe = TimingProbe(timing)
    probe.stop("inference_cluster", probe.start())
    algorithm = _algorithm(
        main_module,
        _inference_pool=None,
        _sequence_predictions_served=7,
        _multitask_fallback_count=0,
        _timing_probe=probe,
        teardown_cleanup_enabled=cleanup,
        symbol_windows={"AMZN": [1, 2]}, symbol_long_windows={"AMZN": [1]}, symbol_treasury_10yr_history={"AMZN": [1]},
        symbol_sensitivity_driver_history={"AMZN": {}}, symbol_feature_history={"AMZN": [1]},
        option_positions_by_symbol={"X": []}, symbol_key_by_option_contract_symbol={"X": "Y"},
    )
    algorithm._ensure_ready = lambda: None
    algorithm._write_state = lambda **kwargs: None
    algorithm.last_trade_bar_by_symbol = {"AMZN": 1}
    algorithm.pending_limit_orders = {"AMZN": {}}
    algorithm.latest_signal_state = {"AMZN": "buy"}
    return algorithm


def test_teardown_reports_native_diagnostics_and_the_timing_line(main_module):
    algorithm = _teardown_algorithm(main_module, cleanup=False, timing=True)
    algorithm.on_end_of_algorithm()
    text = "\n".join(algorithm.debug_lines)
    assert "shutdown-probe: alive_threads=" in text
    assert "prediction-provenance: sequence_served=7" in text
    assert "teardown-probe:" in text and "gc_tracked_objects" in text
    assert "timing-probe: inference_cluster=calls:1" in text
    assert "teardown-cleanup" not in text
    assert algorithm.symbol_windows == {"AMZN": [1, 2]}  # nothing cleared unless opted in


def test_teardown_cleanup_is_opt_in_and_clears_the_symbol_containers(main_module):
    algorithm = _teardown_algorithm(main_module, cleanup=True, timing=False)
    algorithm.on_end_of_algorithm()
    text = "\n".join(algorithm.debug_lines)
    assert "teardown-cleanup: {'cleared': 10" in text
    assert algorithm.symbol_windows == {} and algorithm.pending_limit_orders == {} and algorithm.latest_signal_state == {}
    assert "timing-probe" not in text  # a disabled probe stays silent


def test_a_failing_probe_never_breaks_the_shutdown(main_module):
    algorithm = _teardown_algorithm(main_module, cleanup=True, timing=True)
    algorithm._timing_probe = None  # format_line() on None raises inside the guarded block
    algorithm.on_end_of_algorithm()  # must not raise
    assert any("failed (non-fatal)" in line for line in algorithm.debug_lines)
