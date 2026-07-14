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
