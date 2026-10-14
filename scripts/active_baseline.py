"""As-live and idealized book of the CURRENT ml/ models on one split of a given dataset (V5.8.0).

R-MODEL8 judges a retrained candidate against the "active" models scored on the SAME new splits, with their own scaler and
feature set: build that dataset first (`scripts/build_holdout_dataset.py --config-path <pre-V5.8.0 config> --windows-config
config.json`), run this BEFORE a pull replaces ml/, and run it again on the candidate's own dataset afterwards.

    python scripts/active_baseline.py --split validation|backtest --dataset ml/datasets/v580_active_dataset.csv --out PATH
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from as_live_levers import AsLiveHarness, summarize  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", required=True, choices=["train", "validation", "backtest"])
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()
    harness = AsLiveHarness(args.split, use_cache=not args.no_cache, dataset_path=args.dataset)
    report = {
        "split": args.split, "dataset": args.dataset, "rows": int(len(harness.frame)),
        "as_live": summarize(harness.as_live()), "idealized": summarize(harness.idealized()),
    }
    Path(args.out).write_text(json.dumps(report, indent=2, default=float), encoding="utf-8")
    print(json.dumps({k: report[k]["net_sharpe"] for k in ("as_live", "idealized")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
