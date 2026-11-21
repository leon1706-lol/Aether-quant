"""Judging lab runs by the project's own statistics: `aq lab eval`, `aq lab compare` and `aq lab card`.

Every number is computed on the run's out-of-sample scores (`scores.csv`), never on rows a model was fitted on, and
every Sharpe is shown next to the deflated-Sharpe hurdle at the lab's trial count N.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from evaluation.rank_ic_core import newey_west_t_stat
from evaluation.research_harness import block_bootstrap_mean_ci
from lab import lab_dataset, run_registry
from lab import report_html as rh


def daily_ic(scores: pd.Series, target: pd.Series, dates: pd.Series, *, min_names: int = 3) -> pd.Series:
    """Per-date Spearman correlation of score and target (dates with fewer than `min_names` names, or no spread, skipped)."""
    frame = pd.DataFrame({"date": dates.to_numpy(), "s": scores.to_numpy(), "t": target.to_numpy()}).dropna()
    out = {}
    for date, group in frame.groupby("date"):
        if len(group) < min_names or group["s"].nunique() < 2 or group["t"].nunique() < 2:
            continue
        out[date] = float(group["s"].rank().corr(group["t"].rank()))
    return pd.Series(out, dtype=float).sort_index()


def ic_stats(series: pd.Series, *, horizon: int) -> dict[str, Any]:
    """Mean daily IC, its HAC t-statistic, a bootstrap interval and the number of days."""
    values = series.dropna().to_numpy()
    return {"mean": float(values.mean()) if len(values) else None, "days": int(len(values)),
            "t_hac": newey_west_t_stat(values, max(horizon - 1, 0)) if len(values) > 1 else None,
            "ci95": block_bootstrap_mean_ci(values, block=max(horizon, 1)) if len(values) > 1 else None}


def half_life(decay: Mapping[int, float]) -> float | None:
    """Sessions until the IC falls to half its shortest-horizon value (linear between horizons), None if it never does."""
    points = sorted((int(horizon), value) for horizon, value in decay.items() if value is not None and np.isfinite(value))
    if not points or points[0][1] <= 0:
        return None
    half = points[0][1] / 2.0
    for (h0, v0), (h1, v1) in itertools.pairwise(points):
        if v1 <= half:
            return float(h0 + (v0 - half) / (v0 - v1) * (h1 - h0)) if v0 != v1 else float(h1)
    return None


def load_run_frame(run_dir: Path, dataset: pd.DataFrame | None = None) -> tuple[pd.DataFrame, str, dict]:
    """The run's scores joined to its dataset rows, the score column, and the run record."""
    record = run_registry.read_run(run_dir)
    scores = pd.read_csv(run_dir / "scores.csv", dtype={"date": str, "ticker": str})
    column = next(name for name in scores.columns if name.startswith("score_"))
    if dataset is None:
        dataset = lab_dataset.load_dataset(Path(record["dataset"]))
    frame = scores.merge(dataset.drop(columns=["split"], errors="ignore"), on=["date", "ticker"], how="left")
    return frame, column, record


def spread_returns(frame: pd.DataFrame, column: str, *, quantile: float = 0.2, cost_bps: float = 0.0) -> pd.Series:
    """Daily top-minus-bottom quintile return on target_return_1d, less `cost_bps` on the day's turnover of the two legs."""
    out, previous = {}, None
    for date, group in frame.dropna(subset=[column, "target_return_1d"]).groupby("date"):
        if len(group) < 4:
            continue
        ranked = group[column].rank(pct=True)
        long, short = set(group.loc[ranked > 1 - quantile, "ticker"]), set(group.loc[ranked <= quantile, "ticker"])
        gross = group.loc[group["ticker"].isin(long), "target_return_1d"].mean() - group.loc[group["ticker"].isin(short), "target_return_1d"].mean()
        if previous is None:
            turnover = 1.0
        else:
            turnover = (len(long ^ previous[0]) / max(len(long), 1) + len(short ^ previous[1]) / max(len(short), 1)) / 2.0
        out[date] = gross - turnover * 2.0 * cost_bps / 1e4
        previous = (long, short)
    return pd.Series(out, dtype=float).sort_index()


