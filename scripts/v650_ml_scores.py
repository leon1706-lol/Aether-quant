"""Out-of-sample score tables of a walk-forward run (V6.5.0, tracks T1 and T2).

Each window's model scores only that window's backtest split, from that window's own dataset and scaler, so no row is scored
by a model that saw its label. `--end` is the guard of the selection window: nothing later reaches the score file.

    python scripts/v650_ml_scores.py --run-id walk-forward-<id> --end 2023-06-30
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "ml" / "evaluation" / "v650" / "scores"
EXPORTS = {"multitask": ("multitask_model.json", "multitask_feature_schema.json"),
           "sequence": ("sequence_model.json", "sequence_feature_schema.json")}
HEADS = ("rank_20d", "rank_5d", "sector_neutral_rank_20d")


def window_heads(window_dir: Path, frame: pd.DataFrame, mask: np.ndarray, kind: str, sequence_window: int) -> dict[str, np.ndarray] | None:
    """Head values for the masked rows; None when this window's trainer wrote no artifacts."""
    from evaluation.model_predictions import predict_heads

    model_name, schema_name = EXPORTS[kind]
    if not (window_dir / model_name).exists():
        return None
    export = json.loads((window_dir / model_name).read_text(encoding="utf-8"))
    schema = json.loads((window_dir / schema_name).read_text(encoding="utf-8"))
    return predict_heads(
        frame, export, schema["model_input_names"], list(HEADS), model_kind=kind,
        sequence_feature_schema=schema if kind == "sequence" else None, configured_window_size=sequence_window,
        row_mask=mask, batched=True,
    )


def daily_rank(frame: pd.DataFrame, values: np.ndarray) -> pd.Series:
    return pd.Series(values, index=frame.index).groupby(frame["date"]).rank(pct=True)


def tables_for_window(window_dir: Path, *, end: str, sequence_window: int) -> dict[str, pd.DataFrame]:
    frame = pd.read_csv(window_dir / "full_dataset.csv", low_memory=False)
    frame["date"] = frame["date"].astype(str).str[:10]
    frame = frame.sort_values(["ticker", "date"]).reset_index(drop=True)
    mask = ((frame["split"] == "backtest") & (frame["date"] <= end)).to_numpy()
    if not mask.any():
        return {}
    multitask = window_heads(window_dir, frame, mask, "multitask", sequence_window)
    sequence = window_heads(window_dir, frame, mask, "sequence", sequence_window)
    out: dict[str, pd.DataFrame] = {}

    def add(name: str, values: pd.Series) -> None:
        out[name] = pd.DataFrame({"date": frame.loc[mask, "date"], "ticker": frame.loc[mask, "ticker"], "score": values[mask]})

    if sequence is not None:
        add("ml_a1", (daily_rank(frame, sequence["rank_20d"]) + daily_rank(frame, sequence["rank_5d"])) / 2.0)
        add("ml_a3", pd.Series(sequence["sector_neutral_rank_20d"], index=frame.index))
    if multitask is not None:
        add("ml_a2", pd.Series(multitask["sector_neutral_rank_20d"], index=frame.index))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--sequence-window", type=int, default=30)
    args = parser.parse_args()
    run_dir = ROOT / "ml" / "versions" / args.run_id
    pieces: dict[str, list[pd.DataFrame]] = {}
    windows = sorted(run_dir.glob("window_*"), key=lambda path: int(path.name.split("_")[1]))
    for window_dir in windows:
        if not (window_dir / "full_dataset.csv").exists():
            print(f"{window_dir.name}: no dataset", flush=True)
            continue
        for name, table in tables_for_window(window_dir, end=args.end, sequence_window=args.sequence_window).items():
            pieces.setdefault(name, []).append(table)
            print(f"{window_dir.name} {name}: {len(table)} rows {table['date'].min()}..{table['date'].max()}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, tables in pieces.items():
        merged = pd.concat(tables, ignore_index=True).drop_duplicates(["date", "ticker"], keep="last").sort_values(["date", "ticker"])
        merged.to_csv(OUT / f"{name}.csv", index=False, lineterminator="\n", float_format="%.6f")
        print(f"{name}: {len(merged)} rows to {merged['date'].max()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
