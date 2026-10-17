"""Cell-by-cell comparison of two dataset builds (V6.1.0; the V6.0.0 session carried the same check inline).

Rows are matched on (date, ticker). The report lists rows only in one file, every numeric column whose values differ
by more than 1e-6 (max delta, rows over), the differing cells per ticker, and split-label mismatches.

    python scripts/compare_datasets.py <reference.csv> <candidate.csv> [--out report.json] [--splits train validation ...]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

TOLERANCE = 1e-6


def compare_frames(reference: pd.DataFrame, candidate: pd.DataFrame, tolerance: float = TOLERANCE) -> dict:
    """Both frames indexed by (date, ticker)."""
    report: dict = {"rows_reference": len(reference), "rows_candidate": len(candidate)}
    report["only_reference"] = [list(key) for key in reference.index.difference(candidate.index)[:50]]
    report["only_candidate"] = [list(key) for key in candidate.index.difference(reference.index)[:50]]
    report["num_only_reference"] = int(len(reference.index.difference(candidate.index)))
    report["num_only_candidate"] = int(len(candidate.index.difference(reference.index)))
    common = reference.index.intersection(candidate.index)
    numeric = [c for c in reference.columns if c in candidate.columns and pd.api.types.is_numeric_dtype(reference[c])]
    columns: dict[str, dict] = {}
    by_ticker: dict[str, int] = {}
    for column in numeric:
        a = reference.loc[common, column].to_numpy(dtype=float)
        b = candidate.loc[common, column].to_numpy(dtype=float)
        delta = np.abs(a - b)
        nan_mismatch = np.isnan(a) != np.isnan(b)
        over = (delta > tolerance) | nan_mismatch
        over = np.where(np.isnan(delta) & ~nan_mismatch, False, over)
        if over.any():
            finite = delta[~np.isnan(delta)]
            columns[column] = {"max": float(finite.max()) if finite.size else None, "rows_over": int(over.sum())}
            for ticker, count in pd.Series(over, index=common).groupby(level="ticker").sum().items():
                if count:
                    by_ticker[str(ticker)] = by_ticker.get(str(ticker), 0) + int(count)
    report["columns_differing"] = columns
    report["differing_cells_by_ticker"] = dict(sorted(by_ticker.items(), key=lambda item: -item[1]))
    if "split" in reference.columns and "split" in candidate.columns:
        report["split_mismatch_rows"] = int((reference.loc[common, "split"] != candidate.loc[common, "split"]).sum())
    return report


def load(path: str, splits: list[str] | None) -> pd.DataFrame:
    parts = []
    for chunk in pd.read_csv(path, chunksize=40_000):
        parts.append(chunk[chunk["split"].isin(splits)] if splits else chunk)
    frame = pd.concat(parts, ignore_index=True)
    frame["date"] = frame["date"].astype(str).str[:10]
    return frame.set_index(["date", "ticker"]).sort_index()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reference")
    parser.add_argument("candidate")
    parser.add_argument("--out", default=None)
    parser.add_argument("--splits", nargs="*", default=None)
    args = parser.parse_args()
    report = {"reference": args.reference, "candidate": args.candidate,
              **compare_frames(load(args.reference, args.splits), load(args.candidate, args.splits))}
    summary = {key: value for key, value in report.items() if key not in ("columns_differing", "only_reference", "only_candidate")}
    print(json.dumps(summary, indent=1))
    print("columns differing:", len(report["columns_differing"]))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
