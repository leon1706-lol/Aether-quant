"""Pure, Lean-free order gating for Phase V2-15 (Observation Mode).

No imports from AlgorithmImports/QCAlgorithm live here on purpose: this
module owns the mode -> real-vs-simulated order decision table and must be
unit-testable without a Lean runtime on sys.path.
"""

from __future__ import annotations

VALID_MODES = ("backtest", "observation", "paper", "live")
DEFAULT_FALLBACK_MODE = "observation"

# Default ceiling on the per-fill slippage resolve_fill_slippage() will
# ever apply, regardless of what liquidity/market_liquidity.py's
# estimated_round_trip_cost computes. 500bps (5%) is far above anything the
# estimator produces under normal participation (build_liquidity_decision()
# already blocks orders at 5% participation, long before slippage_factor's
# default 0.1 multiplier could get anywhere near this), so this only ever
# binds as a guard against a degenerate estimate (e.g. a volatility spike on
# a razor-thin bar) corrupting a fill price - never a normal-path limiter.
# Overridable via phase_v2.liquidity.fill_slippage.max_bps (main.py reads
# it in _ensure_ready() and passes it into every call below) - this
# constant is only the fallback when that key is absent from config.json.
MAX_LIQUIDITY_SLIPPAGE_BPS = 500.0

# phase_v2.liquidity.fill_slippage.source: which LiquidityDecision field
# main.py converts into fill-slippage bps. "round_trip" (default, see
# execution/README.md's "Real fill slippage" section for the rationale) =
# estimated_round_trip_cost (price impact + bid-ask spread combined).
# "impact_only" = estimated_slippage alone, for isolating/excluding the
# spread-crossing component.
VALID_FILL_SLIPPAGE_SOURCES = ("round_trip", "impact_only")
DEFAULT_FILL_SLIPPAGE_SOURCE = "round_trip"


def resolve_runtime_mode(raw_mode: str | None) -> str:
    """Normalize a config-supplied mode value, failing safe to observation."""
    if isinstance(raw_mode, str) and raw_mode in VALID_MODES:
        return raw_mode
    return DEFAULT_FALLBACK_MODE


def resolve_order_permission(
    mode: str,
    allow_live_orders: bool,
    broker_config_present: bool,
    risk_locks_healthy: bool,
) -> tuple[bool, str]:
    """Decide whether a real broker order may be placed in the given mode.

    observation always returns False regardless of the other flags - this is
    the single safety invariant the whole phase depends on.
    """
    if mode == "backtest":
        return True, "backtest_unrestricted"

    if mode == "observation":
        return False, "observation_mode_no_real_orders"

    if mode == "paper":
        if allow_live_orders and broker_config_present:
            return True, "paper_orders_enabled"
        return False, "paper_orders_blocked_missing_flag_or_broker_config"

    if mode == "live":
        if allow_live_orders and broker_config_present and risk_locks_healthy:
            return True, "live_orders_enabled"
        return False, "live_orders_blocked_missing_flag_or_broker_config_or_risk_lock"

    return False, "unknown_mode_defaults_to_no_orders"


def slippage_amount(reference_price: float, slippage_bps: float) -> float:
    """Absolute per-unit price slippage for a given bps estimate.

    Shared by main.py's Lean SlippageModel (real backtest/live fills, wired
    via security.SetSlippageModel()) and simulate_fill() below
    (observation-mode simulated fills), so both paths apply the exact same
    bps -> price-impact math instead of two independently-drifting
    formulas. Returns 0.0 for a non-positive price or non-positive bps -
    slippage is never negative (never improves the fill price).
    """
    if reference_price <= 0 or slippage_bps <= 0:
        return 0.0
    return float(reference_price) * (float(slippage_bps) / 10_000.0)


def resolve_fill_slippage_source(raw_source: str | None) -> str:
    """Normalize a phase_v2.liquidity.fill_slippage.source config value,
    failing safe to DEFAULT_FILL_SLIPPAGE_SOURCE for anything unset/unknown
    - same fail-safe-normalize convention as resolve_runtime_mode() above.
    """
    if isinstance(raw_source, str) and raw_source in VALID_FILL_SLIPPAGE_SOURCES:
        return raw_source
    return DEFAULT_FILL_SLIPPAGE_SOURCE


