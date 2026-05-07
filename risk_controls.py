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
