"""The ONE-LOOK out-of-window report (V5.7.0): how a model set performs on the holdout dataset it never saw.

Run exactly once per candidate decision, AFTER the model has been chosen on validation (R-MODEL): the holdout is evidence,
not a selection set. Reads `ml/datasets/holdout_dataset.csv` (scripts/build_holdout_dataset.py), scores every model head
on the holdout window, and reports per head and per asset class: daily rank IC (mean, HAC t, non-overlapping t) against the
dataset's own rank targets, plus the as-live book (blended head, every live mechanism) when `--book` is given.

    python scripts/holdout_report.py [--models multitask sequence] [--book] [--output ml/evaluation/holdout_report.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluation.model_predictions import predict_heads  # noqa: E402
from evaluation.rank_ic_core import newey_west_t_stat, rank_ic_from_arrays  # noqa: E402

ML_DIR = ROOT_DIR / "ml"
MODEL_FILES = {"multitask": ("multitask_model.json", "multitask_feature_schema.json"), "sequence": ("sequence_model.json", "sequence_feature_schema.json")}
HEAD_TARGETS = {"rank_5d": ("target_rank_5d", 5), "rank_20d": ("target_rank_20d", 20)}


def ic_summary(frame: pd.DataFrame, prediction: str, target: str, horizon: int) -> dict:
    """Daily rank IC of `prediction` against `target` over `frame` (one row per ticker-date)."""
    result = rank_ic_from_arrays(
        frame[prediction].to_numpy(), frame[target].to_numpy(), frame["date"].to_numpy(), min_names_per_date=10
    )
    non_overlapping = rank_ic_from_arrays(
        frame[prediction].to_numpy(), frame[target].to_numpy(), frame["date"].to_numpy(),
        non_overlapping_stride=horizon, min_names_per_date=10,
    )
    return {
        "daily_mean_ic": result["mean_ic"], "hac_t": newey_west_t_stat(result["ic_values"], horizon - 1),
        "num_dates": result["num_dates"], "non_overlapping_mean_ic": non_overlapping["mean_ic"],
        "non_overlapping_t": non_overlapping["t_stat"], "non_overlapping_dates": non_overlapping["num_dates"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", nargs="*", default=["multitask", "sequence"])
    parser.add_argument("--dataset", default=str(ML_DIR / "datasets" / "holdout_dataset.csv"))
    parser.add_argument("--book", action="store_true", help="also run the as-live book on the holdout window")
    parser.add_argument("--output", default=str(ML_DIR / "evaluation" / "holdout_report.json"))
    args = parser.parse_args()

    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    dataset = pd.read_csv(args.dataset)
    dataset = dataset[dataset["training_eligible"] & (dataset["split"] == "backtest")].reset_index(drop=True)
    asset_class = {a["ticker"]: a.get("asset_class") or a.get("security_type") for a in config["phase1"]["universe"]["assets"]}
    dataset["asset_class"] = dataset["ticker"].map(asset_class)
    window = int(config.get("phase_v2", {}).get("sequence_model", {}).get("window_size", 30))
    report: dict = {
        "dataset": args.dataset, "rows": int(len(dataset)), "tickers": int(dataset["ticker"].nunique()),
        "first_date": str(dataset["date"].min()), "last_date": str(dataset["date"].max()), "models": {},
    }
    for model_kind in args.models:
        model_file, schema_file = MODEL_FILES[model_kind]
        model_export = json.loads((ML_DIR / model_file).read_text(encoding="utf-8"))
        schema = json.loads((ML_DIR / schema_file).read_text(encoding="utf-8"))
        predictions = predict_heads(
            dataset, model_export, schema["model_input_names"], list(HEAD_TARGETS),
            model_kind=model_kind, sequence_feature_schema=schema if model_kind == "sequence" else None,
            configured_window_size=window,
        )
        per_head = {}
        for head, (target, horizon) in HEAD_TARGETS.items():
            scored = dataset.assign(prediction=predictions[head]).dropna(subset=["prediction", target])
            per_head[head] = {
                "all": ic_summary(scored, "prediction", target, horizon),
                "by_asset_class": {
                    kind: ic_summary(group, "prediction", target, horizon)
                    for kind, group in scored.groupby("asset_class")
                    if group["ticker"].nunique() >= 10 or kind == "forex"
                },
            }
            print(f"{model_kind}/{head}: " + json.dumps(per_head[head]["all"]))
        report["models"][model_kind] = per_head
    if args.book:
        from as_live_levers import AsLiveHarness, summarize

        harness = AsLiveHarness("backtest", dataset_path=args.dataset, use_cache=False)
        report["as_live_book"] = summarize(harness.as_live())
        report["idealized_book"] = summarize(harness.idealized())
        print("as-live book:", json.dumps(report["as_live_book"]))
    Path(args.output).write_text(json.dumps(report, indent=2, default=float), encoding="utf-8")
    print(f"written {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
