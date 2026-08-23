import glob
import json

import numpy as np
import pandas as pd

rec_path = "ml/evaluation/book_history_reconciliation.json"
try:
    rec = json.load(open(rec_path, encoding="utf-8"))
    runs = rec.get("all_runs") or [rec]
except FileNotFoundError:
    print("reconciliation json missing - WS-C needs a fresh --reconcile-all-runs first")
    raise SystemExit(0)

rows = []
for run in runs:
    meta = run.get("run_metadata", {})
    summary = run.get("summary", {})
    start, end = meta.get("start_date"), meta.get("end_date")
    if not start or not end:
        continue
    overlaps = []
    per = run.get("per_date", [])
    for entry in per:
        ov = entry.get("overlap_fraction")
        if ov is None and isinstance(entry.get("matched"), dict):
            m = entry["matched"]
            tot = sum(m.values())
            ov = m.get("exact", 0) / tot if tot else None
        if ov is not None:
            overlaps.append(ov)
    if not overlaps:
        continue
    # match to the backtest run whose log dates bracket this segment
    best_sharpe = None
    for path in glob.glob("backtests/*/1*.json"):
        try:
            payload = json.load(open(path, encoding="utf-8"))
            stats = payload.get("Statistics") or payload.get("statistics") or {}
            sharpe_raw = stats.get("Sharpe Ratio") or stats.get("sharpe_ratio")
            if sharpe_raw is None:
                continue
            runtime_end = str(payload.get("RuntimeEnd", ""))[:10]
            runtime_start = str(payload.get("RuntimeStart", ""))[:10]
            if not (runtime_start <= end and start <= runtime_end):
                continue
            best_sharpe = float(sharpe_raw)
            break
        except Exception:
            continue
    rows.append({
        "run": f"{start}..{end}",
        "mean_overlap": round(float(np.mean(overlaps)), 4),
        "n_dates": len(overlaps),
        "lean_sharpe": best_sharpe,
    })

df = pd.DataFrame(rows)
print(df.to_string(index=False))
paired = df.dropna(subset=["lean_sharpe"])
if len(paired) >= 4:
    from scipy.stats import spearmanr

    rho, pval = spearmanr(paired["mean_overlap"], paired["lean_sharpe"])
    print(f"\nSpearman(overlap, lean_sharpe) n={len(paired)}: rho={rho:.3f} p={pval:.3f}")
    print("=> negative/insignificant rho confirms overlap is NOT a reliable live-performance predictor.")
else:
    print(f"only {len(paired)} paired runs - correlation inconclusive; pairs listed above")

out = "ml/evaluation/overlap_vs_sharpe_analysis.json"
json.dump({"pairs": rows, "spearman": {"n": int(len(paired)), **({"rho": round(rho, 4), "p": round(pval, 4)} if len(paired) >= 4 else {})}}, open(out, "w", encoding="utf-8"), indent=2)
print("written:", out)
