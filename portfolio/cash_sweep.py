"""Idle cash held in a T-bill ETF (V6.2.0, `phase_v2.cash_sweep`, default off).

The book is market neutral and mostly vetoed, so 70-95% of the NAV sits as cash Lean pays no interest on, while Lean's
Sharpe subtracts the full risk-free rate. A market-neutral fund holds that cash in T-bills; this sizes such a holding
(BIL by default, a ticker outside the universe: never scored, ranked, gated or capped) under two hard limits:

  * **no borrowing**: cash after the sweep and everything the strategy may still buy by the next session stays at or
    above `cash_buffer`. Lean charges no margin interest, so a sweep bought on margin would be free carry;
  * **margin**: Lean's buying-power check runs when an order is submitted and does not net sells that have not filled,
    so the sweep leaves room for the whole next session's orders (a fresh book on a rebalance attempt) inside
    `1 - margin_buffer` of the margin Lean's default brokerage model allows (equity 2x, crypto 1x, forex 50x).

The kill switch, the drawdown velocity and the drawdown lock read the strategy's own value (`advance_strategy_value`):
T-bill carry must not mask a failing strategy, and the book's decisions stay its own.
main.py and the offline simulator call the same functions. Pure, NaN-safe.
"""

from __future__ import annotations

import math

# Lean DefaultBrokerageModel.GetLeverage for a margin account (main.py sets no brokerage model)
LEAN_DEFAULT_LEVERAGE = {"equity": 2.0, "crypto": 1.0, "forex": 50.0, "cfd": 50.0}

DEFAULTS = {
    "enabled": False,
    "ticker": "BIL",
    "data_path": "data/equity/usa/daily/bil.zip",
    "max_weight": 0.9,
    "margin_leverage": 2.0,
    "margin_buffer": 0.1,
    "cash_buffer": 0.02,
    "min_trade_weight": 0.05,
    "cost_bps_per_side": 1.0,
    "exclude_from_risk_controls": True,
}


