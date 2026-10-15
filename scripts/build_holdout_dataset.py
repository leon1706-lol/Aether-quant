"""Build the out-of-window holdout dataset (V5.7.0, todo.md finding 10) from `data_holdout/` and the ACTIVE scaler.

Run after `scripts/build_holdout_data.py --apply`. The features come from the same builders as the training dataset
(`train.build_feature_dataset`) on the holdout root; scaling uses the active `ml/scaler_stats.json` (never refit), the
asset-quality flags and eligibility come from the active dataset manifest (so the tradable pool is the live one), and
the `backtest` window of the written file is the holdout window. `aq evaluate ... --dataset holdout` then scores any
model on it. Writes `ml/datasets/holdout_dataset.csv` (gitignored with the other datasets).

    python scripts/build_holdout_dataset.py [--root data] [--start <holdout start>] [--end <holdout end>]
        [--config-path config.json] [--windows-config config.json] [--output ml/datasets/holdout_dataset.csv]

V5.8.0: the data window was extended to 2026 inside `data/`, so the default root is `data` and the default window is
`phase1.windows.holdout`. `--config-path` selects the feature definition (the config the scored models were trained
with - e.g. the pre-V5.8.0 config for the shipped V5.6.0 models), `--windows-config` the train/validation windows of the
written splits (e.g. the V5.8.0 config); that pair builds the baseline dataset that scores the ACTIVE models on the new
splits (`ml/datasets/v580_active_dataset.csv`).

V6.0.0: `--full-splits` writes ONE dataset with all four splits of `--windows-config` (train / validation / backtest
from the training windows, `holdout` for the rows from `phase1.windows.holdout.start` on), scaled with the active
scaler; `--write-split-files` also writes `train_dataset.csv`, `validation_dataset.csv` and `backtest_dataset.csv` next
to `--output` (the files the trainers read). That is how `ml/datasets/full_dataset.csv` is refreshed without refitting
the scaler the installed models were trained with (`train.py --dataset-only` would refit it).

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


SPLIT_FILE_NAMES = {"train": "train_dataset.csv", "validation": "validation_dataset.csv", "backtest": "backtest_dataset.csv"}


def label_holdout_rows(dataset, holdout_start: str):
    """Rows of the extended `backtest` window dated on or after `holdout_start` become split `holdout`."""
    import pandas as pd

    dates = pd.to_datetime(dataset["date"])
    in_holdout = (dataset["split"] == "backtest") & (dates >= pd.Timestamp(holdout_start))
    dataset.loc[in_holdout.to_numpy(), "split"] = "holdout"
    return dataset


def full_split_window(windows: dict) -> tuple[str, str]:
    """(start, end) of the dataset's extended backtest window: the backtest split through the end of the holdout."""
    if "holdout" not in windows:
        raise ValueError("--full-splits needs phase1.windows.holdout")
    return windows["backtest"]["start"], windows["holdout"]["end"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default="data")
    parser.add_argument("--start", default=None, help="default: phase1.windows.holdout.start of --windows-config")
    parser.add_argument("--end", default=None, help="default: phase1.windows.holdout.end of --windows-config")
    parser.add_argument("--config-path", default=str(ROOT_DIR / "config.json"))
    parser.add_argument("--windows-config", default=str(ROOT_DIR / "config.json"))
    parser.add_argument("--output", default=str(ROOT_DIR / "ml" / "datasets" / "holdout_dataset.csv"))
    parser.add_argument("--full-splits", action="store_true", help="V6.0.0: train/validation/backtest/holdout in one file")
    parser.add_argument("--write-split-files", action="store_true", help="V6.0.0: also the per-split files the trainers read")
    args = parser.parse_args()

    config = json.loads(Path(args.config_path).read_text(encoding="utf-8"))
    windows_source = json.loads(Path(args.windows_config).read_text(encoding="utf-8"))["phase1"]["windows"]
    config["phase1"]["windows"] = {
        **config["phase1"]["windows"],
        **{key: windows_source[key] for key in ("training", "validation", "backtest") if key in windows_source},
    }
    holdout_window = windows_source.get("holdout") or {}
    if args.full_splits:
        args.start, args.end = full_split_window(windows_source)
    args.start = args.start or holdout_window.get("start")
    args.end = args.end or holdout_window.get("end")
    if not args.start or not args.end:
        parser.error("no --start/--end and no phase1.windows.holdout in --windows-config")
    scaler_stats = json.loads((ROOT_DIR / "ml" / "scaler_stats.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT_DIR / "ml" / "dataset_manifest.json").read_text(encoding="utf-8"))

    holdout_config, dropped = train.build_holdout_config(config, args.root, args.start, args.end)
    print(f"assets kept: {len(holdout_config['phase1']['universe']['assets'])}, dropped (no holdout zip): {dropped}")
    dataset, metadata = train.build_feature_dataset(holdout_config)
    dataset = train.apply_asset_quality_flags(dataset, manifest["asset_quality"])
    dataset = train.apply_scaler_stats(dataset, scaler_stats)
    dataset, _ = train.add_asset_context_features(dataset, [asset["ticker"] for asset in holdout_config["phase1"]["universe"]["assets"]])
    dataset, _ = train.add_asset_class_context_features(dataset, train.asset_class_by_ticker_from_config(holdout_config))

    if args.full_splits:
        dataset = label_holdout_rows(dataset, holdout_window["start"])
        print("rows per split:", dataset["split"].value_counts(dropna=False).to_dict())
    holdout_rows = dataset[dataset["split"] == ("holdout" if args.full_splits else "backtest")]
    print(
        f"rows: {len(dataset)} total, {len(holdout_rows)} in the holdout window "
        f"({holdout_rows['date'].min()}..{holdout_rows['date'].max()}), {holdout_rows['ticker'].nunique()} tickers"
    )
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(args.output, index=False)
    print(f"written {args.output}; dropped assets: {dropped}")
    if args.write_split_files:
        for split, name in SPLIT_FILE_NAMES.items():
            target = Path(args.output).parent / name
            dataset[dataset["split"] == split].to_csv(target, index=False)
            print(f"written {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
