"""Build the out-of-window holdout dataset (V5.7.0, todo.md finding 10) from `data_holdout/` and the ACTIVE scaler.

Run after `scripts/build_holdout_data.py --apply`. The features come from the same builders as the training dataset
(`train.build_feature_dataset`) on the holdout root; scaling uses the active `ml/scaler_stats.json` (never refit), the
asset-quality flags and eligibility come from the active dataset manifest (so the tradable pool is the live one), and
the `backtest` window of the written file is the holdout window. `aq evaluate ... --dataset holdout` then scores any
model on it. Writes `ml/datasets/holdout_dataset.csv` (gitignored with the other datasets).

    python scripts/build_holdout_dataset.py [--root data_holdout] [--start 2021-04-01] [--end 2025-06-30]

Heavy (same cost as a dataset build): run it on the Codespace, never on the dev PC.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

import train  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default="data_holdout")
    parser.add_argument("--start", default="2021-04-01")
    parser.add_argument("--end", default="2025-06-30")
    parser.add_argument("--output", default=str(ROOT_DIR / "ml" / "datasets" / "holdout_dataset.csv"))
    args = parser.parse_args()

    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    scaler_stats = json.loads((ROOT_DIR / "ml" / "scaler_stats.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT_DIR / "ml" / "dataset_manifest.json").read_text(encoding="utf-8"))

    holdout_config, dropped = train.build_holdout_config(config, args.root, args.start, args.end)
    print(f"assets kept: {len(holdout_config['phase1']['universe']['assets'])}, dropped (no holdout zip): {dropped}")
    dataset, metadata = train.build_feature_dataset(holdout_config)
    dataset = train.apply_asset_quality_flags(dataset, manifest["asset_quality"])
    dataset = train.apply_scaler_stats(dataset, scaler_stats)
    dataset, _ = train.add_asset_context_features(dataset, [asset["ticker"] for asset in holdout_config["phase1"]["universe"]["assets"]])
    dataset, _ = train.add_asset_class_context_features(dataset, train.asset_class_by_ticker_from_config(holdout_config))

    holdout_rows = dataset[dataset["split"] == "backtest"]
    print(
        f"rows: {len(dataset)} total, {len(holdout_rows)} in the holdout window "
        f"({holdout_rows['date'].min()}..{holdout_rows['date'].max()}), {holdout_rows['ticker'].nunique()} tickers"
    )
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(args.output, index=False)
    print(f"written {args.output}; dropped assets: {dropped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
