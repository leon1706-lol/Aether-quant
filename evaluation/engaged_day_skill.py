"""Rank skill on the days the rolling-IC gate lets the book trade (V6.4.0, lead L1). Pure given a scored frame.

The gate vetoes most rebalances, so the pooled IC (~0.05) mixes days the book trades with days it sits out. The question
is whether the engaged days carry clearly more skill than all days (then the gate protects capital) or the same (then it
hides weakness). This module splits a scored frame by the gate's per-date verdict and reports, for each subset, the daily
rank IC (mean, non-overlapping mean, HAC t), the top-N / bottom-N spread of the forward return, and, from a simulated
as-live run, the Sharpe of the days whose most recent rebalance was engaged against all days.
"""

from __future__ import annotations

import math
import statistics

import numpy as np
import pandas as pd

from evaluation.gate_audit import daily_rank_ic
from evaluation.rank_ic_core import newey_west_t_stat

# the owner's pre-set margins: the gate protects capital only if engaged days beat all days by this much on both splits
MIN_IC_MARGIN = 0.02
MIN_SHARPE_MARGIN = 0.15


def gate_labels(gate_fn, dates) -> dict[str, bool]:
    """{date: the rolling-IC gate engaged}; `gate_fn(date)` is `AsLiveHarness.gate_for(...)`'s callable."""
    return {str(date): bool((gate_fn(str(date)) or {}).get("engaged", False)) for date in dates}


def _non_overlapping(values: dict[str, float], calendar: list[str], horizon: int) -> list[float]:
    """Greedy sample of `values` at least `horizon` sessions apart on `calendar` (labels of nearer dates share a window)."""
    position = {day: index for index, day in enumerate(calendar)}
    chosen, last = [], None
    for day in sorted(values, key=lambda d: position.get(d, math.inf)):
        index = position.get(day)
        if index is None or (last is not None and index - last < horizon):
            continue
        chosen.append(values[day])
        last = index
    return chosen


def _spread(day: pd.DataFrame, score_column: str, forward_column: str, top_n: int, bottom_n: int) -> float | None:
    day = day[[score_column, forward_column]].dropna()
    if len(day) < top_n + bottom_n:
        return None
    ordered = day.sort_values(score_column)
    return float(ordered[forward_column].tail(top_n).mean() - ordered[forward_column].head(bottom_n).mean())


def subset_skill(frame: pd.DataFrame, dates: set[str] | None, calendar: list[str], *, score_column: str, target_column: str,
                 forward_column: str, top_n: int, bottom_n: int, horizon: int, min_names: int) -> dict:
    """Skill over `dates` (None = every date of the frame)."""
    data = frame
    if dates is not None:
        data = frame[frame["date"].astype(str).str[:10].isin(dates)]
    ics = daily_rank_ic(data, score_column=score_column, target_column=target_column, min_names_per_date=min_names)
    spreads = [
        value for _day, part in data.groupby(data["date"].astype(str).str[:10], sort=True)
        if (value := _spread(part, score_column, forward_column, top_n, bottom_n)) is not None
    ]
    sampled = _non_overlapping(ics, calendar, horizon)
    return {
        "n_dates": len(ics),
        "daily_mean_ic": float(np.mean(list(ics.values()))) if ics else None,
        "non_overlapping_mean_ic": float(np.mean(sampled)) if sampled else None,
        "non_overlapping_n": len(sampled),
        "hac_t": float(newey_west_t_stat(list(ics.values()), horizon - 1)) if len(ics) > 1 else None,
        "long_short_spread": float(np.mean(spreads)) if spreads else None,
    }


def engaged_vs_all(frame: pd.DataFrame, labels: dict[str, bool], *, score_column: str = "live_rank_score",
                   target_column: str = "target_rank_20d", forward_column: str = "target_return_20d", top_n: int = 6,
                   bottom_n: int = 6, horizon: int = 20, min_names: int = 10) -> dict:
    """{"all", "engaged", "vetoed"} skill dicts plus the IC difference; `labels` from `gate_labels`. Dates the gate has no
    verdict on count as vetoed."""
    calendar = sorted(set(frame["date"].astype(str).str[:10]))
    engaged = {day for day in calendar if labels.get(day, False)}
    vetoed = set(calendar) - engaged
    kwargs = dict(score_column=score_column, target_column=target_column, forward_column=forward_column, top_n=top_n,
                  bottom_n=bottom_n, horizon=horizon, min_names=min_names)
    result = {"all": subset_skill(frame, None, calendar, **kwargs),
              "engaged": subset_skill(frame, engaged, calendar, **kwargs) if engaged else None,
              "vetoed": subset_skill(frame, vetoed, calendar, **kwargs) if vetoed else None,
              "engaged_dates": len(engaged), "vetoed_dates": len(vetoed)}
    one, other = (result["engaged"] or {}).get("daily_mean_ic"), result["all"]["daily_mean_ic"]
    result["ic_margin"] = None if one is None or other is None else one - other
    return result


def sharpe(series, periods: int = 252) -> float | None:
    values = [float(value) for value in series if value is not None and math.isfinite(value)]
    if len(values) < 3:
        return None
    std = statistics.stdev(values)
    return None if std <= 0.0 else statistics.fmean(values) / std * math.sqrt(periods)


def engaged_window_returns(per_date_net_return: dict[str, float], rebalance_log: list[dict]) -> tuple[list[float], list[float]]:
    """(returns on days whose most recent rebalance was engaged, every day's return): each day belongs to the latest
    rebalance on or before it. `rebalance_log` = the simulator's [{"date", "engaged", ...}]."""
    entries = sorted(((str(entry["date"])[:10], bool(entry.get("engaged"))) for entry in rebalance_log), key=lambda e: e[0])
    engaged_returns, all_returns = [], []
    pointer, current = 0, None
    for day in sorted(per_date_net_return):
        while pointer < len(entries) and entries[pointer][0] <= day:
            current = entries[pointer][1]
            pointer += 1
        all_returns.append(per_date_net_return[day])
        if current:
            engaged_returns.append(per_date_net_return[day])
    return engaged_returns, all_returns


def l1_verdict(per_split: dict[str, dict]) -> dict:
    """The owner's bar: on BOTH splits the engaged days beat all days by >= +0.02 IC and >= +0.15 Sharpe (median across
    rebalance phases). `per_split` = {split: {"ic_margin": float | None, "sharpe_margin": float | None}}."""
    checks = {}
    for split, values in per_split.items():
        checks[split] = {
            "ic_margin_ge_0.02": values.get("ic_margin") is not None and values["ic_margin"] >= MIN_IC_MARGIN,
            "sharpe_margin_ge_0.15": values.get("sharpe_margin") is not None and values["sharpe_margin"] >= MIN_SHARPE_MARGIN,
        }
    passed = bool(checks) and all(all(split.values()) for split in checks.values())
    return {"checks": checks, "gate_protects_capital": passed,
            "reading": "the gate protects capital" if passed else "the gate hides weakness, not protects capital"}