def _finite(value, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def resolve_cash_sweep_config(raw: dict | None) -> dict:
    """`phase_v2.cash_sweep` with defaults; out-of-range numbers fall back to the default rather than raise."""
    raw = raw or {}
    config = {
        "enabled": bool(raw.get("enabled", DEFAULTS["enabled"])),
        "ticker": str(raw.get("ticker") or DEFAULTS["ticker"]).upper(),
        "data_path": str(raw.get("data_path") or DEFAULTS["data_path"]),
        "exclude_from_risk_controls": bool(raw.get("exclude_from_risk_controls", DEFAULTS["exclude_from_risk_controls"])),
    }
    bounds = {
        "max_weight": (0.0, 1.0), "margin_leverage": (1.0, 50.0), "margin_buffer": (0.0, 0.9),
        "cash_buffer": (0.0, 0.5), "min_trade_weight": (0.0, 1.0), "cost_bps_per_side": (0.0, 100.0),
    }
    for key, (low, high) in bounds.items():
        value = _finite(raw.get(key, DEFAULTS[key]), DEFAULTS[key])
        config[key] = value if low <= value <= high else DEFAULTS[key]
    return config


def margin_fraction(weights: list[tuple[str, float]]) -> float:
    """Margin Lean's default model holds for these (security type, signed weight) positions, as a fraction of NAV."""
    total = 0.0
    for security_type, weight in weights:
        leverage = LEAN_DEFAULT_LEVERAGE.get(str(security_type).lower(), 1.0)
        total += abs(_finite(weight, 0.0)) / leverage
    return total


def strategy_reserve(
    *,
    rebalance_next: bool,
    book_gross_cap: float,
    max_short_exposure: float,
    formed_long: float,
    formed_short: float,
    book_long: float,
    book_short: float,
    other_budget_remaining: float,
    neutral_budget: float = 0.0,
) -> dict:
    """Gross the strategy may add by the next session, by side, and the margin it would hold. On a rebalance attempt a
    whole new book can be ordered (long up to half the cap, short up to half the cap and `max_short_exposure`) while the
    current one is still held, since sells free nothing until they fill; otherwise only the formed book's unfilled part.
    `other_budget_remaining` (the legacy signal) is counted as long at leverage 1, the worst case for both limits;
    `neutral_budget` (the class sleeves, dollar-neutral by construction: `build_class_sleeve_weights`) as half long and
    half short at equity leverage."""
    cap = max(0.0, _finite(book_gross_cap, 0.0))
    if rebalance_next:
        add_long = cap / 2.0
        add_short = min(cap / 2.0, max(0.0, _finite(max_short_exposure, cap / 2.0)))
    else:
        add_long = max(0.0, _finite(formed_long, 0.0) - _finite(book_long, 0.0))
        add_short = max(0.0, _finite(formed_short, 0.0) - _finite(book_short, 0.0))
    other = max(0.0, _finite(other_budget_remaining, 0.0))
    neutral = max(0.0, _finite(neutral_budget, 0.0))
    return {
        "long": add_long + other + neutral / 2.0,
        "short": add_short + neutral / 2.0,
        "margin": (add_long + add_short + neutral) / LEAN_DEFAULT_LEVERAGE["equity"] + other,
    }


def cash_sweep_target_weight(
    *, long_weight: float, short_weight: float, margin_used: float, reserve: dict, config: dict
) -> float:
    """Sweep weight (fraction of NAV) inside both limits and `max_weight`; 0.0 for any non-finite input."""
    values = [long_weight, short_weight, margin_used, reserve.get("long"), reserve.get("short"), reserve.get("margin")]
    if any(not math.isfinite(_finite(value, float("nan"))) for value in values):
        return 0.0
    long_weight, short_weight, margin_used = abs(float(long_weight)), abs(float(short_weight)), float(margin_used)
    by_margin = config["margin_leverage"] * (1.0 - config["margin_buffer"] - margin_used - float(reserve["margin"]))
    # an unfilled short's proceeds fund only the longs ordered with it: a short that never fills (a cap, a lock) must not
    # leave the sweep bought on credit
    credit = min(float(reserve["short"]), float(reserve["long"]))
    by_cash = 1.0 - long_weight + short_weight - float(reserve["long"]) + credit - config["cash_buffer"]
    return max(0.0, min(config["max_weight"], by_margin, by_cash))


def sweep_order_needed(current_weight: float, target_weight: float, min_trade_weight: float) -> bool:
    """Trade when the gap is at least `min_trade_weight`, or whenever the sweep is above its target (a cut for the
    limits is never deferred)."""
    current, target = _finite(current_weight, 0.0), _finite(target_weight, 0.0)
    return current > target + 1e-9 or abs(target - current) >= float(min_trade_weight)


def advance_strategy_value(state: dict | None, total_value: float, sweep_profit: float) -> tuple[dict, float]:
    """The value the risk controls read: an index that compounds the strategy's own P&L (the portfolio's change minus the
    sweep's) over the TOTAL value the strategy is sized on, starting at the first total value seen. Subtracting the
    cumulative carry from the total instead (V6.2.0's first BT1) divides the strategy's dollar P&L by a smaller base than
    it was sized on: ~8% inflated returns and drawdown speed by mid-2024, enough to trip the kill switch on a day V6.1
    did not. The offline simulator's kill switch reads the same quantity (book + legacy return as a fraction of NAV).
    Returns (new state, value); a non-finite or non-positive input keeps the previous value."""
    total = _finite(total_value, float("nan"))
    sweep = _finite(sweep_profit, 0.0)
    if state is None:
        if not math.isfinite(total) or total <= 0.0:
            return None, total_value
        return {"total": total, "sweep": sweep, "value": total}, total
    if not math.isfinite(total) or total <= 0.0 or state["total"] <= 0.0:
        return state, state["value"]
    strategy_return = ((total - state["total"]) - (sweep - state["sweep"])) / state["total"]
    value = state["value"] * (1.0 + strategy_return)
    return {"total": total, "sweep": sweep, "value": value}, value
