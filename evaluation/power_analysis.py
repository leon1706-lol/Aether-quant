"""What a t-test on an alpha can and can't show, given how much history exists (V6.6.0).

An alpha Sharpe of s over T years has a t of about s * sqrt(T), so a bar of t >= 3 is out of reach of a real but modest edge on a
short window, and a failed test proves little unless it was powerful. A refutation quotes `excluded_alpha_sharpe` instead of "no
alpha". Normal approximation throughout, with daily data's autocorrelation ignored: figures to compare, not to decimal places.
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

_NORMAL = NormalDist()


def minimum_detectable_alpha_sharpe(years: float, t_bar: float = 3.0) -> float:
    """The alpha Sharpe whose expected t just reaches `t_bar` over `years`."""
    if years <= 0.0:
        return math.inf
    return float(t_bar) / math.sqrt(years)


def power_of_t_test(alpha_sharpe: float, years: float, t_bar: float = 3.0) -> float:
    """Chance that a true alpha Sharpe of `alpha_sharpe` clears `t_bar` over `years`."""
    if years <= 0.0:
        return 0.0
    return 1.0 - _NORMAL.cdf(float(t_bar) - float(alpha_sharpe) * math.sqrt(years))


def excluded_alpha_sharpe(observed_t: float, years: float, confidence: float = 0.95) -> float:
    """One-sided upper bound on the true alpha Sharpe, given the t observed: true values above this are rejected at `confidence`."""
    if years <= 0.0:
        return math.inf
    return (float(observed_t) + _NORMAL.inv_cdf(float(confidence))) / math.sqrt(years)


def fundamental_law_ir(ic: float, names: int, rebalances_per_year: float, transfer: float = 1.0) -> float:
    """Grinold's IR = transfer * IC * sqrt(breadth), breadth = independent bets a year. Names aren't independent, so this is a ceiling."""
    breadth = max(0.0, float(names) * float(rebalances_per_year))
    return float(transfer) * float(ic) * math.sqrt(breadth)


def power_table(years_list: Sequence[float]=(3.3, 8.0, 15.8, 22.8), alpha_sharpes: Sequence[float]=(0.25, 0.5, 0.75, 1.0, 1.5), t_bar: float = 3.0) -> dict[str, Any]:
    """The table `ml/evaluation/v660/power.json` holds, written before any score of the phase exists."""
    return {
        "t_bar": t_bar,
        "minimum_detectable_alpha_sharpe": {str(years): minimum_detectable_alpha_sharpe(years, t_bar) for years in years_list},
        "power": {
            str(years): {str(sharpe): power_of_t_test(sharpe, years, t_bar) for sharpe in alpha_sharpes} for years in years_list
        },
        "fundamental_law_ir_at_ic_0_02_monthly": {
            str(names): fundamental_law_ir(0.02, names, 12.0) for names in (55, 250, 500)
        },
    }