def sharpe_block(returns: pd.Series, *, trials_n: int, trial_variance: float | None) -> dict[str, Any]:
    """Sharpe, PSR, DSR at N (with a variance floor) and the minimum track record, annualised by the calendar."""
    from evaluation.alpha_proof import deflated_sharpe_from_inputs
    from evaluation.backtest_statistics import expected_max_sharpe, probabilistic_sharpe_ratio
    from evaluation.overfitting import minimum_track_record_length

    values = returns.dropna()
    if len(values) < 3 or float(values.std(ddof=1)) == 0.0:
        return {"days": int(len(values)), "sharpe": None}
    weekends = pd.to_datetime(pd.Index(values.index)).day_of_week.max() >= 5
    periods = 365.0 if weekends else 252.0
    sharpe = float(values.mean() / values.std(ddof=1) * np.sqrt(periods))
    variance = trial_variance if trial_variance is not None and trial_variance > 0 else 0.25
    psr = probabilistic_sharpe_ratio(values.to_numpy())
    block = {"days": int(len(values)), "sharpe": sharpe, "annual_return": float(values.mean() * periods), "psr": None if psr is None else float(psr),
             "trials_n": int(trials_n), "hurdle_sharpe": expected_max_sharpe(max(trials_n, 1), variance) or 0.0}
    block["dsr"] = deflated_sharpe_from_inputs(values.to_numpy(), num_trials=max(trials_n, 1), trial_variance=variance, annualization=periods).get("value")
    block["min_track_record_days"] = float(minimum_track_record_length(values.to_numpy(), periods_per_year=int(periods)))
    return block


def trial_variance(ledger: Path) -> float | None:
    """The variance of the lab's trial Sharpe ratios (the deflated Sharpe's input), or None below two trials."""
    from evaluation.trial_ledger import read_ledger

    if not ledger.exists():
        return None
    sharpes = [entry["annualised_sharpe"] for entry in read_ledger(ledger) if entry.get("role") == "candidate" and entry.get("annualised_sharpe") is not None]
    return float(np.var(sharpes, ddof=1)) if len(sharpes) > 1 else None


def evaluate_run(run_dir: Path, *, lab_dir: Path, book: bool = False, cost_bps: float = 10.0, horizons: Sequence[int] = (1, 5, 20),
                 dataset: pd.DataFrame | None = None) -> dict[str, Any]:
    """IC (overall, by split, by year), its decay and half-life, quintile spreads, the train-to-OOS gap and, with `book`,
    a cost-aware quintile book judged at the lab's N."""
    frame, column, record = load_run_frame(run_dir, dataset)
    target = record.get("target", "target_rank_20d")
    horizon = int("".join(ch for ch in target.split("_")[-1] if ch.isdigit()) or 20)
    report: dict[str, Any] = {"run": run_dir.name, "model": record.get("model"), "template": record.get("template"), "target": target}
    ic = daily_ic(frame[column], frame[target], frame["date"])
    report["ic"] = ic_stats(ic, horizon=horizon)
    report["ic_by_split"] = {split: ic_stats(daily_ic(part[column], part[target], part["date"]), horizon=horizon) for split, part in frame.groupby("split")}
    report["ic_by_year"] = {year: float(values.mean()) for year, values in ic.groupby(pd.Index(ic.index).str[:4])}
    decay = {}
    for h in horizons:
        column_h = f"target_return_{h}d"
        if column_h in frame.columns:
            decay[int(h)] = float(daily_ic(frame[column], frame[column_h], frame["date"]).mean())
    report["decay"] = decay
    report["half_life_sessions"] = half_life(decay)
    quintiles = {}
    for _, group in frame.dropna(subset=[column, "target_return_1d"]).groupby("date"):
        if len(group) >= 5:
            buckets = pd.qcut(group[column].rank(method="first"), 5, labels=False) + 1
            for bucket, value in group.groupby(buckets)["target_return_1d"].mean().items():
                quintiles.setdefault(int(bucket), []).append(float(value))
    report["quintile_mean_return_1d"] = {bucket: float(np.mean(values)) for bucket, values in sorted(quintiles.items())}
    folds = (record.get("metrics") or {}).get("folds") or []
    validation = [row["best_validation_ic"] for row in folds if row.get("best_validation_ic") is not None]
    report["overfit_gap"] = {"best_validation_ic": float(np.mean(validation)) if validation else None, "oos_ic": report["ic"]["mean"],
                             "gap": (float(np.mean(validation)) - report["ic"]["mean"]) if validation and report["ic"]["mean"] is not None else None}
    from lab.trainer import ledger_count

    trials_n = max(ledger_count(lab_dir), int(record.get("trials_n") or 1))  # N as it stands now: every later trial counts against this run too
    variance = trial_variance(lab_dir / "trials.jsonl")
    report["book"] = sharpe_block(spread_returns(frame, column, cost_bps=cost_bps), trials_n=trials_n, trial_variance=variance) if book else None
    report["trials_n"] = trials_n
    return report


