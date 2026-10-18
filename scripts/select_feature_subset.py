"""V6.2.0: choose the smaller input set for the regularised retrain on the TRAIN split only (rule in the V6.2.0 plan).

Validation and backtest are never read, so the retrained subset models can still be judged on them (R-MODEL10). Writes
`ml/evaluation/v620/feature_subset.json` (kept / dropped with reasons, the inputs) and a feature-schema file the trainers
take through `--feature-schema-path`.

    python scripts/select_feature_subset.py [--dataset ml/datasets/full_dataset.csv] [--out-dir ml/evaluation/v620]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

TRAIN_HALF_BOUNDARY = "2018-07-01"
LATE_WINDOW = ("2019-01-01", "2021-12-31")
TARGET = "target_rank_20d"


def main() -> int:
    from evaluation.feature_quality_audit import _daily_ic, feature_quality, permutation_ic_drop, select_feature_subset
    from evaluation.model_predictions import predict_heads

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=str(ROOT_DIR / "ml" / "datasets" / "full_dataset.csv"))
    parser.add_argument("--out-dir", default=str(ROOT_DIR / "ml" / "evaluation" / "v620"))
    args = parser.parse_args()

    ml_dir = ROOT_DIR / "ml"
    schema = json.loads((ml_dir / "multitask_feature_schema.json").read_text(encoding="utf-8"))
    features = list(schema["model_input_names"])
    wanted = set(features) | {"date", "ticker", "split", TARGET, "training_eligible"}
    parts = []
    for chunk in pd.read_csv(args.dataset, usecols=lambda name: name in wanted, chunksize=50_000):
        chunk = chunk[chunk["split"] == "train"]
        if "training_eligible" in chunk.columns:
            chunk = chunk[chunk["training_eligible"].astype(bool)]
        parts.append(chunk)
    train = pd.concat(parts, ignore_index=True)
    train["date"] = train["date"].astype(str).str[:10]
    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    asset_class = {a["ticker"]: a.get("asset_class") or a.get("security_type") for a in config["phase1"]["universe"]["assets"]}
    train["asset_class"] = train["ticker"].map(asset_class)

    quality = feature_quality(train, features, target=TARGET)
    early = train[train["date"] < TRAIN_HALF_BOUNDARY]
    late = train[train["date"] >= TRAIN_HALF_BOUNDARY]
    early_ic = {f: _daily_ic(early.assign(value=pd.to_numeric(early[f], errors="coerce")), "value", TARGET, "date", 10) for f in features}
    late_ic = {f: _daily_ic(late.assign(value=pd.to_numeric(late[f], errors="coerce")), "value", TARGET, "date", 10) for f in features}

    model = json.loads((ml_dir / "multitask_model.json").read_text(encoding="utf-8"))
    window = train[(train["date"] >= LATE_WINDOW[0]) & (train["date"] <= LATE_WINDOW[1])].reset_index(drop=True)

    def predict(data):
        return np.asarray(predict_heads(data, model, features, ["rank_20d"], model_kind="multitask", batched=True)["rank_20d"])

    drops = permutation_ic_drop(window, features, predict, target=TARGET)
    subset = select_feature_subset(
        features, permutation_drop=drops, early_ic=early_ic, late_ic=late_ic,
        ticker_id_suspects=quality["flags"]["ticker_id_suspects"],
    )
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    from json_safety import atomic_write_json, sanitize_json_finite

    report = {
        "rule": "train split only: permutation drop > 0 on 2019-2021 (installed multitask rank_20d), univariate daily IC "
                "same sign and |IC| >= 0.002 in both train halves (split 2018-07-01), not a ticker-ID suspect",
        "kept": subset["kept"], "dropped": subset["dropped"], "n_features": len(features), "n_kept": len(subset["kept"]),
        "permutation_drop": drops, "early_ic": early_ic, "late_ic": late_ic,
        "ticker_id_suspects": quality["flags"]["ticker_id_suspects"],
    }
    atomic_write_json(out_dir / "feature_subset.json", sanitize_json_finite(report), indent=2)
    (out_dir / "feature_schema_subset.json").write_text(
        json.dumps({**schema, "model_input_names": subset["kept"]}, indent=2), encoding="utf-8"
    )
    print(f"kept {len(subset['kept'])} of {len(features)} features -> {out_dir / 'feature_subset.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
