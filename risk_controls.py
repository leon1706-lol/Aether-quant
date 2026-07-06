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