def render_eval(report: Mapping[str, Any]) -> str:
    """`aq lab eval`'s text report."""
    ic = report["ic"]
    lines = [f"{report['run']} ({report['model']}, {report['template']}) on {report['target']}",
             f"out-of-sample IC {rh.fmt(ic['mean'], 4)} over {ic['days']} days, HAC t {rh.fmt(ic['t_hac'], 2)}, 95% CI {ic['ci95'] and [round(v, 4) for v in ic['ci95']]}"]
    lines += [f"  {split}: IC {rh.fmt(stats['mean'], 4)} ({stats['days']} days, t {rh.fmt(stats['t_hac'], 2)})" for split, stats in report["ic_by_split"].items()]
    lines.append("by year: " + ", ".join(f"{year} {value:+.4f}" for year, value in report["ic_by_year"].items()))
    lines.append("decay: " + ", ".join(f"{h}d {value:+.4f}" for h, value in report["decay"].items()) + f"; half-life {rh.fmt(report['half_life_sessions'], 1)} sessions")
    lines.append("quintiles (1d return): " + ", ".join(f"Q{bucket} {value:+.5f}" for bucket, value in report["quintile_mean_return_1d"].items()))
    gap = report["overfit_gap"]
    lines.append(f"best validation IC {rh.fmt(gap['best_validation_ic'], 4)} vs out-of-sample {rh.fmt(gap['oos_ic'], 4)} (gap {rh.fmt(gap['gap'], 4)})")
    if report.get("book"):
        book = report["book"]
        lines.append(f"quintile book after costs: Sharpe {rh.fmt(book.get('sharpe'), 2)}, PSR {rh.fmt(book.get('psr'), 3)}, DSR at N={book.get('trials_n')} "
                     f"{rh.fmt(book.get('dsr'), 3)} (a winner of N trials must beat Sharpe {rh.fmt(book.get('hurdle_sharpe'), 2)})")
    return "\n".join(lines)


def render_eval_html(report: Mapping[str, Any]) -> str:
    """`aq lab eval --html`: the report as one self-contained page."""
    rows = [[split, stats["mean"], stats["days"], stats["t_hac"]] for split, stats in report["ic_by_split"].items()]
    sections = [("Out-of-sample IC", rh.table([["all", report["ic"]["mean"], report["ic"]["days"], report["ic"]["t_hac"]], *rows], ["split", "mean IC", "days", "HAC t"])),
                ("IC by year", rh.svg_bars(report["ic_by_year"], label="IC by year")),
                ("Decay", rh.table([[f"{h} sessions", value] for h, value in report["decay"].items()], ["horizon", "IC"])),
                ("Quintiles", rh.svg_bars({f"Q{bucket}": value for bucket, value in report["quintile_mean_return_1d"].items()}, label="Quintile returns"))]
    if report.get("book"):
        book = report["book"]
        sections.append(("Quintile book after costs", rh.table([[key, value] for key, value in book.items()], ["statistic", "value"])))
    return rh.page(f"Lab run {report['run']}", sections, subtitle=f"{report['model']} ({report['template']}) on {report['target']}, out-of-sample rows only",
                   footer=f"N = {report['trials_n']} trials in this lab: judge any Sharpe against the hurdle, not against zero.")


def baseline_scores(frame: pd.DataFrame, name: str) -> pd.Series:
    """A simple baseline on the same rows: `momentum_20` (20-session return) or `reversal_5`, from the dataset's columns."""
    if name in frame.columns:
        return frame[name]
    mapping = {"momentum_20": "ret_20", "momentum_60": "ret_60", "reversal_5": "rev_5"}
    if mapping.get(name) in frame.columns:
        return frame[mapping[name]]
    raise KeyError(f"no baseline {name!r}: use a feature column of the dataset or one of {', '.join(mapping)}")


