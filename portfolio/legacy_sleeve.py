"""Capped "legacy signal" sleeve for the rank book (V5.5.0, Problems.md #128).

Background: with the portfolio book enabled, every symbol the book does NOT
select still ran the original probability-up signal path (`_derive_signal`).
In the 2026-08-27 backtest 121 of 155 equity entries came from that old
long-only path and only 33 from the book, so live equity was "the old signal
plus the book's shorts", a strategy the offline rank-book simulation never
modeled. This module keeps that path but puts it inside an explicit,
measurable budget instead of letting it run unbounded:

- a gross-exposure budget shared by every sleeve position,
- a per-name weight cap,
- no new sleeve entries while the book is vetoed (default).

Pure and Lean-free: main.py calls `apply_legacy_sleeve_policy()` once per
non-book symbol, the offline simulator reads the same config.
"""

from __future__ import annotations

import math

DEFAULT_LEGACY_SLEEVE_CONFIG = {
    "enabled": False,
    "max_gross_exposure": 0.10,
    "max_weight_per_name": 0.02,
    "trade_when_book_vetoed": False,
}


def resolve_legacy_sleeve_config(raw: dict | None) -> dict:
    """Normalize `phase_v2.legacy_sleeve`; any malformed value falls back to
    the default (sleeve disabled == the pre-V5.5.0 unbounded behavior)."""
    config = dict(DEFAULT_LEGACY_SLEEVE_CONFIG)
    if not isinstance(raw, dict):
        return config
    config["enabled"] = bool(raw.get("enabled", config["enabled"]))
    config["trade_when_book_vetoed"] = bool(raw.get("trade_when_book_vetoed", config["trade_when_book_vetoed"]))
    for key in ("max_gross_exposure", "max_weight_per_name"):
        try:
            value = float(raw.get(key, config[key]))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value >= 0.0:
            config[key] = value
    return config


def compute_sleeve_gross_used(
    held_weights_by_symbol: dict[str, float],
    book_member_keys: set[str] | frozenset[str],
) -> float:
    """Gross |weight| currently held outside the book: every invested symbol
    that is neither in this bar's book nor in the last formed book. During a
    veto the book is empty, so remembered members still count as book (they
    are positions the book opened), not sleeve."""
    gross = 0.0
    for symbol_key, weight in held_weights_by_symbol.items():
        if symbol_key in book_member_keys:
            continue
        try:
            value = abs(float(weight))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            gross += value
    return gross


def apply_legacy_sleeve_policy(
    signal_name: str,
    target_weight: float,
    is_book_member: bool,
    is_currently_invested: bool,
    book_is_active: bool,
    sleeve_gross_used: float,
    sleeve_config: dict,
    is_book_owned: bool = False,
) -> dict:
    """Decide how much of a non-book symbol's legacy signal may trade.

    Returns {"signal", "target_weight", "reason", "sleeve_gross_used"}.
    - A NEW entry ("buy"/"short" on a flat, non-book symbol) is admitted only
      inside the gross budget and the per-name cap. The returned
      `sleeve_gross_used` includes it, so the caller threads it through the
      rest of the bar's loop and the budget is atomic across symbols.
    - A HELD sleeve position (invested, not book-owned) that the legacy signal
      wants to size up is capped at the per-name weight - otherwise the 2%
      entry would be scaled to the signal's full ~8% on the next bar.
    - Book members, positions the BOOK opened (`is_book_owned` - during a veto
      they are non-members too, and must not be shrunk to a sleeve weight),
      exits ("sell") and "hold" pass through untouched.
    """
    passthrough = {
        "signal": signal_name,
        "target_weight": target_weight,
        "reason": "legacy_sleeve_not_applicable",
        "sleeve_gross_used": sleeve_gross_used,
    }
    if not sleeve_config.get("enabled"):
        return passthrough
    if is_book_member or is_book_owned or signal_name not in ("buy", "short"):
        return passthrough
    if is_currently_invested:
        try:
            requested_held = abs(float(target_weight))
        except (TypeError, ValueError):
            return passthrough
        cap = float(sleeve_config["max_weight_per_name"])
        if not math.isfinite(requested_held) or requested_held <= cap:
            return passthrough
        direction = 1.0 if float(target_weight) >= 0.0 else -1.0
        return {
            "signal": signal_name,
            "target_weight": direction * cap,
            "reason": "legacy_sleeve_held_capped",
            "sleeve_gross_used": sleeve_gross_used,
        }

    def _hold(reason: str) -> dict:
        return {"signal": "hold", "target_weight": 0.0, "reason": reason, "sleeve_gross_used": sleeve_gross_used}

    if not book_is_active and not sleeve_config.get("trade_when_book_vetoed", False):
        return _hold("legacy_sleeve_book_vetoed")
    try:
        requested = abs(float(target_weight))
    except (TypeError, ValueError):
        return _hold("legacy_sleeve_non_finite_weight")
    if not math.isfinite(requested) or not math.isfinite(sleeve_gross_used):
        return _hold("legacy_sleeve_non_finite_weight")

    remaining = float(sleeve_config["max_gross_exposure"]) - sleeve_gross_used
    if remaining <= 0.0:
        return _hold("legacy_sleeve_budget_exhausted")
    capped = min(requested, float(sleeve_config["max_weight_per_name"]), remaining)
    if capped <= 0.0:
        return _hold("legacy_sleeve_budget_exhausted")
    direction = 1.0 if float(target_weight) >= 0.0 else -1.0
    return {
        "signal": signal_name,
        "target_weight": direction * capped,
        "reason": "legacy_sleeve_capped" if capped < requested else "legacy_sleeve_within_budget",
        "sleeve_gross_used": sleeve_gross_used + capped,
    }
