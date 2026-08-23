"""V5.3.6 WS-C - overlap-vs-lean-Sharpe correlation (ordinal pairing).

book_history.jsonl segments were appended in wall-clock order and backtest
dirs are chronological; all real runs share the SAME sim window so
window-matching is ambiguous by construction. Ordinal pairing of the last-N
segments with the last-N completed runs is the documented approximation.
"""

from __future__ import annotations

import glob
import json
import re

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

rec = json.load(open("ml/evaluation/book_history_reconciliation.json", encoding="utf-8"))
runs = rec.get("all_runs") or [rec]

dirs_with_logs = sorted(d for d in glob.glob("backtests/2026-*") if glob.glob(d + "/log.txt"))


def dir_sharpe(d: str) -> float | None:
    text = open(glob.glob(d + "/log.txt")[0], encoding="utf-8", errors="ignore").read()
    vals = re.findall(r"STATISTICS:: Sharpe Ratio\s*(-?[\d.]+)", text)
    return float(vals[-1]) if vals else None


dir_sharpes = []
for d in dirs_with_logs:
    s = dir_sharpe(d)
    if s is not None:
        dir_sharpes.append((d.split("\\")[-1].split("/")[0], s))
print(f"runs with parsable sharpe: {len(dir_sharpes)}")

seen: set = []
ordered_segments = []
for run in runs:
    meta = run.get("run_metadata", {})
    key = (meta.get("start_date"), meta.get("end_date"))
    if key in seen or not key[0]:
        continue
    seen.append(key)
    overlaps = [
        e.get("overlap_fraction")
        for e in run.get("per_date", [])
        if e.get("overlap_fraction") is not None
    ]
    if overlaps:
        ordered_segments.append((key[0], key[1], float(np.mean(overlaps)), len(overlaps)))
print(f"unique dated segments: {len(ordered_segments)}")

n = min(len(ordered_segments), len(dir_sharpes))
pairs_src = list(zip(ordered_segments[-n:], dir_sharpes[-n:]))

rows = []
for (start, end, mean_ov, n_d), (dir_name, sharpe) in pairs_src:
    rows.append(
        {
            "segment": f"{start}..{end}",
            "mean_overlap": round(mean_ov, 4),
            "n_dates": n_d,
            "backtest_dir": dir_name,
            "lean_sharpe": sharpe,
        }
    )

df = pd.DataFrame(rows)
print(df.to_string(index=False))

paired = df.dropna(subset=["lean_sharpe"])
result: dict = {"pairs": rows}
if len(paired) >= 4:
    rho, pval = spearmanr(paired["mean_overlap"], paired["lean_sharpe"])
    result["spearman"] = {"n": int(len(paired)), "rho": round(float(rho), 4), "p": round(float(pval), 4)}
    print(f"\nSpearman(overlap, lean_sharpe): rho={rho:.3f} p={pval:.3f} (n={len(paired)})")
else:
    print(f"\nonly {len(paired)} paired - inconclusive")
json.dump(result, open("ml/evaluation/overlap_vs_sharpe_analysis.json", "w", encoding="utf-8"), indent=2)
print("written ml/evaluation/overlap_vs_sharpe_analysis.json")
