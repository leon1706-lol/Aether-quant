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
    mode.

    V5.2.7 (development/Problems.md) - CORRECTED docstring: this used to
    claim "scoped narrowly to the sticky total-drawdown lock and the
    regime risk_off drawdown branch," but that was never accurate once
    V5.1 Phase 6 extended main.py's session-rollover sticky-clear branch
    to ALSO cover any kill_switch_* trade_lock_reason, not just
    total_drawdown_limit_breached - this flag's real effect was always
    broader than its own docstring said. This is now the LEGACY combined
    flag, kept only for backward compatibility (still fully functional,
    still bundles both behaviors exactly as before) - new callers should
    use is_sticky_trade_lock_bypass_active()/is_regime_drawdown_bypass_active()
    below instead, which split the same two behaviors into independently
    configurable flags while still OR-ing this legacy flag in so nobody's
    existing config silently stops working."""
    return runtime_mode == "backtest" and bypass_flag


def is_sticky_trade_lock_bypass_active(
    runtime_mode: str,
    sticky_bypass_flag: bool,
    legacy_bypass_flag: bool,
) -> bool:
    """V5.2.7 (development/Problems.md) - True when a backtest is running
    with EITHER phase_v2.backtest.bypass_sticky_trade_lock OR the legacy
    phase_v2.backtest.bypass_safety_gates explicitly true. Controls ONLY
    main.py's session-rollover total_drawdown_limit_breached/kill_switch_*
    sticky-lock clear - never the regime risk_off drawdown branch (see
    is_regime_drawdown_bypass_active() for that, now a genuinely
    independent flag instead of the two being bundled together under one
    name). Any non-backtest runtime_mode always returns False regardless
    of either flag.

    Bug this closes: a real backtest showed a kill-switch trip on
    2020-02-27 stay locked for the remaining 13 months of a ~2.2-year
    backtest (336/336 book-member decisions forced to reduce_risk in that
    window, vs. 16% before the trip) - kill_switch_* reasons are
    deliberately exempt from the normal daily auto-clear (a real, correct
    safety choice for live/paper trading, where a human should decide
    when to resume after a genuine circuit-breaker trip), but an
    unattended historical backtest has no human to ever clear it, so a
    single trip event silently darkens the rest of the evaluation window
    regardless of whether the underlying conditions later recover."""
    return runtime_mode == "backtest" and (sticky_bypass_flag or legacy_bypass_flag)


def is_regime_drawdown_bypass_active(
    runtime_mode: str,
    regime_bypass_flag: bool,
    legacy_bypass_flag: bool,
) -> bool:
    """V5.2.7 (development/Problems.md) - True when a backtest is running
    with EITHER phase_v2.backtest.bypass_regime_drawdown_gate OR the
    legacy phase_v2.backtest.bypass_safety_gates explicitly true.
    Controls ONLY main.py::_build_regime_payload()'s
    risk_off_drawdown_threshold override (set to infinity when active,
    disabling just the drawdown-driven branch of classify_risk_regime -
    the bearish-trend/high-vol and composite-risk-score branches stay
    active regardless) - never the sticky trade-lock clear (see
    is_sticky_trade_lock_bypass_active() for that). Any non-backtest
    runtime_mode always returns False regardless of either flag.

    Deliberately a SEPARATE flag from the sticky-lock bypass above, even
    though both were previously bundled under the single
    bypass_safety_gates flag - a user who wants a stuck kill-switch lock
    to be able to clear should not be forced to also disable this
    unrelated regime-level protection as a side effect."""
    return runtime_mode == "backtest" and (regime_bypass_flag or legacy_bypass_flag)


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


def compute_held_weight(holdings_value: float, total_portfolio_value: float) -> float:
    """The current_weight formula _apply_signal()'s scaling branches already
    compute inline (twice, once per direction) - extracted so every caller
    reads one shared formula instead of maintaining duplicate copies that
    could silently drift if one is ever edited without the other. Floors
    total_portfolio_value at 1.0 (never divide by zero/negative)."""
    return holdings_value / max(total_portfolio_value, 1.0)


def is_position_resize_permitted(
    position_scaling_enabled: bool,
    is_book_selected: bool,
    is_rebalance_bar: bool,
) -> bool:
    """V5.2.1 (development/Problems.md) - a book-selected symbol's SIZE may
    only resize on a rebalance bar; every other symbol (an individual-
    signal trade, or every symbol when the book is disabled entirely) is
    completely unaffected by this gate.

    Bug this closes: should_scale_position() was being re-evaluated every
    single bar for book members too, entirely independent of the book's
    own is_rebalance_bar cadence - a book member's base weight is frozen
    between rebalances, but the downstream sizing pipeline (confidence/
    volatility/liquidity/cost multipliers) reinterprets that same frozen
    weight differently bar to bar from live noise, tripping
    rebalance_threshold_weight and firing real resize orders on non-
    rebalance bars. That noise-churn is what this gates out.

    Deliberately does NOT touch full exits (signal_name == "sell") or the
    V4.3.0 futures/options incremental-quantity protection
    (compute_incremental_order_quantity()) - both are unconditional,
    separate code paths, never gated by this function."""
    return position_scaling_enabled and (not is_book_selected or is_rebalance_bar)


def should_lock_in_duration_beta(
    window_length: int,
    treasury_window_length: int,
    target_window_length: int,
) -> bool:
    """V5.2.5 (development/Problems.md #91-continuation) - whether enough
    history has accumulated to compute bond_empirical_duration_beta ONCE
    and cache it, rather than re-rolling a fresh (and therefore drifting)
    estimate every bar.

    Bug this closes: main.py::_bond_empirical_duration_beta_for_symbol()
    used to recompute this OLS slope from a ROLLING window every single
    bar for the life of the backtest, while train.py::build_bond_features_by_date()
    (the offline path that produced the model's OWN training data) computes
    it ONCE per ticker - a single slope over that asset's entire available
    history - and broadcasts that unchanged value to every row. The model
    was trained on a stable, whole-history characteristic per bond asset;
    live was feeding it a noisy, continuously-drifting value instead - an
    out-of-training-distribution input for every bond-tagged symbol, every
    bar, confirmed directly correlated with the bond-ETF-heavy live-vs-
    offline selection mismatch pattern found in the V5.2.4 reconciliation.

    True once BOTH the price window and the treasury-yield window have
    reached `target_window_length` (main.py's own `self.long_bar_history_size`,
    260 - the deque's own maxlen, the most history practically available to
    a live algorithm that can never see future data the way an offline
    batch process can) - mirrors train.py's own "compute once per ticker,
    broadcast unchanged" semantic as closely as a real-time algorithm's
    inherent lack of future history allows. Both windows must independently
    clear the bar (AND, not OR) - a symbol with plenty of price history but
    a still-filling treasury-yield history (or vice versa) isn't ready yet."""
    return window_length >= target_window_length and treasury_window_length >= target_window_length


def compute_forex_order_units(target_weight: float, close_price: float, portfolio_value: float) -> int:
    """V5.2.7 (development/Problems.md) - converts a target portfolio
    weight into whole base-currency UNITS for a Forex MarketOrder - NOT a
    lot count. QuantConnect Lean's MarketOrder() for SecurityType.Forex
    takes raw base-currency units (e.g. MarketOrder("EURUSD", 10000) =
    10,000 EUR), matching Portfolio[symbol].Quantity's own reporting
    convention - standard, documented Lean/IB behavior, but UNVERIFIED
    empirically in this repo/Lean image as of this fix. See
    build_forex_order_sizing_record()'s notional_ratio field for the
    direct, human-checkable confirmation this assumption needs from a
    real backtest.

    Bug this closes: main.py::_forex_lot_count_for_weight() used to
    divide notional by (lot_size * close_price) - a full 100,000-unit
    standard lot - which on a $100k backtest account with a realistic
    book-member position weight (4-12%) produces a notional ($4,000-
    $12,000) far smaller than even one lot ($67,000-$130,000+), so the
    division always rounded to 0. Confirmed directly: forex allocations
    that cleared every other risk/liquidity/confidence gate and reached
    a real "trade" decision still silently produced zero Lean orders.

    Deliberately does NOT round to a whole lot_size multiple either -
    that would silently reproduce the exact same always-zero-orders bug
    under a new name, since the same realistic position sizes are still
    far below one full lot. Rounds to the nearest whole UNIT instead
    (IB/Lean forex orders must be whole units, never fractional
    currency). Returns 0 (never raises) when close_price or
    portfolio_value is non-positive."""
    if close_price <= 0.0 or portfolio_value <= 0.0:
        return 0
    notional = target_weight * portfolio_value
    return int(round(notional / close_price))


def build_forex_order_sizing_record(
    date_str: str,
    symbol: str,
    direction: str,
    target_weight: float,
    portfolio_value: float,
    close_price: float,
    order_units: int,
) -> dict:
    """V5.2.7 (development/Problems.md) - a diagnostic snapshot of one
    forex order-sizing decision, for main.py's optional (config-gated,
    off by default, backtest-only) forex-order-sizing log. Exists
    because compute_forex_order_units()'s "Lean forex MarketOrder takes
    raw units" assumption cannot be verified from this Python codebase
    alone - notional_ratio is the direct, human-checkable confirmation a
    real backtest's log can provide instead: it should sit very close to
    1.0 for correct sizing (only whole-unit rounding slop); a value
    wildly off (e.g. 100x or 0.01x) is the exact, unambiguous symptom of
    a wrong units assumption, and should be treated as disqualifying for
    that backtest's other results until investigated.

    Pure: no I/O, no `self`, never raises on well-formed inputs.
    intended_notional == 0.0 (target_weight == 0.0) returns
    notional_ratio=None rather than dividing by zero - a symbol with no
    real order to place has nothing to sanity-check."""
    intended_notional = target_weight * portfolio_value
    implied_notional = order_units * close_price
    return {
        "date": date_str,
        "symbol": symbol,
        "direction": direction,
        "target_weight": target_weight,
        "portfolio_value": portfolio_value,
        "close_price": close_price,
        "order_units": order_units,
        "intended_notional": intended_notional,
        "implied_notional": implied_notional,
        "notional_ratio": (implied_notional / intended_notional) if intended_notional != 0.0 else None,
    }


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
