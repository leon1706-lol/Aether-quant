"""V5.5.0 backtest findings (Problems.md #133): fixes found by auditing the 2026-10-07 Lean run.

Round file - cross-module regressions committed together with their fix:
  * the cooldown exemption covers FORCED exits only (230 of 355 trades closed within 2 days),
  * a position the book opened is held through a gate veto,
  * no second order is stacked on one already working (26 market+limit pairs, several both filled),
  * the liquidity gate's spread input is capped per asset class (all crypto / 126 of 179 forex selections blocked).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from execution import should_skip_for_open_order
from execution.order_gate import is_real_order_placement
from liquidity import build_liquidity_decision, cap_spread_proxy
from portfolio import should_hold_owned_position_on_veto
from risk_controls import compute_position_exit_tracking_update, evaluate_non_model_exit, is_cooldown_exempt

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- cooldown


def test_only_forced_exits_skip_the_cooldown():
    assert is_cooldown_exempt("sell", True, is_forced_exit=True) is True
    assert is_cooldown_exempt("sell", True, is_forced_exit=False) is False
    assert is_cooldown_exempt("sell", True) is False
    assert is_cooldown_exempt("sell", False, is_forced_exit=True) is False
    assert is_cooldown_exempt("buy", True, is_forced_exit=True) is False


# ---------------------------------------------------------------- hold through a veto


def test_owned_position_is_held_only_while_the_book_is_vetoed():
    held = dict(enabled=True, is_book_member=False, is_book_owned=True, is_currently_invested=True, book_is_active=False)
    assert should_hold_owned_position_on_veto(**held) is True
    assert should_hold_owned_position_on_veto(**{**held, "enabled": False}) is False  # off = pre-V5.5.0
    assert should_hold_owned_position_on_veto(**{**held, "book_is_active": True}) is False  # rotation exit decides
    assert should_hold_owned_position_on_veto(**{**held, "is_book_owned": False}) is False  # sleeve names stay legacy
    assert should_hold_owned_position_on_veto(**{**held, "is_currently_invested": False}) is False
    assert should_hold_owned_position_on_veto(**{**held, "is_book_member": True}) is False


# ---------------------------------------------------------------- never stack orders


def test_untracked_open_order_blocks_a_second_entry():
    assert should_skip_for_open_order(-26.0, has_tracked_pending_limit=False) is True
    assert should_skip_for_open_order(40.0, has_tracked_pending_limit=False) is True


def test_tracked_limit_order_is_left_to_the_pending_order_policy():
    assert should_skip_for_open_order(-26.0, has_tracked_pending_limit=True) is False


def test_nothing_open_or_garbage_quantity_never_blocks():
    assert should_skip_for_open_order(0.0, False) is False
    assert should_skip_for_open_order(float("nan"), False) is False
    assert should_skip_for_open_order(float("inf"), False) is False
    assert should_skip_for_open_order("x", False) is False
    assert should_skip_for_open_order(None, False) is False


def test_order_already_open_is_not_audited_as_a_placement():
    assert is_real_order_placement("order_already_open", True) is False


# ---------------------------------------------------------------- spread cap


def test_spread_cap_clamps_only_configured_classes():
    caps = {"crypto": 0.001, "forex": 0.0003}
    assert cap_spread_proxy(0.0131, "crypto", caps) == 0.001
    assert cap_spread_proxy(0.0035, "forex", caps) == 0.0003
    assert cap_spread_proxy(0.0005, "crypto", caps) == 0.0005  # below the cap: untouched
    assert cap_spread_proxy(0.0131, "equity", caps) == 0.0131  # no cap for the class


def test_spread_cap_defaults_to_a_noop_and_survives_garbage():
    assert cap_spread_proxy(0.0131, "crypto", None) == 0.0131
    assert cap_spread_proxy(0.0131, "crypto", {}) == 0.0131
    assert cap_spread_proxy(None, "crypto", {"crypto": 0.001}) is None
    assert cap_spread_proxy(0.0131, "crypto", {"crypto": "x"}) == 0.0131
    assert cap_spread_proxy(0.0131, "crypto", {"crypto": float("nan")}) == 0.0131
    assert cap_spread_proxy(0.0131, "crypto", {"crypto": -1.0}) == 0.0131
    assert cap_spread_proxy(float("nan"), "crypto", {"crypto": 0.001}) != 0.001  # not-finite passes through


def test_capped_spread_lets_a_crypto_book_name_through_the_cost_gate():
    """BTCUSD on 2021-04-01: a 1.3% high-low 'spread' tripped the 0.25% round-trip ceiling."""
    kwargs = dict(
        close=58000.0, volume=0.0, target_weight=0.02, portfolio_value=100_000.0, annualized_volatility=0.7,
        security_type="crypto", max_round_trip_cost_fraction=0.0025, zero_volume_fallback_ddv=1e9,
    )
    raw = build_liquidity_decision(dynamic_spread=0.0131, **kwargs)
    capped = build_liquidity_decision(dynamic_spread=cap_spread_proxy(0.0131, "crypto", {"crypto": 0.001}), **kwargs)
    assert raw.recommended_action == "block"
    assert capped.recommended_action == "allow"


# ---------------------------------------------------------------- stale exit-tracking state (#134)


def _update(**kwargs):
    base = dict(
        was_invested=False, is_invested=False, close_price=100.0, signal_name="hold", peak_price_since_entry=None,
        direction=None, bar_index=100,
    )
    return compute_position_exit_tracking_update(**{**base, **kwargs})


def test_flat_symbol_with_leftover_entry_state_is_cleared_only_when_asked():
    assert _update(has_entry_state=True, clear_stale_state=True) == {"action": "clear"}
    assert _update(has_entry_state=True) == {"action": "noop"}  # pre-fix default unchanged
    assert _update(has_entry_state=False, clear_stale_state=True) == {"action": "noop"}


def test_clear_stale_state_does_not_touch_held_or_entering_positions():
    assert _update(was_invested=True, is_invested=True, has_entry_state=True, clear_stale_state=True,
                   direction="long", peak_price_since_entry=95.0)["action"] == "hold"
    assert _update(is_invested=True, clear_stale_state=True, has_entry_state=True)["action"] == "enter"


def test_lifecycle_second_holding_is_not_force_exited_after_a_stale_state():
    """Replays the 2026-10-07 failure: holding 1 closed at bar 30 (fill seen a bar late), re-entry seen at bar 100."""
    state: dict = {"entry": 5, "peak": 50.0, "direction": "short"}
    cleared = _update(has_entry_state=True, clear_stale_state=True, bar_index=31)
    assert cleared["action"] == "clear"
    state.clear()
    entered = _update(was_invested=True, is_invested=True, has_entry_state=False, bar_index=100, signal_name="short",
                      held_quantity=-10.0, average_entry_price=100.0)
    assert entered["action"] == "enter" and entered["entry_bar_index"] == 100 and entered["direction"] == "short"
    assert evaluate_non_model_exit(101, True, 20, 0.15, entered["entry_bar_index"], entered["peak_price_since_entry"],
                                   entered["direction"], 100.0) is None
    # the bug: stale bar-5 state fires max-holding on the very next bar
    assert evaluate_non_model_exit(101, True, 20, 0.15, 5, 50.0, "short", 100.0) == "max_holding_age_exceeded"


# ---------------------------------------------------------------- wiring


def test_main_wires_the_findings_fixes_and_the_config_ships_them():
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    called = {
        node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    for name in ("should_hold_owned_position_on_veto", "should_skip_for_open_order", "cap_spread_proxy", "is_cooldown_exempt"):
        assert name in called, f"main.py no longer calls {name}"
    assert "is_forced_exit" in (ROOT / "main.py").read_text(encoding="utf-8")
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["phase_v2"]
    assert config["portfolio_book"]["hold_owned_positions_on_veto"] is True
    assert set(config["liquidity"]["max_spread_proxy_by_type"]) == {"crypto", "forex", "equity"}  # equity: V5.6.0, Problems #143
