"""V5.3.6 WS-E - promotion-gate null calibration.

Question: when the model has ZERO skill, how often does the promotion gate
apparatus (non-overlapping stride-20 t-stat >= 2.0; era sign-flip count)
still produce alarming readings? Establishes false-positive rates so
`not_promotable` verdicts can be read against a calibrated null.

Method: destroy cross-sectional alignment by permuting prediction ranks
WITHIN each date (preserves marginals, kills signal), then compute per-date
Spearman IC between prediction-ranks and REAL target ranks over the
backtest window; derive non-overlapping stride-20 t-stats and per-era mean
signs; repeat N times.
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
STRIDE = 20


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
    n_dates = len(dates)
    tickers = sorted(ds["ticker"].unique())
    ticker_idx = {t: i for i, t in enumerate(tickers)}

    R = np.full((n_dates, len(tickers)), np.nan)
    T = R.copy()
    for row in ds.itertuples(index=False):
        R[date_idx[row.date], ticker_idx[row.ticker]] = row.pred_rank
        T[date_idx[row.date], ticker_idx[row.ticker]] = row.target_rank

    counts = (~np.isnan(R) & ~np.isnan(T)).sum(axis=1)
    valid_dates = counts >= 10
    print(f"dates with >=10 names: {valid_dates.sum()}/{n_dates}")

    def ic_series(target_matrix: np.ndarray) -> np.ndarray:
        out = np.full(n_dates, np.nan)
        for i in range(n_dates):
            if not valid_dates[i]:
                continue
            r = R[i][~np.isnan(R[i])]
            t = target_matrix[i][~np.isnan(T[i])]
            if len(r) != len(t):
                continue
            rc = r - r.mean()
            tc = t - t.mean()
            denom = np.sqrt((rc * rc).sum() * (tc * tc).sum())
            out[i] = float((rc * tc).sum() / denom) if denom else np.nan
        return out

    def t_stat(ic: np.ndarray) -> float:
        vals = ic[~np.isnan(ic)]
        vals = vals[::STRIDE]
        if len(vals) < 3 or vals.std(ddof=1) == 0:
            return 0.0
        return float(vals.mean() / vals.std(ddof=1) * np.sqrt(len(vals)))

    ERA_RANGES = {
        "era_0_good": ("2019-01-01", "2019-04-01"),
        "era_1_bad": ("2019-04-01", "2019-09-01"),
        "era_2_bad": ("2019-12-01", "2020-03-01"),
        "era_3_bad": ("2020-06-01", "2020-09-01"),
        "rest": ("1900-01-01", "2099-12-31"),
    }
    era_masks = []
    for name, (a, b) in ERA_RANGES.items():
        mask = np.zeros(n_dates, dtype=bool)
        for i, d in enumerate(dates):
            if a <= d <= b:
                if name != "rest" or not any(
                    ea <= d <= eb for (ea, eb) in list(ERA_RANGES.values())[:-1]
                ):
                    mask[i] = valid_dates[i]
        era_masks.append(mask)

    def era_negative_count(ic: np.ndarray) -> int:
        signs = []
        for mask in era_masks[:-1]:
            vals = ic[mask]
            vals = vals[~np.isnan(vals)]
            if len(vals):
                signs.append(vals.mean() < 0)
        return int(sum(signs))

    # Real (unpermuted) baseline
    real_ic = ic_series(T)
    real_t = t_stat(real_ic)
    real_neg = era_negative_count(real_ic)
    print(f"REAL: t={real_t:.3f} negative_eras={real_neg}")

    rng = np.random.default_rng(42)
    t_null, neg_null = [], []
    T_work = T.copy()
    for perm in range(N_PERMS):
        for i in range(n_dates):
            if valid_dates[i]:
                row = T_work[i]
                finite = ~np.isnan(row)
                row[finite] = rng.permutation(row[finite])
        ic = ic_series(T_work)
        t_null.append(t_stat(ic))
        neg_null.append(era_negative_count(ic))
    t_arr = np.array(t_null)
    neg_arr = np.array(neg_null)

    summary = {
        "n_perms": N_PERMS,
        "stride": STRIDE,
        "real": {"t_stat": round(real_t, 4), "negative_eras": real_neg},
        "null_t_stat": {
            "p50": round(float(np.percentile(t_arr, 50)), 4),
            "p95": round(float(np.percentile(t_arr, 95)), 4),
            "p99": round(float(np.percentile(t_arr, 99)), 4),
            "max": round(float(t_arr.max()), 4),
            "P(null t>=2.0)": round(float((t_arr >= 2.0).mean()), 4),
        },
        "null_negative_eras": {
            "mode": int(np.bincount(neg_arr).argmax()),
            "P(null neg>=2)": round(float((neg_arr >= 2).mean()), 4),
            "P(null neg>=3)": round(float((neg_arr >= 3).mean()), 4),
            "observed_real_is_unusual": bool(real_neg > np.percentile(neg_arr, 95)),
        },
    }
    out = ROOT_DIR / "ml" / "evaluation" / "promotion_gate_null_calibration.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
