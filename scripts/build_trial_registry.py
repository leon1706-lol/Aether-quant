"""Every research variant ever scored by a pre-registered rule, as one trial list (V6.3.0) -> the deflated Sharpe ratio's
N and Sharpe variance (`evaluation/backtest_statistics.py`, README "Return/Risk Efficiency").

Each rule chain's `ml/evaluation/<phase>/research.json` stores, per variant and scoring mode, one summary per split with
`median_net_sharpe` over the rebalance phases. A trial is one (phase, stage, variant, mode) scored on the backtest split
(the split variants were selected on); a summary repeated verbatim (the base book re-scored in every stage) counts once.

    python scripts/build_trial_registry.py [--evaluation-dir ml/evaluation] [--out ml/evaluation/trial_registry.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.trial_registry import SPLIT, build_registry, collect_trials, dedupe  # noqa: E402,F401


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--evaluation-dir", type=Path, default=ROOT / "ml" / "evaluation")
    parser.add_argument("--out", type=Path, default=ROOT / "ml" / "evaluation" / "trial_registry.json")
    args = parser.parse_args()
    registry = build_registry(args.evaluation_dir)
    args.out.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    print(f"{registry['num_trials']} trials from {', '.join(registry['sources']) or 'no research files'} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
