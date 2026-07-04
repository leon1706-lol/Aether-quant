"""Per-asset market liquidity and execution impact assessment for Aether Quant V2.

Estimates whether a target order is reasonable given the asset's observed
daily dollar volume. All thresholds are configurable via config.json
phase_v2.liquidity.

Bid-ask spread cost (V2-23.1): estimated dynamically per asset per bar via
estimate_high_low_spread() -- the Corwin & Schultz (2012) high-low spread
estimator, computed from each asset's own recent daily high/low ranges (data
already collected every bar, no bid/ask quote feed needed). TYPICAL_SPREAD_BY_TYPE
remains as a static fallback for the first bar or two of a run, before enough
high/low history has accumulated to estimate from.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

TRADING_DAYS_PER_YEAR = 252

TYPICAL_SPREAD_BY_TYPE: dict[str, float] = {
    "equity": 0.0005,
    "crypto": 0.0020,
}

# Corwin & Schultz (2012) constant: 3 - 2*sqrt(2), from the paper's alpha formula.
_CORWIN_SCHULTZ_CONSTANT = 3 - 2 * math.sqrt(2)


def estimate_high_low_spread(highs: list[float], lows: list[float]) -> float | None:
    """Corwin & Schultz (2012) high-low bid-ask spread estimator.

    Estimates the fractional bid-ask spread (e.g. 0.001 = 10 bps) from nothing
    but consecutive days' high/low ranges -- no bid/ask/fill data required.
    Computes one estimate per consecutive 2-bar window and averages them.
    Per-window estimates are clipped to 0.0 when negative, a known artifact
    of the estimator in low-volatility/noisy conditions (standard practice,
    not a bug).

    Returns None if fewer than 2 valid (positive, high >= low) bars are
    available -- callers should fall back to a static proxy in that case.
    """
    if len(highs) != len(lows) or len(highs) < 2:
        return None

    window_spreads: list[float] = []
    for index in range(len(highs) - 1):
        high_1, low_1 = float(highs[index]), float(lows[index])
        high_2, low_2 = float(highs[index + 1]), float(lows[index + 1])
        if high_1 <= 0 or low_1 <= 0 or high_2 <= 0 or low_2 <= 0:
            continue
        if high_1 < low_1 or high_2 < low_2:
            continue

        beta = math.log(high_1 / low_1) ** 2 + math.log(high_2 / low_2) ** 2
        low_min = min(low_1, low_2)
        high_max = max(high_1, high_2)
        gamma = math.log(high_max / low_min) ** 2

        alpha = (
            (math.sqrt(2 * beta) - math.sqrt(beta)) / _CORWIN_SCHULTZ_CONSTANT
            - math.sqrt(gamma / _CORWIN_SCHULTZ_CONSTANT)
        )
        spread = 2 * (math.exp(alpha) - 1) / (1 + math.exp(alpha))
        window_spreads.append(max(0.0, spread))

    if not window_spreads:
        return None

    return sum(window_spreads) / len(window_spreads)


@dataclass(frozen=True)
class LiquidityDecision:
    daily_dollar_volume: float
    order_value: float
    participation_rate: float
    estimated_slippage: float
    spread_proxy: float
    estimated_round_trip_cost: float
    liquidity_risk: str
    recommended_action: str
    adjusted_target_weight: float
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def build_liquidity_decision(
    close: float,
    volume: float,
    target_weight: float,
    portfolio_value: float,
    annualized_volatility: float,
    security_type: str = "equity",
    thin_participation_threshold: float = 0.002,
    high_impact_participation_threshold: float = 0.01,
    blocked_participation_threshold: float = 0.05,
    min_daily_dollar_volume: float = 100_000.0,
    high_impact_size_factor: float = 0.5,
    slippage_factor: float = 0.1,
    dynamic_spread: float | None = None,
) -> LiquidityDecision:
    close = float(close)
    volume = float(volume)
    target_weight = float(target_weight)
    portfolio_value = max(float(portfolio_value), 1.0)
    annualized_volatility = max(float(annualized_volatility), 0.0)
    reasons: list[str] = []

    daily_dollar_volume = close * volume
    spread_proxy = (
        float(dynamic_spread)
        if dynamic_spread is not None
        else TYPICAL_SPREAD_BY_TYPE.get(str(security_type), 0.001)
    )

    # No order to place — no liquidity concern.
    if target_weight == 0.0:
        return LiquidityDecision(
            daily_dollar_volume=daily_dollar_volume,
            order_value=0.0,
            participation_rate=0.0,
            estimated_slippage=0.0,
            spread_proxy=spread_proxy,
            estimated_round_trip_cost=spread_proxy,
            liquidity_risk="normal",
            recommended_action="allow",
            adjusted_target_weight=0.0,
            reasons=["no_order_target_weight_zero"],
        )

    # Zero or insufficient volume → blocked.
    if volume == 0.0 or daily_dollar_volume < min_daily_dollar_volume:
        reason = (
            "zero_volume" if volume == 0.0
            else f"daily_dollar_volume_below_floor_{min_daily_dollar_volume:.0f}"
        )
        reasons.append(reason)
        return LiquidityDecision(
            daily_dollar_volume=daily_dollar_volume,
            order_value=portfolio_value * abs(target_weight),
            participation_rate=1.0,
            estimated_slippage=0.0,
            spread_proxy=spread_proxy,
            estimated_round_trip_cost=spread_proxy,
            liquidity_risk="blocked",
            recommended_action="block",
            adjusted_target_weight=0.0,
            reasons=reasons,
        )

    order_value = portfolio_value * abs(target_weight)
    participation_rate = order_value / daily_dollar_volume

    daily_vol = annualized_volatility / math.sqrt(TRADING_DAYS_PER_YEAR)
    estimated_slippage = participation_rate * daily_vol * slippage_factor
    estimated_round_trip_cost = estimated_slippage + spread_proxy

    if participation_rate >= blocked_participation_threshold:
        reasons.append(f"participation_rate_{participation_rate:.4f}_exceeds_blocked_threshold")
        return LiquidityDecision(
            daily_dollar_volume=daily_dollar_volume,
            order_value=order_value,
            participation_rate=participation_rate,
            estimated_slippage=estimated_slippage,
            spread_proxy=spread_proxy,
            estimated_round_trip_cost=estimated_round_trip_cost,
            liquidity_risk="blocked",
            recommended_action="block",
            adjusted_target_weight=0.0,
            reasons=reasons,
        )

    if participation_rate >= high_impact_participation_threshold:
        reasons.append(f"participation_rate_{participation_rate:.4f}_exceeds_high_impact_threshold")
        adjusted = target_weight * high_impact_size_factor
        return LiquidityDecision(
            daily_dollar_volume=daily_dollar_volume,
            order_value=order_value,
            participation_rate=participation_rate,
            estimated_slippage=estimated_slippage,
            spread_proxy=spread_proxy,
            estimated_round_trip_cost=estimated_round_trip_cost,
            liquidity_risk="high_impact",
            recommended_action="reduce_size",
            adjusted_target_weight=adjusted,
            reasons=reasons,
        )

    if participation_rate >= thin_participation_threshold:
        reasons.append(f"participation_rate_{participation_rate:.4f}_exceeds_thin_threshold")
        return LiquidityDecision(
            daily_dollar_volume=daily_dollar_volume,
            order_value=order_value,
            participation_rate=participation_rate,
            estimated_slippage=estimated_slippage,
            spread_proxy=spread_proxy,
            estimated_round_trip_cost=estimated_round_trip_cost,
            liquidity_risk="thin",
            recommended_action="simulate_instead",
            adjusted_target_weight=target_weight,
            reasons=reasons,
        )

    reasons.append("participation_rate_within_normal_bounds")
    return LiquidityDecision(
        daily_dollar_volume=daily_dollar_volume,
        order_value=order_value,
        participation_rate=participation_rate,
        estimated_slippage=estimated_slippage,
        spread_proxy=spread_proxy,
        estimated_round_trip_cost=estimated_round_trip_cost,
        liquidity_risk="normal",
        recommended_action="allow",
        adjusted_target_weight=target_weight,
        reasons=reasons,
    )
