"""Rolling-IC gate audit (V5.8.0, todo lead 1).

On the 2021-25 holdout the idealized book earned +0.55 Sharpe while the as-live book lost -0.21: the rolling-IC gate
vetoed 513 of 630 rebalances although the pooled rank IC was +0.055 (HAC t 3.95). A gate that sees a positive signal and
still vetoes four rebalances in five is either measuring something else or measuring it late. This module puts the gate's
own reading next to what it is supposed to estimate, date by date:

  * `state_mean_ic` - what `compute_rolling_ic_state` (the live function, via the incremental offline state) reports,
  * `resolved_trailing_ic` - the mean of the FULLY resolved daily IC (dataset rank target, every name) over the same
    number of trailing origin dates whose horizon has elapsed by that date - the quantity the gate estimates,
  * `forward_ic` - the daily IC of the decision date itself (known only later), i.e. whether a veto was right.

Summary: veto share, false-veto share (vetoed although the forward IC was positive), the correlation between the gate's
reading and the resolved trailing IC, and the mean gap between them. Pure pandas/numpy, no I/O.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def daily_rank_ic(
    frame: pd.DataFrame,
    *,
    score_column: str,
    target_column: str,
    date_column: str = "date",
    min_names_per_date: int = 10,
) -> dict[str, float]:
    """{date: Spearman IC of the score against the (already per-date ranked) target}, dates under the name floor or with
    no variance skipped."""
    out: dict[str, float] = {}
    data = frame[[date_column, score_column, target_column]].dropna()
    for date, day in data.groupby(date_column, sort=True):
        if len(day) < min_names_per_date:
            continue
        score_rank = day[score_column].rank().to_numpy()
        target_rank = day[target_column].rank().to_numpy()
        if np.ptp(score_rank) == 0.0 or np.ptp(target_rank) == 0.0:
            continue
        value = float(np.corrcoef(score_rank, target_rank)[0, 1])
        if np.isfinite(value):
            out[str(date)[:10]] = value
    return out


def resolved_trailing_ic(
    daily_ic: dict[str, float], trading_dates: list[str], *, horizon: int, window: int
) -> dict[str, float | None]:
    """For each date D in `trading_dates` (the equity-session calendar), the mean daily IC over the `window` most recent
    origin dates whose `horizon`-session forward window ended strictly before D - what a perfect, fully resolved trailing
    gate would read on D."""
    positions = {date: index for index, date in enumerate(trading_dates)}
    ic_dates = sorted(date for date in daily_ic if date in positions)
    ic_positions = np.array([positions[date] for date in ic_dates], dtype=int)
    ic_values = np.array([daily_ic[date] for date in ic_dates], dtype=float)
    out: dict[str, float | None] = {}
    for date in trading_dates:
        cutoff = positions[date] - horizon  # origin + horizon < D  <=>  origin <= D - horizon - 1
        eligible = np.nonzero(ic_positions < cutoff)[0]
        if len(eligible) == 0:
            out[date] = None
            continue
        tail = eligible[-window:]
        out[date] = float(ic_values[tail].mean())
    return out


def audit_rolling_ic_gate(
    *,
    decision_dates: list[str],
    gate_fn,
    state_fn,
    daily_ic: dict[str, float],
    trading_dates: list[str],
    horizon: int,
    window: int,
) -> dict:
    """`gate_fn(date) -> evaluate_rolling_ic_gate() dict`, `state_fn(date) -> compute_rolling_ic_state() dict` (the same
    objects the as-live simulator uses). `decision_dates` are the rebalance dates to audit."""
    trailing = resolved_trailing_ic(daily_ic, trading_dates, horizon=horizon, window=window)
    rows = []
    for date in decision_dates:
        key = str(date)[:10]
        state = state_fn(key) or {}
        verdict = gate_fn(key) or {}
        rows.append(
            {
                "date": key,
                "engaged": bool(verdict.get("engaged", True)),
                "reason": verdict.get("reason"),
                "state_mean_ic": state.get("rolling_mean_ic"),
                "state_resolved_dates": state.get("num_resolved_dates"),
                "state_resolved_observations": state.get("num_resolved_observations"),
                "resolved_trailing_ic": trailing.get(key),
                "forward_ic": daily_ic.get(key),
            }
        )
    vetoed = [row for row in rows if not row["engaged"]]
    false_vetoes = [row for row in vetoed if row["forward_ic"] is not None and row["forward_ic"] > 0]
    true_vetoes = [row for row in vetoed if row["forward_ic"] is not None and row["forward_ic"] <= 0]
    paired = [
        (row["state_mean_ic"], row["resolved_trailing_ic"])
        for row in rows
        if row["state_mean_ic"] is not None and row["resolved_trailing_ic"] is not None
    ]
    correlation = None
    mean_gap = None
    if len(paired) >= 3:
        state_values, resolved_values = map(np.asarray, zip(*paired))
        if np.std(state_values) > 0 and np.std(resolved_values) > 0:
            correlation = float(np.corrcoef(state_values, resolved_values)[0, 1])
        mean_gap = float(np.mean(state_values - resolved_values))
    resolved_would_veto = [
        row for row in rows if row["resolved_trailing_ic"] is not None and row["resolved_trailing_ic"] < 0.0
    ]
    forward = [row["forward_ic"] for row in rows if row["forward_ic"] is not None]
    return {
        "num_decisions": len(rows),
        "num_vetoed": len(vetoed),
        "veto_share": (len(vetoed) / len(rows)) if rows else None,
        "num_false_vetoes": len(false_vetoes),
        "false_veto_share_of_vetoes": (len(false_vetoes) / len(vetoed)) if vetoed else None,
        "num_true_vetoes": len(true_vetoes),
        "mean_forward_ic_all": float(np.mean(forward)) if forward else None,
        "mean_forward_ic_vetoed": float(np.mean([r["forward_ic"] for r in vetoed if r["forward_ic"] is not None]))
        if any(r["forward_ic"] is not None for r in vetoed)
        else None,
        "state_vs_resolved_correlation": correlation,
        "state_minus_resolved_mean_gap": mean_gap,
        "resolved_gate_veto_share": (len(resolved_would_veto) / len(rows)) if rows else None,
        "rows": rows,
    }
