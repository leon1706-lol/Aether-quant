"""Pure risk-control helpers shared by tests and the Lean algorithm."""

from __future__ import annotations


def assess_drawdown_lock(
    daily_drawdown: float,
    total_drawdown: float,
    max_daily_drawdown_pct: float,
    max_total_drawdown_pct: float,
) -> tuple[bool, str | None]:
    if total_drawdown <= -max_total_drawdown_pct:
        return True, "total_drawdown_limit_breached"
    if daily_drawdown <= -max_daily_drawdown_pct:
        return True, "daily_drawdown_limit_breached"
    return False, None


def is_backtest_safety_bypass_active(runtime_mode: str, bypass_flag: bool) -> bool:
    """True only when a backtest is running with
    phase_v2.backtest.bypass_safety_gates explicitly set to true - any
    non-backtest runtime_mode always returns False regardless of the flag,
    and the flag defaults to False (gates active, honest/deployable-
    representative) so this is opt-in, not implicit. Deliberately
    independent of aq trade-lock's on/off/auto override, which keeps its
    existing, separately-documented meaning unchanged in every runtime
    mode. Scoped narrowly to the sticky total-drawdown lock and the
    regime risk_off drawdown branch - never touches liquidity/topology/
    cooldown/exposure gates."""
    return runtime_mode == "backtest" and bypass_flag


def active_position_limit_reached(
    active_positions: int,
    max_active_positions: int,
    is_currently_invested: bool,
) -> bool:
    return not is_currently_invested and active_positions >= max_active_positions


def cap_target_weight(
    target_weight: float,
    current_exposure: float,
    exposure_cap: float,
) -> tuple[float, bool]:
    remaining_exposure = max(0.0, exposure_cap - current_exposure)
    requested_exposure = abs(target_weight)
    if requested_exposure <= remaining_exposure:
        return target_weight, False

    if remaining_exposure <= 0.0:
        return 0.0, True

    direction = 1.0 if target_weight >= 0.0 else -1.0
    return direction * remaining_exposure, False


def should_scale_position(
    current_weight: float,
    target_weight: float,
    rebalance_threshold_weight: float,
) -> bool:
    """True iff an already-open, same-direction position's target has moved
    far enough (>= threshold) to warrant resubmitting an order, rather than
    treating trivial confidence wiggle as churn. Direction-agnostic (abs) -
    callers only invoke this once a same-direction hold is already
    established via the unchanged previous_signal gate."""
    return abs(target_weight - current_weight) >= rebalance_threshold_weight


def compute_incremental_order_quantity(
    target_quantity: float,
    current_quantity: float,
) -> float:
    """target_quantity is an ABSOLUTE, already-signed sizing target
    (futures contract count, or a matched option contract's/spread's
    target quantity), recomputed fresh every bar; current_quantity is
    whatever is actually held right now. Returns the signed delta an
    incremental order primitive (MarketOrder/Buy) must submit to converge
    toward target_quantity, instead of firing the absolute target every
    bar and silently overshooting it. Pure arithmetic, never raises -
    callers round/zero-check the result themselves."""
    return target_quantity - current_quantity


def evaluate_non_model_exit(
    bar_index: int,
    exits_enabled: bool,
    exits_max_holding_bars: int,
    exits_trailing_stop_pct: float,
    entry_bar_index: int | None,
    peak_price_since_entry: float | None,
    direction: str,
    close_price: float,
) -> str | None:
    """V4.10 - pure extraction of main.py::_check_non_model_exit(),
    asset-class-agnostic (same trailing-stop/max-age math for equity,
    crypto, futures, options, forex alike). Two checks, first match wins:

    1. Max holding age: fires once bar_index - entry_bar_index reaches
       exits_max_holding_bars, regardless of price.
    2. Trailing stop: fires once price has drawn down
       exits_trailing_stop_pct from its best price since entry
       (direction-aware: "best" is the highest close for a long, lowest
       for a short).

    exits_enabled=False restores pre-fix behavior byte-for-byte - no
    non-model exit ever fires. Caller resolves the per-symbol dict
    lookups (entry_bar_index/peak_price_since_entry/direction) before
    calling - this function itself touches no dicts, no self."""
    if not exits_enabled:
        return None

    if entry_bar_index is None:
        return None

    if bar_index - entry_bar_index >= exits_max_holding_bars:
        return "max_holding_age_exceeded"

    if peak_price_since_entry is not None and peak_price_since_entry > 0.0:
        if direction == "long":
            drawdown_from_peak = (peak_price_since_entry - close_price) / peak_price_since_entry
        else:
            drawdown_from_peak = (close_price - peak_price_since_entry) / peak_price_since_entry
        if drawdown_from_peak >= exits_trailing_stop_pct:
            return "trailing_stop_triggered"

    return None


def compute_position_exit_tracking_update(
    was_invested: bool,
    is_invested: bool,
    close_price: float,
    signal_name: str,
    peak_price_since_entry: float | None,
    direction: str | None,
    bar_index: int,
) -> dict:
    """V4.10 - pure extraction of main.py::_update_position_exit_tracking().
    Observes the net invested/not-invested transition (was_invested vs.
    is_invested) rather than hooking into any asset-class-specific
    routing - robust to every routing path by construction, since it only
    cares about the outcome.

    Returns the NEW state as a dict rather than mutating dicts in place,
    so this stays pure/testable - the caller applies the result to its
    own tracking dicts:
    - {"action": "enter", "entry_bar_index":, "entry_price":,
      "peak_price_since_entry":, "direction":} on a fresh entry.
    - {"action": "hold", "peak_price_since_entry":} while an existing
      position is held (entry_bar_index/entry_price are untouched by
      design - not present in this dict).
    - {"action": "clear"} once a held position is closed.
    - {"action": "noop"} otherwise (was never invested and still isn't -
      matches the original method's implicit no-op branch)."""
    if is_invested and not was_invested:
        return {
            "action": "enter",
            "entry_bar_index": bar_index,
            "entry_price": close_price,
            "peak_price_since_entry": close_price,
            "direction": "short" if signal_name == "short" else "long",
        }

    if is_invested and was_invested:
        resolved_direction = direction or "long"
        peak_price = peak_price_since_entry if peak_price_since_entry is not None else close_price
        if resolved_direction == "long":
            new_peak_price = max(peak_price, close_price)
        else:
            new_peak_price = min(peak_price, close_price)
        return {"action": "hold", "peak_price_since_entry": new_peak_price}

    if not is_invested and was_invested:
        return {"action": "clear"}

    return {"action": "noop"}
