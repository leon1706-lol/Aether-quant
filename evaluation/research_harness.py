"""One report for any cross-sectional signal (V6.4.3): `evaluate_signal(frame, score_column=...)` scores a
(date, ticker, score) column against the dataset's per-date rank targets with the statistics the pre-registered rules
use, so a factor, a probe model and the installed model are judged by the same numbers.

Per split and horizon: daily mean rank IC with its plain, non-overlapping (stride = horizon) and HAC (Newey-West,
lags = horizon - 1) t-stats, a date-block bootstrap CI, 90-day era stability, IC by year / asset class / regime tercile,
and the decay over horizons. Pure; no I/O.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from evaluation.gate_audit import daily_rank_ic
from evaluation.rank_book_simulator import summarize_metric_stability
from evaluation.rank_ic_core import newey_west_t_stat


def _t_stat(values: np.ndarray) -> float:
    if len(values) < 2 or float(np.std(values, ddof=1)) == 0.0:
        return 0.0
    return float(np.mean(values) / (np.std(values, ddof=1) / np.sqrt(len(values))))


def block_bootstrap_mean_ci(values, *, block: int, draws: int = 1000, seed: int = 7, confidence: float = 0.95) -> list[float] | None:
    """Percentile CI of the mean of a serially correlated series, resampling contiguous blocks of `block` values."""
    series = np.asarray(values, dtype=float)
    n = len(series)
    if n < 2:
        return None
    block = max(1, min(int(block), n))
    rng = np.random.default_rng(seed)
    blocks_needed = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=(draws, blocks_needed))
    index = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(draws, -1)[:, :n]
    means = series[index].mean(axis=1)
    tail = (1.0 - confidence) / 2.0
    return [float(np.quantile(means, tail)), float(np.quantile(means, 1.0 - tail))]


def ic_summary(ic_by_date: dict[str, float], *, horizon: int, era_days: int = 90, bootstrap_draws: int = 1000, seed: int = 7) -> dict:
    """Statistics of one daily IC series ({date: ic})."""
    if not ic_by_date:
        return {"num_dates": 0, "mean_ic": 0.0, "t": 0.0, "nonoverlap_t": 0.0, "hac_t": 0.0, "ci95": None, "eras": None,
                "ic_by_year": {}}
    dates = sorted(ic_by_date)
    values = np.array([ic_by_date[d] for d in dates], dtype=float)
    stride = max(1, int(horizon))
    nonoverlap = values[::stride]
    timestamps = pd.to_datetime(pd.Series(dates))
    era = ((timestamps - timestamps.iloc[0]).dt.days // max(1, era_days)).to_numpy()
    era_means = [float(values[era == e].mean()) for e in np.unique(era)]
    by_year = pd.Series(values, index=timestamps.dt.year.to_numpy()).groupby(level=0).mean()
    return {
        "num_dates": len(values),
        "mean_ic": float(values.mean()),
        "t": _t_stat(values),
        "nonoverlap_mean_ic": float(nonoverlap.mean()),
        "nonoverlap_t": _t_stat(nonoverlap),
        "num_nonoverlap_dates": int(len(nonoverlap)),
        "hac_t": float(newey_west_t_stat(values, lags=max(0, stride - 1))),
        "ci95": block_bootstrap_mean_ci(values, block=stride, draws=bootstrap_draws, seed=seed),
        "eras": summarize_metric_stability(era_means, min_windows=3, max_sign_flip_fraction=0.34),
        "ic_by_year": {int(year): float(value) for year, value in by_year.items()},
    }


def evaluate_signal(frame: pd.DataFrame, *, score_column: str, date_column: str = "date", ticker_column: str = "ticker",
                    split_column: str = "split", splits=("validation", "backtest"), horizons=(5, 20),
                    target_template: str = "target_rank_{h}d", class_column: str | None = None,
                    regime_column: str | None = None, min_names_per_date: int = 20, era_days: int = 90,
                    bootstrap_draws: int = 1000, seed: int = 7) -> dict:
    """{split: {"h<horizon>": ic_summary, "by_class": ..., "by_regime": ..., "decay": {horizon: mean_ic}}}."""
    report: dict = {"score_column": score_column, "splits": {}}
    for split in splits:
        part = frame[frame[split_column] == split] if split_column in frame.columns else frame
        split_report: dict = {"num_rows": int(len(part))}
        decay: dict = {}
        if "target_return_1d" in part.columns:
            one_day = part.assign(_rank_1d=part.groupby(date_column)["target_return_1d"].rank(pct=True))
            ic_1d = daily_rank_ic(one_day, score_column=score_column, target_column="_rank_1d", date_column=date_column,
                                  min_names_per_date=min_names_per_date)
            decay[1] = float(np.mean(list(ic_1d.values()))) if ic_1d else None
        for horizon in horizons:
            target = target_template.format(h=horizon)
            if target not in part.columns:
                continue
            ic = daily_rank_ic(part, score_column=score_column, target_column=target, date_column=date_column,
                               min_names_per_date=min_names_per_date)
            summary = ic_summary(ic, horizon=horizon, era_days=era_days, bootstrap_draws=bootstrap_draws, seed=seed)
            split_report[f"h{horizon}"] = summary
            decay[int(horizon)] = summary["mean_ic"] if summary["num_dates"] else None
            if class_column and class_column in part.columns:
                split_report.setdefault("by_class", {})[f"h{horizon}"] = {
                    str(cls): ic_summary(daily_rank_ic(group, score_column=score_column, target_column=target,
                                                       date_column=date_column, min_names_per_date=max(3, min_names_per_date // 4)),
                                         horizon=horizon, era_days=era_days, bootstrap_draws=200, seed=seed)["mean_ic"]
                    for cls, group in part.groupby(class_column)
                }
            if regime_column and regime_column in part.columns and ic:
                regime_by_date = part.groupby(date_column)[regime_column].median()
                terciles = pd.qcut(regime_by_date.rank(method="first"), 3, labels=["low", "mid", "high"])
                bucket = {str(date)[:10]: str(label) for date, label in terciles.items()}
                frame_ic = pd.Series(ic)
                split_report.setdefault("by_regime", {})[f"h{horizon}"] = {
                    label: float(frame_ic[[bucket.get(d) == label for d in frame_ic.index]].mean())
                    for label in ("low", "mid", "high")
                }
        split_report["decay"] = decay
        report["splits"][split] = split_report
    return report
