"""Where does the offline simulator part ways with Lean? (V6.4.3, rule R-CAL4)

`scripts/lean_calibration.py` runs the as-live simulator as a ladder of increasingly live-like variants against a
finished Lean run. This module reads such a report and decomposes what is left of the gap:

- `rung_attribution`: the daily-correlation and return-gap change each rung of the ladder buys, so the mechanism that
  closes most of the gap (cadence phase, next-open fills, fee floor, live gates, topology sizing, ...) is named;
- `daily_gap_breakdown`: on two aligned daily return series, the tracking error, the share of the squared gap carried
  by the worst days, the gap's autocorrelation (a persistent gap is a modelling difference, a noisy one is fills) and
  the gap on rebalance days against the days in between;
- `gap_report`: both for every window of a calibration report.
Pure; no I/O.
"""

from __future__ import annotations

import numpy as np
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

LADDER_ORDER = ("v580", "phase", "next_open", "min_fee", "live_gates", "calibrated", "v610_member_pass", "v610_mechanisms", "v610")


def rung_attribution(variants: dict[str, dict], order: Sequence[str]=LADDER_ORDER) -> list[dict]:
    """[{"rung", "daily_correlation", "delta_correlation", "annual_return_gap", "delta_gap"}] along the ladder."""
    rows, previous = [], None
    for name in order:
        row = variants.get(name)
        if not row:
            continue
        correlation, gap = row.get("daily_correlation"), row.get("annual_return_gap")
        entry = {"rung": name, "daily_correlation": correlation, "annual_return_gap": gap,
                 "decision_agreement": row.get("decision_agreement"), "weight_l1": row.get("weight_l1"),
                 "name_overlap": row.get("name_overlap")}
        if previous is not None:
            entry["delta_correlation"] = (correlation - previous["daily_correlation"]
                                          if correlation is not None and previous["daily_correlation"] is not None else None)
            entry["delta_gap"] = (abs(gap) - abs(previous["annual_return_gap"])
                                  if gap is not None and previous["annual_return_gap"] is not None else None)
        rows.append(entry)
        previous = entry
    return rows


def daily_gap_breakdown(lean: dict[str, float], offline: dict[str, float], *, rebalance_dates: Iterable[str]=(), worst_share: float = 0.05) -> dict[str, Any]:
    """Statistics of the daily gap offline - lean over their common dates."""
    common = sorted(set(lean) & set(offline))
    if len(common) < 3:
        return {"days": len(common)}
    a = np.array([offline[d] for d in common], dtype=float)
    b = np.array([lean[d] for d in common], dtype=float)
    gap = a - b
    squared = gap**2
    k = max(1, int(round(len(gap) * worst_share)))
    worst = np.argsort(squared)[::-1][:k]
    rebalance = np.array([d in set(rebalance_dates) for d in common])
    autocorrelation = float(np.corrcoef(gap[:-1], gap[1:])[0, 1]) if gap[:-1].std() > 0 and gap[1:].std() > 0 else None
    out = {
        "days": len(common),
        "daily_correlation": float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else None,
        "tracking_error_annual": float(gap.std(ddof=1) * np.sqrt(252)),
        "mean_gap_annual": float(gap.mean() * 252),
        "worst_days_share_of_squared_gap": float(squared[worst].sum() / squared.sum()) if squared.sum() > 0 else 0.0,
        "worst_days": [{"date": common[i], "offline": float(a[i]), "lean": float(b[i])} for i in worst[:10]],
        "gap_autocorrelation": autocorrelation,
    }
    if rebalance.any() and (~rebalance).any():
        out["mean_abs_gap_rebalance_days"] = float(np.abs(gap[rebalance]).mean())
        out["mean_abs_gap_other_days"] = float(np.abs(gap[~rebalance]).mean())
    return out


def gap_report(calibration: dict[str, Any], *, variant: str = "calibrated") -> dict[str, Any]:
    """{window: {"ladder": rung_attribution, "best_rung", "judged": the `variant` row}} for a lean_calibration.py report."""
    out = {}
    for name, window in (calibration.get("windows") or {}).items():
        variants = window.get("variants") or {}
        ladder = rung_attribution(variants)
        scored = [row for row in ladder if row.get("daily_correlation") is not None]
        out[name] = {
            "ladder": ladder,
            "best_rung": max(scored, key=lambda row: row["daily_correlation"])["rung"] if scored else None,
            "judged": variants.get(variant),
        }
    return out