def compare_runs(run_dirs: Sequence[Path], *, baseline: str | None = None) -> dict[str, Any]:
    """A leaderboard by mean out-of-sample IC on the rows every run scored, with each run's IC difference to the best one
    tested by a HAC t and a block-bootstrap CI."""
    frames = [load_run_frame(path) for path in run_dirs]
    target = frames[0][2].get("target", "target_rank_20d")
    common = None
    for frame, _, _ in frames:
        keys = set(zip(frame["date"], frame["ticker"], strict=False))
        common = keys if common is None else common & keys
    series: dict[str, pd.Series] = {}
    for (frame, column, _), path in zip(frames, run_dirs, strict=False):
        mask = [key in common for key in zip(frame["date"], frame["ticker"], strict=False)]
        part = frame[mask]
        series[path.name] = daily_ic(part[column], part[target], part["date"])
        if baseline and baseline not in series:
            series[baseline] = daily_ic(baseline_scores(part, baseline), part[target], part["date"])
    table = sorted(({"run": name, "ic": float(values.mean()), "days": int(len(values))} for name, values in series.items()), key=lambda row: -row["ic"])
    best = table[0]["run"]
    horizon = int("".join(ch for ch in target.split("_")[-1] if ch.isdigit()) or 20)
    for row in table:
        if row["run"] == best:
            row.update(diff=0.0, t_hac=None, ci95=None)
            continue
        joined = pd.concat([series[row["run"]], series[best]], axis=1, join="inner").dropna()
        difference = (joined.iloc[:, 0] - joined.iloc[:, 1]).to_numpy()
        row.update(diff=float(difference.mean()) if len(difference) else None, t_hac=newey_west_t_stat(difference, max(horizon - 1, 0)) if len(difference) > 1 else None,
                   ci95=block_bootstrap_mean_ci(difference, block=horizon) if len(difference) > 1 else None)
    return {"target": target, "rows": len(common or []), "leaderboard": table}


def render_compare(report: Mapping[str, Any]) -> str:
    """`aq lab compare`'s text: the leaderboard, each run against the best."""
    lines = [f"{report['rows']} common rows, target {report['target']}"]
    for row in report["leaderboard"]:
        test = "" if row["t_hac"] is None else f"  vs best {row['diff']:+.4f} (HAC t {row['t_hac']:.2f}, CI {[round(v, 4) for v in row['ci95']] if row['ci95'] else '-'})"
        lines.append(f"{row['ic']:+.4f}  {row['run']} ({row['days']} days){test}")
    return "\n".join(lines)


def model_card(run_dir: Path, report: Mapping[str, Any] | None = None) -> str:
    """A Markdown model card from the run's own numbers."""
    record = run_registry.read_run(run_dir)
    report = report or evaluate_run(run_dir, lab_dir=run_dir.parent.parent, book=True)
    metrics = record.get("metrics") or {}
    book = report.get("book") or {}
    ic = report["ic"]
    return "\n".join([
        f"# Model card: {record.get('model')} ({run_dir.name})", "",
        f"- **Template:** {record.get('template')}; loss {record.get('loss')}; folds {record.get('folds')}; seeds {record.get('seeds')}",
        f"- **Data:** {record.get('dataset')} ({record.get('rows')} rows); target `{record.get('target')}`",
        f"- **Features ({len(record.get('features', []))}):** {', '.join(record.get('features', []))}",
        f"- **Out-of-sample IC:** {rh.fmt(ic['mean'], 4)} over {ic['days']} days (HAC t {rh.fmt(ic['t_hac'], 2)}, 95% CI {ic['ci95'] and [round(v, 4) for v in ic['ci95']]})",
        f"- **Seed stability:** IC spread across seeds {rh.fmt(metrics.get('oof_ic_seed_std'), 4)} (per seed: {metrics.get('per_seed_ic')})",
        f"- **Half-life:** {rh.fmt(report.get('half_life_sessions'), 1)} sessions; decay {report.get('decay')}",
        f"- **Quintile book after costs:** Sharpe {rh.fmt(book.get('sharpe'), 2)}, PSR {rh.fmt(book.get('psr'), 3)}, DSR {rh.fmt(book.get('dsr'), 3)} at N = {report.get('trials_n')}"
        f" (hurdle {rh.fmt(book.get('hurdle_sharpe'), 2)})",
        "- **Intended use:** research. A lab result is a candidate, not a verified edge: it needs a pre-registered round and an unread holdout.",
        f"- **Limits:** {len(report.get('ic_by_year', {}))} years of out-of-sample dates; the IC by year is {report.get('ic_by_year')}.",
        f"- **Pins:** {json.dumps(record.get('pins', {}))}",
    ]) + "\n"
