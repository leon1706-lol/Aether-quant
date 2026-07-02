"""Pure, Lean-free order gating for Phase V2-15 (Observation Mode).

No imports from AlgorithmImports/QCAlgorithm live here on purpose: this
module owns the mode -> real-vs-simulated order decision table and must be
unit-testable without a Lean runtime on sys.path.
"""

from __future__ import annotations

VALID_MODES = ("backtest", "observation", "paper", "live")
DEFAULT_FALLBACK_MODE = "observation"


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

    slippage_factor = 1.0 + (slippage_bps / 10_000.0)
    fill_price = close_price * slippage_factor
    notional = target_weight * equity
    quantity = notional / fill_price

    return {
        "fill_price": fill_price,
        "notional": notional,
        "quantity": quantity,
    }
