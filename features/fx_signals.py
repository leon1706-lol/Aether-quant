"""Alternative forex sleeve signals (V5.8.0).

The pooled model has no cross-sectional forex edge (within-pool rank IC -0.07 with or without `fx_carry_3m`, Problems
#151), so the forex sleeve can rank the pairs by one of the two classic currency factors instead:

  * `carry`        - the 3-month rate differential r_base - r_quote (`features/fx_carry.py`), point-in-time,
  * `ts_momentum`  - the vol-scaled trailing return over `lookbacks` (default 60 and 120 sessions), averaged,
  * `carry_momentum` - the mean of the two cross-sectional z-scores.

`model_rank` keeps the model's own score (the V5.7.0 behaviour). Every score is "higher = long". Pure; `main.py` passes
the live windows, the research script passes dataset history, both call `fx_sleeve_scores`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

FX_SIGNALS = ("model_rank", "carry", "ts_momentum", "carry_momentum")
DEFAULT_MOMENTUM_LOOKBACKS = (60, 120)


def ts_momentum_score(closes: Sequence[float], lookbacks: Sequence[int] = DEFAULT_MOMENTUM_LOOKBACKS, vol_window: int = 60) -> float | None:
    """Mean over `lookbacks` of the trailing log return divided by (daily log-return std x sqrt(lookback)) - a t-like,
    vol-comparable momentum across pairs with very different volatility (EURCHF vs AUDJPY). None when the window is
    shorter than the longest lookback + 1 or the volatility is zero/non-finite."""
    values = [float(value) for value in closes if value is not None and math.isfinite(float(value)) and float(value) > 0.0]
    longest = max(int(lb) for lb in lookbacks)
    if len(values) < longest + 1:
        return None
    logs = [math.log(value) for value in values]
    returns = [logs[i] - logs[i - 1] for i in range(1, len(logs))]
    recent = returns[-vol_window:]
    if len(recent) < 2:
        return None
    mean = sum(recent) / len(recent)
    variance = sum((value - mean) ** 2 for value in recent) / (len(recent) - 1)
    daily_vol = math.sqrt(variance)
    if not math.isfinite(daily_vol) or daily_vol <= 0.0:
        return None
    scores = []
    for lookback in lookbacks:
        trailing = logs[-1] - logs[-1 - int(lookback)]
        scores.append(trailing / (daily_vol * math.sqrt(int(lookback))))
    return float(sum(scores) / len(scores))


def _zscores(values: Mapping[str, float]) -> dict[str, float]:
    finite = {key: float(value) for key, value in values.items() if value is not None and math.isfinite(float(value))}
    if len(finite) < 2:
        return {key: 0.0 for key in finite}
    mean = sum(finite.values()) / len(finite)
    std = math.sqrt(sum((value - mean) ** 2 for value in finite.values()) / (len(finite) - 1))
    if std <= 0.0 or not math.isfinite(std):
        return {key: 0.0 for key in finite}
    return {key: (value - mean) / std for key, value in finite.items()}


def fx_sleeve_scores(
    signal: str,
    *,
    model_scores: Mapping[str, float] | None = None,
    closes_by_pair: Mapping[str, Sequence[float]] | None = None,
    carry_by_pair: Mapping[str, float] | None = None,
    lookbacks: Sequence[int] = DEFAULT_MOMENTUM_LOOKBACKS,
    vol_window: int = 60,
) -> dict[str, float]:
    """{pair: score} for the requested `signal` over the pairs that have the inputs it needs (a pair without inputs is
    left out, never scored 0). An unknown signal raises ValueError (config typo must not trade silently)."""
    if signal not in FX_SIGNALS:
        raise ValueError(f"unknown forex sleeve signal {signal!r}; expected one of {FX_SIGNALS}")
    if signal == "model_rank":
        return {k: float(v) for k, v in (model_scores or {}).items() if v is not None and math.isfinite(float(v))}
    carry = {k: float(v) for k, v in (carry_by_pair or {}).items() if v is not None and math.isfinite(float(v))}
    momentum: dict[str, float] = {}
    for pair, closes in (closes_by_pair or {}).items():
        score = ts_momentum_score(closes, lookbacks, vol_window)
        if score is not None:
            momentum[pair] = score
    if signal == "carry":
        return carry
    if signal == "ts_momentum":
        return momentum
    common = set(carry) & set(momentum)
    carry_z = _zscores({k: carry[k] for k in common})
    momentum_z = _zscores({k: momentum[k] for k in common})
    return {pair: 0.5 * (carry_z[pair] + momentum_z[pair]) for pair in common}


def ts_momentum_series(closes, lookbacks: Sequence[int] = DEFAULT_MOMENTUM_LOOKBACKS, vol_window: int = 60):
    """ts_momentum_score() evaluated at every position of a close series (a pandas Series), vectorised for research
    over thousands of rows: position i equals ts_momentum_score(closes[:i + 1]). NaN where the scalar returns None.
    pandas is imported here so the live path never pays for it."""
    import numpy as np  # noqa: PLC0415
    import pandas as pd  # noqa: PLC0415

    values = pd.Series(closes, dtype=float)
    logs = np.log(values.where(values > 0))
    daily = logs.diff()
    daily_vol = daily.rolling(vol_window, min_periods=2).std(ddof=1)
    scores = []
    for lookback in lookbacks:
        trailing = logs - logs.shift(int(lookback))
        scores.append(trailing / (daily_vol * math.sqrt(int(lookback))))
    result = sum(scores) / len(scores)
    longest = max(int(lb) for lb in lookbacks)
    result[(daily_vol <= 0) | (~np.isfinite(daily_vol))] = np.nan
    result.iloc[:longest] = np.nan
    return result
