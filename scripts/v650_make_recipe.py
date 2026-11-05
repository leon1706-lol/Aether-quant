"""The recipe of the V6.5.0 walk-forward (T1, T2): today's config, honest as-of labels, and windows that stop before the
verification data. Its config goes to ml/evaluation/v650/configs/recipe.json.

Training windows end before their backtest window, and the last window's backtest ends in 2023-11, so nothing later than that
is loaded at all. If a model sleeve survives, the same run is resumed with the end date moved (frozen first): `--end 2026-11-30`.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ml" / "evaluation" / "v650" / "configs" / "recipe.json"


def recipe(base: dict, *, end: str) -> dict:
    config = copy.deepcopy(base)
    config["phase1"]["target"]["ranking"]["beta_estimation"] = "asof"
    config["phase1"]["universe"]["common_window"] = {**config["phase1"]["universe"]["common_window"], "end": end}
    walk = config["phase_v2"]["retraining"]["walk_forward"]
    # the per-window simulator would print verification-window figures nobody needs; the score tables are the output
    walk.update({
        "train_multitask": True, "train_sequence": True, "net_performance": False,
        "multitask_timeout_seconds": 7200, "sequence_timeout_seconds": 14400,
    })
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--end", default="2023-11-30")
    args = parser.parse_args()
    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(recipe(base, end=args.end), indent=4), encoding="utf-8", newline="\n")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
