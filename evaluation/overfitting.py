"""Overfitting tests beyond PBO and the deflated Sharpe (V6.6.5, #345): how long a record must be, and how much of a
Sharpe ratio survives the number of trials that produced it.

- `minimum_track_record_length`: Bailey & López de Prado (2012), "The Sharpe Ratio Efficient Frontier", eq. for MinTRL.
- `haircut_sharpe`: Harvey & Liu (2015), "Backtesting", the Bonferroni, Holm and BHY adjustments of a Sharpe ratio's
  p-value, for a strategy that is the best of `num_trials` (rank 1; the other trials' p-values are not needed then).
- `pbo` is `evaluation.pbo.probability_of_backtest_overfitting` (CSCV), under a short name.

Only the standard library and numpy: `statistics.NormalDist` gives the normal quantiles.
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import TYPE_CHECKING, Literal

import numpy as np

from evaluation.pbo import probability_of_backtest_overfitting

if TYPE_CHECKING:
    from numpy.typing import ArrayLike

__all__ = ["minimum_track_record_length", "haircut_sharpe", "pbo"]

pbo = probability_of_backtest_overfitting
_NORMAL = NormalDist()


def _clean(returns) -> np.ndarray:
    values = np.asarray(returns, dtype=float).ravel()
    return values[np.isfinite(values)]


def minimum_track_record_length(returns: ArrayLike, *, target_sharpe: float = 0.0, confidence: float = 0.95, periods_per_year: int = 252) -> float:
    """Observations needed before the observed Sharpe beats `target_sharpe` (annual) at `confidence`, given the series'
    skew and kurtosis: `1 + (1 - g3*SR + (g4-1)/4*SR^2) * (z / (SR - SR*))^2` with per-period SR and raw kurtosis g4.
    `inf` when the observed Sharpe does not exceed the target; `nan` for fewer than 3 finite observations or zero variance."""
    values = _clean(returns)
    if len(values) < 3 or not 0.0 < float(confidence) < 1.0:
        return float("nan")
    sd = float(values.std(ddof=1))
    if not math.isfinite(sd) or sd == 0.0:
        return float("nan")
    sr = float(values.mean()) / sd
    target = float(target_sharpe) / math.sqrt(float(periods_per_year))
    if sr <= target:
        return float("inf")
    centred = values - values.mean()
    m2 = float(np.mean(centred**2))
    skew = float(np.mean(centred**3)) / m2**1.5
    kurtosis = float(np.mean(centred**4)) / m2**2
    z = _NORMAL.inv_cdf(float(confidence))
    return 1.0 + (1.0 - skew * sr + (kurtosis - 1.0) / 4.0 * sr**2) * (z / (sr - target)) ** 2


def haircut_sharpe(sharpe: float, n_obs: int, num_trials: int, *, method: Literal["bonferroni", "holm", "bhy"] = "bhy",
                   periods_per_year: int = 252) -> dict[str, float]:
    """The annual Sharpe that survives `num_trials`: its t-statistic `SR * sqrt(n_obs / periods_per_year)`, the two-sided
    p-value, the p-value adjusted for multiple testing, and the Sharpe implied by the adjusted p-value.

    At rank 1, Holm equals Bonferroni (`p * M`) and BHY multiplies by `M * c(M)` with `c(M) = sum(1/i)`. Returns
    `{"sharpe", "haircut_sharpe", "haircut", "t_stat", "p_value", "adjusted_p_value"}`; a non-positive Sharpe gets a 100% haircut."""
    if method not in ("bonferroni", "holm", "bhy"):
        raise ValueError("method must be 'bonferroni', 'holm' or 'bhy'")
    trials = max(int(num_trials), 1)
    years = max(float(n_obs), 0.0) / float(periods_per_year)
    sr = float(sharpe)
    if not math.isfinite(sr) or years <= 0.0:
        return {"sharpe": sr, "haircut_sharpe": 0.0, "haircut": 1.0, "t_stat": 0.0, "p_value": 1.0, "adjusted_p_value": 1.0}
    t_stat = sr * math.sqrt(years)
    p_value = 2.0 * (1.0 - _NORMAL.cdf(abs(t_stat)))
    factor = float(trials)
    if method == "bhy":
        factor *= sum(1.0 / i for i in range(1, trials + 1))
    adjusted = min(p_value * factor, 1.0)
    if sr <= 0.0 or adjusted >= 1.0:
        haircut_sr = 0.0
    else:
        haircut_sr = _NORMAL.inv_cdf(1.0 - adjusted / 2.0) / math.sqrt(years)
    haircut_sr = min(haircut_sr, sr) if sr > 0 else 0.0
    return {
        "sharpe": sr, "haircut_sharpe": haircut_sr, "haircut": 1.0 - haircut_sr / sr if sr > 0 else 1.0,
        "t_stat": t_stat, "p_value": p_value, "adjusted_p_value": adjusted,
    }
