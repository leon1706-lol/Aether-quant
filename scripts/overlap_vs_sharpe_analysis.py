"""Overlap-vs-Lean-Sharpe correlation (ordinal pairing).

book_history.jsonl segments were appended in wall-clock order and backtest dirs are
chronological; real runs share the SAME sim window, so window-matching is ambiguous by
construction. Ordinal pairing of the last-N segments with the last-N completed runs is the
documented approximation. Segments are never de-duplicated by window: every run is its own
point (collapsing identical windows merged distinct runs into one, V5.6.0).
"""

from __future__ import annotations

import glob
import json
import re
from pathlib import Path

import numpy as np

SHARPE_PATTERN = re.compile(r"STATISTICS:: Sharpe Ratio\s*(-?[\d.]+)")


def parse_engine_sharpe(log_text: str) -> float | None:
    values = SHARPE_PATTERN.findall(log_text)
    return float(values[-1]) if values else None


def collect_backtest_sharpes(pattern: str = "backtests/2026-*") -> list[tuple[str, float]]:
    """(directory name, Lean Sharpe) of every chronologically sorted run whose ENGINE log has statistics."""
    sharpes = []
    for directory in sorted(glob.glob(pattern)):
        logs = glob.glob(directory + "/log.txt")
        if not logs:
            continue
        sharpe = parse_engine_sharpe(Path(logs[0]).read_text(encoding="utf-8", errors="ignore"))
        if sharpe is not None:
            sharpes.append((Path(directory).name, sharpe))
    return sharpes


def segment_overlaps(runs: list[dict]) -> list[tuple[str, str, float, int]]:
    """One (start, end, mean overlap, n dates) per reconciled run that has any overlap reading."""
    segments = []
    for run in runs:
        meta = run.get("run_metadata", {})
        if not meta.get("start_date"):
            continue
        overlaps = [e["overlap_fraction"] for e in run.get("per_date", []) if e.get("overlap_fraction") is not None]
        if overlaps:
            segments.append((meta["start_date"], meta.get("end_date"), float(np.mean(overlaps)), len(overlaps)))
    return segments


def pair_ordinally(segments: list, dir_sharpes: list[tuple[str, float]]) -> list[dict]:
    n = min(len(segments), len(dir_sharpes))
    rows = []
    for (start, end, mean_overlap, n_dates), (dir_name, sharpe) in zip(segments[len(segments) - n :], dir_sharpes[len(dir_sharpes) - n :]):
        rows.append(
            {
                "segment": f"{start}..{end}",
                "mean_overlap": round(mean_overlap, 4),
                "n_dates": n_dates,
                "backtest_dir": dir_name,
                "lean_sharpe": sharpe,
            }
        )
    return rows


def main() -> None:
    import pandas as pd
    from scipy.stats import spearmanr

    reconciliation = json.loads(Path("ml/evaluation/book_history_reconciliation.json").read_text(encoding="utf-8"))
    runs = reconciliation.get("all_runs") or [reconciliation]
    dir_sharpes = collect_backtest_sharpes()
    print(f"runs with parsable sharpe: {len(dir_sharpes)}")
    segments = segment_overlaps(runs)
    print(f"dated segments with overlap readings: {len(segments)}")

    rows = pair_ordinally(segments, dir_sharpes)
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))

    result: dict = {"pairs": rows}
    if len(df) >= 4:
        rho, pval = spearmanr(df["mean_overlap"], df["lean_sharpe"])
        result["spearman"] = {"n": int(len(df)), "rho": round(float(rho), 4), "p": round(float(pval), 4)}
        print(f"\nSpearman(overlap, lean_sharpe): rho={rho:.3f} p={pval:.3f} (n={len(df)})")
    else:
        print(f"\nonly {len(df)} paired - inconclusive")
    Path("ml/evaluation/overlap_vs_sharpe_analysis.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("written ml/evaluation/overlap_vs_sharpe_analysis.json")


if __name__ == "__main__":
    main()