def liquidity_cost_fraction(liquidity_payload: dict, source: str) -> float:
    """Pick which liquidity/market_liquidity.py::LiquidityDecision field
    (already a fraction, e.g. 0.001 = 10bps) feeds the fill-slippage
    estimate, per resolve_fill_slippage_source()'s normalized source.
    Missing/malformed field -> 0.0, never raises.
    """
    key = "estimated_slippage" if source == "impact_only" else "estimated_round_trip_cost"
    return float(liquidity_payload.get(key, 0.0) or 0.0)


def resolve_slippage_bps(
    symbol_key: str,
    slippage_bps_by_symbol: dict,
    max_bps: float = MAX_LIQUIDITY_SLIPPAGE_BPS,
) -> float:
    """Pure lookup + clamp: how many bps of slippage to charge symbol_key,
    given the per-symbol bps dict main.py refreshes every bar in
    on_data()'s Pass 2 (liquidity_cost_fraction()'s selected field,
    converted to bps). Shared by resolve_fill_slippage() below (real Lean
    fills) and main.py's observation-mode
    SimulatedPortfolioState.enter_long() call sites, so both paths apply
    the identical clamp.

    Missing symbol -> 0.0 bps (no liquidity estimate computed yet, e.g. an
    order placed before Pass 2 has run for it once). Clamped to max_bps
    (phase_v2.liquidity.fill_slippage.max_bps, defaulting to
    MAX_LIQUIDITY_SLIPPAGE_BPS) as a guard against a degenerate estimate
    corrupting a fill price.
    """
    bps = float(slippage_bps_by_symbol.get(symbol_key, 0.0) or 0.0)
    return min(max(bps, 0.0), float(max_bps))


def resolve_fill_slippage(
    symbol_key: str,
    reference_price: float,
    slippage_bps_by_symbol: dict,
    max_bps: float = MAX_LIQUIDITY_SLIPPAGE_BPS,
) -> float:
    """Pure lookup + clamp + apply, used by main.py's real Lean
    SlippageModel (_LiquidityAwareSlippageModel.GetSlippageApproximation)
    to turn the per-symbol bps dict into an absolute fill-price delta."""
    return slippage_amount(reference_price, resolve_slippage_bps(symbol_key, slippage_bps_by_symbol, max_bps))


def simulate_fill(
    close_price: float,
    target_weight: float,
    equity: float,
    slippage_bps: float = 0.0,
) -> dict:
    """Pure hypothetical fill-price/quantity/notional math.

    Quantity/notional are purely a function of the target portfolio weight,
    current equity, and fill price - the same math applies whether the
    caller is entering, exiting (target_weight=0.0), or liquidating.
    """
    if close_price <= 0:
        return {"fill_price": 0.0, "notional": 0.0, "quantity": 0.0}

    fill_price = close_price + slippage_amount(close_price, slippage_bps)
    notional = target_weight * equity
    quantity = notional / fill_price

    return {
        "fill_price": fill_price,
        "notional": notional,
        "quantity": quantity,
    }


def resolve_limit_price(
    reference_price: float,
    spread_fraction: float,
    is_buy: bool,
    offset_multiplier: float = 1.0,
) -> float:
    """Pure limit-price placement for main.py's real limit orders
    (execution/risk realism pass, part 2).

    Offsets reference_price by half of spread_fraction (already a
    fraction, e.g. 0.001 = 10bps - the same unit family
    liquidity_cost_fraction() above consumes) times offset_multiplier
    (phase_v2.limit_orders.offset_multiplier). Halving matches the
    standard "bid = mid - spread/2, ask = mid + spread/2" convention -
    spread_fraction is a round-trip/full-spread estimate
    (liquidity/market_liquidity.py's spread_proxy), a single-sided limit
    order should only cross half of it.

    A buy limit sits BELOW reference_price (never overpay above the last
    close); a sell/short limit sits ABOVE it (never undersell below the
    last close). offset_multiplier > 1.0 places a more passive (further
    from reference, lower fill probability, more price improvement if
    filled) limit; < 1.0 places a more aggressive one (closer to/crossing
    reference, higher fill probability, less improvement).

    Returns reference_price unchanged whenever reference_price or
    spread_fraction is non-positive - never returns a non-positive or
    crossed-through price, matching slippage_amount()'s fail-safe-to-
    neutral convention above.
    """
    if reference_price <= 0 or spread_fraction <= 0:
        return float(reference_price)
    offset = float(reference_price) * (float(spread_fraction) / 2.0) * float(offset_multiplier)
    return reference_price - offset if is_buy else reference_price + offset


