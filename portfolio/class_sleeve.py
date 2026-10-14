"""Asset-class sleeves (V5.8.0): a small, separately budgeted long/short book over ONE asset class ranked among itself.

V5.7.0 built this for forex only (`portfolio/forex_sleeve.py`). V5.8.0 needs the same structure for bonds: ranked in the
equity pool, the 22 bond ETFs mostly expressed a bonds-vs-equities market bet (within-bond holdout IC ~0) and every bond
ETF the BT7 book traded lost money. A class sleeve takes the class out of the main book's pool, ranks it among itself,
holds `per_side` longs and shorts, and funds each leg with half of its own gross budget.

Pure, no I/O, no Lean imports. `main.py` and the research scripts / simulator call the same functions.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from portfolio.book_construction import BookAllocation


@dataclass(frozen=True)
class ClassSleeveConfig:
    asset_class: str
    enabled: bool = False
    per_side: int = 2
    gross_budget: float = 0.0
    max_weight_per_name: float | None = None
    rebalance_every_bars: int = 20
    min_trade_usd: float = 0.0
    min_rank_confidence_spread: float = 0.0
    hysteresis_rank_margin: float = 0.0
    signal: str = "model_rank"  # "model_rank" (the blended live score) or "ts_momentum" (features/fx_signals.py)


def resolve_class_sleeve_config(asset_class: str, raw: dict | None) -> ClassSleeveConfig:
    """Config block (`phase_v2.<class>_sleeve`) -> ClassSleeveConfig. Absent block = disabled."""
    raw = raw or {}

    def _number(key: str, default: float) -> float:
        try:
            value = float(raw.get(key, default))
        except (TypeError, ValueError):
            return default
        return value if math.isfinite(value) else default

    max_weight = _number("max_weight_per_name", _number("max_weight_per_pair", 0.0))
    return ClassSleeveConfig(
        asset_class=str(asset_class),
        enabled=bool(raw.get("enabled", False)),
        per_side=max(1, int(_number("per_side", 2))),
        gross_budget=max(0.0, _number("gross_budget", 0.0)),
        max_weight_per_name=max_weight if max_weight > 0.0 else None,
        rebalance_every_bars=max(1, int(_number("rebalance_every_bars", 20))),
        min_trade_usd=max(0.0, _number("min_trade_usd", 0.0)),
        min_rank_confidence_spread=max(0.0, _number("min_rank_confidence_spread", 0.0)),
        hysteresis_rank_margin=max(0.0, _number("hysteresis_rank_margin", 0.0)),
        signal=str(raw.get("signal", "model_rank")) if str(raw.get("signal", "model_rank")) in ("model_rank", "ts_momentum") else "model_rank",
    )


def build_class_sleeve_weights(
    allocations: Mapping[str, BookAllocation], gross_budget: float, max_weight_per_name: float | None = None
) -> dict[str, float]:
    """Signed target weight (fraction of NAV) per selected name: each leg gets `gross_budget / 2`, split evenly over its
    names, optionally capped per name. A one-sided book (no shorts, no longs) gets {} - a class sleeve is dollar-neutral by
    construction, never a directional bet on the class. Non-finite or non-positive budget -> {}."""
    if not allocations or not math.isfinite(float(gross_budget)) or gross_budget <= 0.0:
        return {}
    longs = [symbol for symbol, allocation in allocations.items() if allocation.role == "long"]
    shorts = [symbol for symbol, allocation in allocations.items() if allocation.role == "short"]
    if not longs or not shorts:
        return {}
    cap = abs(float(max_weight_per_name)) if max_weight_per_name else None
    weights: dict[str, float] = {}
    for legs, sign in ((longs, 1.0), (shorts, -1.0)):
        per_name = (gross_budget / 2.0) / len(legs)
        if cap is not None:
            per_name = min(per_name, cap)
        weights.update({symbol: sign * per_name for symbol in legs})
    return weights


def resize_below_minimum(delta_units: float, price: float, min_trade_usd: float) -> bool:
    """True when a resize of `delta_units` at `price` is worth less than `min_trade_usd` in notional (a fixed per-order
    fee would cost more bps than the move is worth). `min_trade_usd <= 0` disables the check (False). Non-finite inputs ->
    True (do not trade on garbage)."""
    if min_trade_usd <= 0.0:
        return False
    try:
        notional = abs(float(delta_units)) * float(price)
    except (TypeError, ValueError):
        return True
    return (not math.isfinite(notional)) or notional < float(min_trade_usd)


def sleeve_classes_out_of_main_pool(configs: Mapping[str, ClassSleeveConfig], class_enabled: Mapping[str, bool]) -> frozenset[str]:
    """Asset classes that leave the main book's candidate pool: those with an enabled sleeve whose class may trade."""
    return frozenset(
        name for name, config in configs.items() if config.enabled and bool(class_enabled.get(name, True))
    )
