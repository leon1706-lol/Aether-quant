"""Tests for portfolio/legacy_sleeve.py (V5.5.0, Problems.md #128): the capped
budget around the old probability-up signal that used to trade unbounded
alongside the rank book. Conventions match the rest of this repo: no test
classes, module-level helpers, plain dicts."""

import math

from portfolio.legacy_sleeve import (
    DEFAULT_LEGACY_SLEEVE_CONFIG,
    apply_legacy_sleeve_policy,
    compute_sleeve_gross_used,
    resolve_legacy_sleeve_config,
)

CONFIG = {"enabled": True, "max_gross_exposure": 0.10, "max_weight_per_name": 0.02, "trade_when_book_vetoed": False}


def _apply(signal="buy", weight=0.08, member=False, invested=False, book_active=True, used=0.0, config=CONFIG):
    return apply_legacy_sleeve_policy(signal, weight, member, invested, book_active, used, config)


def test_default_config_is_disabled_so_old_behavior_is_unchanged():
    assert DEFAULT_LEGACY_SLEEVE_CONFIG["enabled"] is False
    result = apply_legacy_sleeve_policy("buy", 0.08, False, False, True, 0.0, resolve_legacy_sleeve_config(None))
    assert result["signal"] == "buy"
    assert result["target_weight"] == 0.08
    assert result["reason"] == "legacy_sleeve_not_applicable"


def test_resolve_config_ignores_malformed_values():
    config = resolve_legacy_sleeve_config(
        {"enabled": True, "max_gross_exposure": "nope", "max_weight_per_name": -1, "trade_when_book_vetoed": 1}
    )
    assert config["enabled"] is True
    assert config["max_gross_exposure"] == DEFAULT_LEGACY_SLEEVE_CONFIG["max_gross_exposure"]
    assert config["max_weight_per_name"] == DEFAULT_LEGACY_SLEEVE_CONFIG["max_weight_per_name"]
    assert config["trade_when_book_vetoed"] is True
    assert resolve_legacy_sleeve_config("garbage") == DEFAULT_LEGACY_SLEEVE_CONFIG


def test_entry_is_capped_to_per_name_weight():
    result = _apply(weight=0.08)
    assert result["signal"] == "buy"
    assert result["target_weight"] == 0.02
    assert result["reason"] == "legacy_sleeve_capped"
    assert math.isclose(result["sleeve_gross_used"], 0.02)


def test_short_entry_keeps_its_sign():
    result = _apply(signal="short", weight=-0.08)
    assert result["target_weight"] == -0.02


def test_small_entry_within_budget_is_untouched():
    result = _apply(weight=0.015)
    assert result["target_weight"] == 0.015
    assert result["reason"] == "legacy_sleeve_within_budget"


def test_budget_is_atomic_across_symbols_and_exhausts():
    used = 0.0
    admitted = 0
    for _ in range(20):
        result = _apply(weight=0.08, used=used)
        used = result["sleeve_gross_used"]
        admitted += result["signal"] == "buy"
    assert admitted == 5  # 5 x 0.02 == the 0.10 gross budget
    assert math.isclose(used, 0.10)
    exhausted = _apply(weight=0.08, used=used)
    assert exhausted["signal"] == "hold"
    assert exhausted["target_weight"] == 0.0
    assert exhausted["reason"] == "legacy_sleeve_budget_exhausted"


def test_last_entry_is_trimmed_to_the_remaining_budget():
    result = _apply(weight=0.08, used=0.09)
    assert math.isclose(result["target_weight"], 0.01)


def test_no_new_entries_while_the_book_is_vetoed_by_default():
    result = _apply(book_active=False)
    assert result["signal"] == "hold"
    assert result["reason"] == "legacy_sleeve_book_vetoed"


def test_vetoed_book_allows_entries_when_configured():
    result = _apply(book_active=False, config=dict(CONFIG, trade_when_book_vetoed=True))
    assert result["signal"] == "buy"


def test_book_members_book_owned_positions_exits_and_holds_pass_through():
    assert _apply(member=True)["reason"] == "legacy_sleeve_not_applicable"
    assert _apply(signal="sell", weight=-0.08)["signal"] == "sell"
    assert _apply(signal="hold", weight=0.0)["signal"] == "hold"
    # a position the BOOK opened, rotated out or un-selected during a veto, must not be shrunk to a sleeve weight
    owned = apply_legacy_sleeve_policy("buy", 0.08, False, True, False, 0.0, CONFIG, is_book_owned=True)
    assert owned["target_weight"] == 0.08 and owned["reason"] == "legacy_sleeve_not_applicable"


def test_a_held_sleeve_position_cannot_be_scaled_past_the_per_name_cap():
    """The 2% entry used to be resized to the legacy signal's full ~8% the next bar."""
    held = _apply(invested=True, weight=0.08)
    assert held["target_weight"] == 0.02
    assert held["reason"] == "legacy_sleeve_held_capped"
    assert held["sleeve_gross_used"] == 0.0  # already counted in the used budget; no double count
    short = _apply(signal="short", invested=True, weight=-0.08)
    assert short["target_weight"] == -0.02
    assert _apply(invested=True, weight=0.015)["target_weight"] == 0.015  # below the cap: untouched
    assert _apply(invested=True, weight=float("nan"))["reason"] == "legacy_sleeve_not_applicable"


def test_non_finite_weight_never_trades():
    for bad in (float("nan"), float("inf")):
        result = _apply(weight=bad)
        assert result["signal"] == "hold"
        assert result["target_weight"] == 0.0
    assert _apply(used=float("nan"))["signal"] == "hold"


def test_compute_sleeve_gross_counts_only_non_book_holdings():
    held = {"A": 0.05, "B": -0.03, "C": 0.10, "D": float("nan")}
    assert math.isclose(compute_sleeve_gross_used(held, {"C"}), 0.08)
    assert compute_sleeve_gross_used({}, set()) == 0.0
    assert compute_sleeve_gross_used({"A": "x"}, set()) == 0.0