# Pure classification of a Lean OrderStatus enum member's name (or
# str(status)) into "pending" / "filled" / "canceled" / "unknown" -
# isolates the one place this pass has to guess at Lean's real OrderStatus
# spelling (see execution/README.md's "Real limit orders" section for the
# full casing-risk writeup) into a single small function, so a casing fix
# is a one-line change here rather than a hunt through main.py's
# on_order_event()/_process_pending_limit_order_timeouts().
PENDING_ORDER_STATUS_NAMES = ("New", "Submitted", "PartiallyFilled", "UpdateSubmitted")
TERMINAL_FILLED_STATUS_NAMES = ("Filled",)
TERMINAL_CANCELED_STATUS_NAMES = ("Canceled", "Invalid")


def classify_order_status(status_name: str) -> str:
    """Pure string classification, never raises on an unrecognized value -
    returns "unknown" instead, which callers treat as still-pending
    (conservative: never mistakes an unrecognized status for a fill)."""
    if status_name in TERMINAL_FILLED_STATUS_NAMES:
        return "filled"
    if status_name in TERMINAL_CANCELED_STATUS_NAMES:
        return "canceled"
    if status_name in PENDING_ORDER_STATUS_NAMES:
        return "pending"
    return "unknown"


# Pure classification of main.py::_apply_signal()/_apply_option_order()'s
# execution_note return strings into "was a REAL order actually placed" -
# used by the audit-log hook (development/Problems.md #42) at its single
# call site in on_data()'s Pass 2 loop, rather than scattering a push call
# across every one of _apply_signal()'s many branches/asset-class routings
# (equity/futures/option x buy/sell/short, each with its own f-string
# execution_note). An explicit denylist, not a broader heuristic, so a new
# no-op reason added to main.py in the future fails safe (gets audited as
# "real" and is easy to notice/fix) rather than silently never being
# audited if it happened to match a loose pattern.
_NO_OP_EXECUTION_NOTES = frozenset(
    {
        "kept_long",
        "kept_short",
        "already_flat",
        "cooldown_active",
        "no_action",
        "max_active_positions_reached",
        "futures_zero_contract_count",
        "options_no_usable_contract",
        "options_spread_no_usable_legs",
        # V4.3.0 - allow adding to an existing position (development/
        # Changelog.md). Plain constants only, never f-strings - this
        # denylist is exact-string matching, and an f-string note would
        # silently misclassify as a REAL placement, the wrong-direction
        # failure mode this module's own docstring warns about.
        "kept_long_futures",
        "kept_short_futures",
        "futures_zero_delta_kept",
        "options_kept",
        "options_zero_or_negative_delta_kept",
        "options_contract_drifted_kept",
        "options_spread_kept",
        "options_spread_shrink_unsupported",
        "options_spread_legs_mismatch_kept",
    }
)
_NO_OP_EXECUTION_NOTE_SUFFIXES = ("_exposure_cap_reached",)


def is_real_order_placement(execution_note: str, orders_allowed: bool) -> bool:
    """True only for a genuinely-placed real order - never a simulated/
    observation-mode fill (execution_note prefixed "simulated_") and never
    one of the known no-op/blocked outcomes above."""
    if not orders_allowed or execution_note.startswith("simulated_"):
        return False
    if execution_note in _NO_OP_EXECUTION_NOTES:
        return False
    if execution_note.endswith(_NO_OP_EXECUTION_NOTE_SUFFIXES):
        return False
    return True
