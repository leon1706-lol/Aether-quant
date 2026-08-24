"""V5.4.2 - Almgren-style sqrt market-impact model.

Replaces flat bps-per-side costs with a volume-participation-dependent
impact estimate when enabled. The core formula follows Almgren et al.
(2005): temporary price impact scales with the square root of the
participation rate (trade size / average daily volume), modulated by
the asset's own daily volatility.

    impact_bps = eta × sigma_daily × sqrt(|trade_size / ADV|)

where:
- eta: calibrated impact coefficient (higher = more illiquid asset class)
- sigma_daily: rolling daily volatility of the asset (fraction, not %)
- trade_size / ADV: participation rate (fraction of daily volume consumed)

Pure: numpy only, no I/O, deterministic given inputs."""

from __future__ import annotations

import math


def compute_sqrt_impact_bps(
    *,
    trade_size_fraction: float,
    daily_volatility: float,
    avg_daily_dollar_volume: float,
    portfolio_value: float,
    eta: float = 0.5,
) -> float:
    """Computes temporary market impact in basis points.

    Args:
        trade_size_fraction: absolute weight change (e.g. 0.05 = 5% of book).
        daily_volatility: rolling daily return std (e.g. 0.02 = 2%).
        avg_daily_dollar_volume: asset's ADV in dollars (e.g. 50_000_000).
        portfolio_value: total book value in dollars.
        eta: impact coefficient — higher for less liquid assets.
             Calibrated defaults: equity ~0.5, crypto ~1.0, bond ETF ~0.3.

    Returns:
        Impact cost in basis points (always >= 0). Zero when any input is
        degenerate (zero size, zero ADV, zero vol)."""
    if trade_size_fraction <= 0 or avg_daily_dollar_volume <= 0 or portfolio_value <= 0:
        return 0.0
    if daily_volatility <= 0:
        return 0.0

    trade_dollars = trade_size_fraction * portfolio_value
    participation_rate = abs(trade_dollars / avg_daily_dollar_volume)

    impact_fraction = eta * daily_volatility * math.sqrt(participation_rate)
    return max(0.0, impact_fraction * 1e4)


def compute_participation_rate(
    *,
    trade_size_fraction: float,
    portfolio_value: float,
    avg_daily_dollar_volume: float,
) -> float:
    """Fraction of the asset's ADV consumed by this trade (0 when degenerate)."""
    if avg_daily_dollar_volume <= 0 or portfolio_value <= 0:
        return 0.0
    return abs(trade_size_fraction * portfolio_value / avg_daily_dollar_volume)


# Per-security-type default eta values (calibrated from literature ranges;
# refine per-asset once real fill data exists).
DEFAULT_ETA_BY_SECURITY_TYPE: dict[str, float] = {
    "equity": 0.5,
    "crypto": 1.0,
    "bond": 0.3,
    "forex": 0.1,
    "future": 0.4,
    "option": 0.8,
}
