"""Per-sleeve loss guard (V5.8.0).

V5.8.0 enables sleeves the evidence may not fully support (owner decision: forex, bonds, newly eligible crypto and RL
sizing trade even without a proven edge, at a minimal cap). The cap bounds the exposure; this guard bounds the damage.
Each sleeve's mark-to-market P&L is tracked per bar; when its drawdown from the running peak over the trailing
`lookback_bars` exceeds `max_loss_fraction_nav` of NAV, the sleeve is suspended for `cooldown_bars`: no new entries, its
positions are closed. The portfolio-level kill switch stays the control for the whole book; this one only switches a
sleeve off.

Pure, no I/O. `main.py` and `evaluation/rank_book_simulator.py` call the same function (parity contract).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class SleeveGuardConfig:
    enabled: bool = False
    max_loss_fraction_nav: float = 0.01
    lookback_bars: int = 60
    cooldown_bars: int = 60


def resolve_sleeve_guard_config(raw: dict | None) -> SleeveGuardConfig:
    """Config block -> SleeveGuardConfig; absent or malformed keys fall back to the defaults (disabled)."""
    raw = raw or {}

    def _number(key: str, default: float) -> float:
        try:
            value = float(raw.get(key, default))
        except (TypeError, ValueError):
            return default
        return value if math.isfinite(value) else default

    return SleeveGuardConfig(
        enabled=bool(raw.get("enabled", False)),
        max_loss_fraction_nav=max(0.0, _number("max_loss_fraction_nav", 0.01)),
        lookback_bars=max(1, int(_number("lookback_bars", 60))),
        cooldown_bars=max(0, int(_number("cooldown_bars", 60))),
    )


def trailing_drawdown(pnl_increments: Sequence[float], lookback_bars: int) -> float:
    """Largest peak-to-trough fall (a positive number, same unit as the increments) of the cumulative P&L over the last
    `lookback_bars` increments, measured up to the latest bar. Non-finite increments count as 0."""
    window = [float(value) if value is not None and math.isfinite(float(value)) else 0.0 for value in pnl_increments[-lookback_bars:]]
    peak = 0.0
    level = 0.0
    for value in window:
        level += value
        peak = max(peak, level)
    return max(0.0, peak - level)


def evaluate_sleeve_guard(
    pnl_increments: Sequence[float],
    nav: float,
    config: SleeveGuardConfig,
    *,
    current_bar: int,
    suspended_until_bar: int | None = None,
) -> dict:
    """Decides whether the sleeve may trade on `current_bar`.

    `pnl_increments` is the sleeve's per-bar P&L history (dollars, or NAV fractions with `nav=1.0`), oldest first.
    Returns {"active": bool, "reason": str, "suspended_until_bar": int | None, "drawdown": float, "limit": float}.
    A suspension started earlier holds until `suspended_until_bar` (exclusive); a fresh breach starts a new one. The
    history is NOT reset by the caller: after the cooldown the trailing window usually no longer contains the loss, and
    if it still does the sleeve stays off - a loss that has not healed is not a reason to resume."""
    limit = max(0.0, float(nav)) * config.max_loss_fraction_nav if math.isfinite(float(nav)) else 0.0
    if not config.enabled:
        return {"active": True, "reason": "sleeve_guard_disabled", "suspended_until_bar": None, "drawdown": 0.0, "limit": limit}
    drawdown = trailing_drawdown(pnl_increments, config.lookback_bars)
    if suspended_until_bar is not None and current_bar < suspended_until_bar:
        return {"active": False, "reason": "sleeve_guard_cooldown", "suspended_until_bar": suspended_until_bar,
                "drawdown": drawdown, "limit": limit}
    if limit > 0.0 and drawdown > limit:
        return {"active": False, "reason": "sleeve_guard_loss_limit", "suspended_until_bar": current_bar + config.cooldown_bars,
                "drawdown": drawdown, "limit": limit}
    return {"active": True, "reason": "sleeve_guard_ok", "suspended_until_bar": None, "drawdown": drawdown, "limit": limit}


def sleeve_pnl_increment(previous_values: dict[str, float], current_values: dict[str, float], cash_flows: dict[str, float]) -> float:
    """Mark-to-market P&L of a sleeve between two bars: change in its positions' market value minus the cash put in
    (buys positive, sells negative, fees positive). Symbols missing on one side count as 0."""
    symbols = set(previous_values) | set(current_values) | set(cash_flows)
    total = 0.0
    for symbol in symbols:
        change = float(current_values.get(symbol, 0.0)) - float(previous_values.get(symbol, 0.0))
        total += change - float(cash_flows.get(symbol, 0.0))
    return total if math.isfinite(total) else 0.0
