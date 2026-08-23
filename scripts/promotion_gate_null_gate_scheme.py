"""V5.3.7 - null calibration of the promotion gate's era flip-FRACTION under
the gate's OWN 90-day non-overlapping era scheme
(train.split_into_non_overlapping_eras semantics, replicated torch-free).

Question answered: with zero skill, what opposite-sign flip FRACTION does
the existing max_era_sign_flip_fraction knob need to tolerate so it stops
blocking statistically-typical noise?

Method mirrors promotion_gate_null_calibration.py: permute target ranks
within each date (destroys alignment, preserves marginals), per-date
Spearman IC series, bucket dates into consecutive era_length_days windows,
per-era mean IC, count eras opposite to the overall mean sign relative to
eligible eras (num_dates >= era_min_observations). Real model's own
fraction reported alongside.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

N_PERMS = 400
ERA_LENGTH_DAYS = 90
ERA_MIN_OBSERVATIONS = 3


def main() -> int:
    ds = pd.read_csv(ROOT_DIR / "ml" / "datasets" / "full_dataset.csv")
    ds = ds[ds["date"] >= "2019-01-01"]
    scored = pd.read_csv(ROOT_DIR / "ml" / "evaluation" / "gate_sweep_scored.csv")
    ds = ds.merge(scored, on=["date", "ticker"], how="inner")
    ds["target_rank"] = ds.groupby("date")["target_rank_20d"].rank(pct=True)
    ds["pred_rank"] = ds.groupby("date")["raw_blended_score"].rank(pct=True)
    ds = ds.dropna(subset=["target_rank", "pred_rank"])

    dates = sorted(ds["date"].unique())
    date_idx = {d: i for i, d in enumerate(dates)}
    tickers = sorted(ds["ticker"].unique())
    t_idx = {t: i for i, t in enumerate(tickers)}
    n_dates, n_tickers = len(dates), len(tickers)

    R = np.full((n_dates, n_tickers), np.nan)
    T = R.copy()
    for row in ds.itertuples(index=False):
        R[date_idx[row.date], t_idx[row.ticker]] = row.pred_rank
        T[date_idx[row.date], t_idx[row.ticker]] = row.target_rank
    counts = (~np.isnan(R) & ~np.isnan(T)).sum(axis=1)
    valid = counts >= 10

    def ic_series(target: np.ndarray) -> np.ndarray:
        out = np.full(n_dates, np.nan)
        for i in range(n_dates):
            if not valid[i]:
                continue
            r = R[i][~np.isnan(R[i])]
            t = target[i][~np.isnan(T[i])]
            rc, tc = r - r.mean(), t - t.mean()
            denom = np.sqrt((rc * rc).sum() * (tc * tc).sum())
            out[i] = float((rc * tc).sum() / denom) if denom else np.nan
        return out

    # Era buckets under the gate's own scheme: consecutive 90-day windows
    # from the FIRST valid date (split_into_non_overlapping_eras semantics,
    # train.py:4203).
    start_ts = pd.Timestamp(dates[0])
    era_id_for_date = np.array(
        [(pd.Timestamp(d) - start_ts).days // ERA_LENGTH_DAYS for d in dates]
    )
    era_ids = sorted(set(era_id_for_date[valid].tolist()))

    def flip_fraction(ic: np.ndarray) -> tuple[float, int]:
        overall_mean = np.nanmean(ic[valid])
        eligible = opposite = 0
        for eid in era_ids:
            mask = (era_id_for_date == eid) & valid & ~np.isnan(ic)
            vals = ic[mask]
            if len(vals) < ERA_MIN_OBSERVATIONS:
                continue
            eligible += 1
            era_mean = float(np.mean(vals))
            if abs(era_mean) >= 0.05 and (
                (overall_mean > 0 and era_mean < 0) or (overall_mean < 0 and era_mean > 0)
            ):
                opposite += 1
        frac = opposite / eligible if eligible else 0.0
        return frac, eligible

    real_ic = ic_series(T)
    real_frac, n_eras = flip_fraction(real_ic)

    rng = np.random.default_rng(42)
    fracs = []
    T_work = T.copy()
    for _ in range(N_PERMS):
        for i in range(n_dates):
            if valid[i]:
                row = T_work[i]
                finite = ~np.isnan(row)
                row[finite] = rng.permutation(row[finite])
        frac, _e = flip_fraction(ic_series(T_work))
        fracs.append(frac)
    arr = np.array(fracs)

    summary = {
        "era_length_days": ERA_LENGTH_DAYS,
        "n_eras_eligible_real": n_eras,
        "real_flip_fraction": round(real_frac, 4),
        "null_flip_fraction": {
            "p50": round(float(np.percentile(arr, 50)), 4),
            "p75": round(float(np.percentile(arr, 75)), 4),
            "p95": round(float(np.percentile(arr, 95)), 4),
            "max": round(float(arr.max()), 4),
        },
        "configured_max_era_sign_flip_fraction": 0.34,
        "P(null fraction > 0.34)": round(float((arr > 0.34).mean()), 4),
        "recommended_max": float(min(0.49, round(float(np.percentile(arr, 95)) + 0.01, 2))),
        "n_perms": N_PERMS,
    }
    out = ROOT_DIR / "ml" / "evaluation" / "promotion_gate_null_gate_scheme.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
