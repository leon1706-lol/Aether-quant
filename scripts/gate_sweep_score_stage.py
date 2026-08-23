"""V5.3.6 WS-B/D stage 1: compute blended raw scores ONCE and cache them.

Backtest-split rows only (2019-01-01 onward - the eras every gate question
lives in), multitask-only scoring for speed. Output:
ml/evaluation/gate_sweep_scored.csv with [date, ticker, raw_blended_score].
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

ML_DIR = ROOT_DIR / "ml"


def main() -> int:
    from aq_cli import _EVALUATE_MODEL_ARTIFACTS
    from evaluation import compute_blended_raw_scores, predict_head
    from portfolio.rank_signal import resolve_rank_signal_policy

    t0 = time.time()
    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    dataset = pd.read_csv(ML_DIR / "datasets" / "full_dataset.csv")
    dataset = dataset[dataset["date"] >= "2019-01-01"].reset_index(drop=True)
    print(f"rows in scope: {len(dataset)}", flush=True)

    metrics_by_model = {}
    for model_name, fname in (("sequence", "sequence_training_metrics.json"), ("multitask", "multitask_training_metrics.json")):
        p = ML_DIR / fname
        metrics_by_model[model_name] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    policy = resolve_rank_signal_policy(metrics_by_model, config)
    if "multitask" in policy["model_priority"]:
        policy["model_priority"] = ["multitask"]
    active_heads = [h for h, w in policy["heads"].items() if w > 0.0]
    print(f"policy priority={policy['model_priority']} heads={active_heads}", flush=True)

    predictions_by_model = {}
    for model_kind in policy["model_priority"]:
        model_fname, schema_fname = _EVALUATE_MODEL_ARTIFACTS[model_kind]
        export = json.loads((ML_DIR / model_fname).read_text(encoding="utf-8"))
        schema = json.loads((ML_DIR / schema_fname).read_text(encoding="utf-8"))
        heads = {}
        for head_name in active_heads:
            print(f"predicting {model_kind}/{head_name}...", flush=True)
            heads[head_name] = predict_head(
                dataset,
                export,
                schema["model_input_names"],
                head_name,
                model_kind=model_kind,
                sequence_feature_schema=schema if model_kind == "sequence" else None,
                configured_window_size=int(config.get("phase_v2", {}).get("sequence_model", {}).get("window_size", 30)),
            )
        predictions_by_model[model_kind] = heads

    dataset["raw_blended_score"] = compute_blended_raw_scores(dataset, predictions_by_model, policy)
    out = dataset[["date", "ticker", "raw_blended_score"]].copy()
    out_path = ML_DIR / "evaluation" / "gate_sweep_scored.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"written {out_path} in {time.time()-t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
