"""Trend sleeve (V6.4.4): a small directional time-series-momentum book next to the market-neutral one.

Time-series momentum (Moskowitz, Ooi & Pedersen 2012) is the one classic alpha source the project lacked: each
instrument is held long when its own trailing return is positive and short when negative, sized by inverse volatility
so every name contributes a similar risk, the whole sleeve aimed at `target_vol` of NAV a year. The instruments
(`symbols`: broad equity indices, Treasuries, oil) leave the main book's and the bond sleeve's pools while it is on, so
each symbol has one owner.

Pure, no I/O, no Lean imports. `main.py` and `evaluation/trend_sleeve_backtest.py` call the same functions.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

TREND_SIGNALS = ("sign_252", "sign_126", "sign_63", "sign_blend")
BLEND_LOOKBACKS = (63, 126, 252)


@dataclass(frozen=True)
class TrendSleeveConfig:
    """Settings of the trend sleeve: on or off, its symbols, the signal and the volatility target."""
    enabled: bool = False
    symbols: tuple[str, ...] = ()
    signal: str = "sign_252"
    target_vol: float = 0.03
    vol_window: int = 60
    max_weight_per_name: float = 0.08
    gross_cap: float = 0.25
    rebalance_every_bars: int = 20
    min_weight_change: float = 0.005

    @property
    def history_needed(self) -> int:
        """Closes a symbol needs before it can carry a signal and a volatility."""
        return max(max(signal_lookbacks(self.signal)), self.vol_window) + 1


def signal_lookbacks(signal: str) -> tuple[int, ...]:
    """The lookbacks a trend signal name stands for (`sign_252` is 252; `sign_blend` the blend's)."""
    if signal == "sign_blend":
        return BLEND_LOOKBACKS
    return (int(signal.split("_", 1)[1]),)


def resolve_trend_sleeve_config(raw: Mapping | None) -> TrendSleeveConfig:
    """`phase_v2.trend_sleeve` -> TrendSleeveConfig. Absent block = disabled; a malformed number keeps its default."""
    raw = raw or {}
    defaults = TrendSleeveConfig()

    def _number(key: str, default: float, minimum: float) -> float:
        try:
            value = float(raw.get(key, default))
        except (TypeError, ValueError):
            return default
        return value if math.isfinite(value) and value >= minimum else default

    signal = str(raw.get("signal", defaults.signal))
    symbols = raw.get("symbols") or ()
    return TrendSleeveConfig(
        enabled=bool(raw.get("enabled", False)),
        symbols=tuple(str(symbol) for symbol in symbols) if isinstance(symbols, (list, tuple)) else (),
        signal=signal if signal in TREND_SIGNALS else defaults.signal,
        target_vol=_number("target_vol", defaults.target_vol, 0.0),
        vol_window=int(_number("vol_window", defaults.vol_window, 2)),
        max_weight_per_name=_number("max_weight_per_name", defaults.max_weight_per_name, 0.0),
        gross_cap=_number("gross_cap", defaults.gross_cap, 0.0),
        rebalance_every_bars=int(_number("rebalance_every_bars", defaults.rebalance_every_bars, 1)),
        min_weight_change=_number("min_weight_change", defaults.min_weight_change, 0.0),
    )


def _clean(closes: Sequence[float]) -> list[float] | None:
    values = []
    for value in closes:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number) or number <= 0.0:
            return None
        values.append(number)
    return values


def trend_signal(closes: Sequence[float], signal: str) -> float | None:
    """sign_N: the sign of the trailing N-session log return (-1, 0, +1); sign_blend: the mean of sign_63/126/252.
    None when the history is shorter than the longest lookback + 1 or holds a non-finite / non-positive close."""
    if signal not in TREND_SIGNALS:
        return None
    lookbacks = signal_lookbacks(signal)
    values = _clean(closes[-(max(lookbacks) + 1):]) if len(closes) >= max(lookbacks) + 1 else None
    if values is None:
        return None
    signs = []
    for lookback in lookbacks:
        change = math.log(values[-1] / values[-1 - lookback])
        signs.append(0.0 if change == 0.0 else math.copysign(1.0, change))
    return sum(signs) / len(signs)


def annualised_vol(closes: Sequence[float], window: int, annualization: float = 252.0) -> float | None:
    """Sample std of the last `window` daily log returns x sqrt(annualization); None if too short, flat or invalid."""
    if len(closes) < window + 1:
        return None
    values = _clean(closes[-(window + 1):])
    if values is None:
        return None
    returns = [math.log(values[i] / values[i - 1]) for i in range(1, len(values))]
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    vol = math.sqrt(variance) * math.sqrt(annualization)
    return vol if math.isfinite(vol) and vol > 0.0 else None


def trend_sleeve_weights(
    closes_by_symbol: Mapping[str, Sequence[float]], config: TrendSleeveConfig, *, annualization: float = 252.0
) -> dict[str, float]:
    """Signed target weight (fraction of NAV) per symbol of `config.symbols` with a non-zero signal and a volatility:
    w = s * (target_vol / sqrt(N_active)) / sigma, each |w| capped at max_weight_per_name, then all scaled down so that
    sum |w| <= gross_cap. {} when disabled or nothing qualifies."""
    if not config.enabled or config.target_vol <= 0.0:
        return {}
    active: dict[str, tuple[float, float]] = {}
    for symbol in config.symbols:
        closes = closes_by_symbol.get(symbol)
        if not closes:
            continue
        signal = trend_signal(closes, config.signal)
        vol = annualised_vol(closes, config.vol_window, annualization)
        if signal is None or vol is None or signal == 0.0:
            continue
        active[symbol] = (signal, vol)
    if not active:
        return {}
    per_name_vol = config.target_vol / math.sqrt(len(active))
    weights = {}
    for symbol, (signal, vol) in active.items():
        weight = signal * per_name_vol / vol
        cap = config.max_weight_per_name
        weights[symbol] = max(-cap, min(cap, weight))
    gross = sum(abs(weight) for weight in weights.values())
    if config.gross_cap <= 0.0:
        return {}
    if gross > config.gross_cap:
        scale = config.gross_cap / gross
        weights = {symbol: weight * scale for symbol, weight in weights.items()}
    return {symbol: weight for symbol, weight in weights.items() if weight != 0.0}


def apply_min_change(previous: Mapping[str, float], target: Mapping[str, float], min_change: float) -> dict[str, float]:
    """Keeps a held weight when the new target moves it by less than `min_change` (fewer small, fee-heavy trades). A
    symbol whose target is missing or zero always closes; a new symbol always opens."""
    out: dict[str, float] = {}
    for symbol, weight in target.items():
        if not math.isfinite(float(weight)) or weight == 0.0:
            continue
        held = previous.get(symbol)
        if held is not None and held != 0.0 and abs(float(weight) - float(held)) < float(min_change) \
                and math.copysign(1.0, held) == math.copysign(1.0, weight):
            out[symbol] = float(held)
        else:
            out[symbol] = float(weight)
    return out
