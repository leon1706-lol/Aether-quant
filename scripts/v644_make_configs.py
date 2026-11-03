"""V6.4.4: write rule R-MODEL12's candidate configs (ml/evaluation/v644/configs/) from the shipped config.json.

Every candidate is the shipped config plus the honest labels (`beta_estimation: "asof"`, #246), multitask-only scoring,
and a walk-forward that trains and tracks the multitask model on the candidate's own live-signal target. The grid is
fixed in `GRID` before any V6.4.4 score; `base_asof.json` is the dataset build's config.

    python scripts/v644_make_configs.py [--base config.json] [--out ml/evaluation/v644/configs]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "scripts"))

MT = "phase_v2.retraining.multitask_training"
CSI = "phase1.features.cross_sectional_inputs"
SECTOR_HEADS = {"sector_neutral_rank_20d": 1.0}
RANK_HEADS = {"rank_20d": 0.5, "rank_5d": 0.5}
SECTOR_PRIMARY = {
    f"{MT}.horizon_heads.sector_neutral_rank_20d.loss_weight": 1.0,
    f"{MT}.horizon_heads.rank_20d.loss_weight": 0.3,
    f"{MT}.early_stop_head": "sector_neutral_rank_20d",
}
RANKED = {f"{CSI}.enabled": True, f"{CSI}.group": "asset_class", f"{CSI}.mode": "replace", f"{CSI}.min_group_size": 5}

# ID -> (config patches beyond the base, live-signal heads). Fixed before any V6.4.4 score (rules.json records the shas).
GRID: dict[str, tuple[dict, dict]] = {
    "M0": ({}, RANK_HEADS),
    "M1": (dict(SECTOR_PRIMARY), SECTOR_HEADS),
    "M2": (dict(RANKED), RANK_HEADS),
    "M3": ({**SECTOR_PRIMARY, **RANKED}, SECTOR_HEADS),
    "M4": ({**SECTOR_PRIMARY, **RANKED, f"{MT}.hidden_layers": [32, 16], f"{MT}.weight_decay": 0.04, f"{MT}.dropout": 0.35},
           SECTOR_HEADS),
    "M5": ({**SECTOR_PRIMARY, **RANKED, f"{MT}.ranking_loss.objective": "listnet"}, SECTOR_HEADS),
    # The plan's "group none" ranks across classes whose bars reach live on different ticks (not reproducible live);
    # M6 instead keeps the raw scaled inputs AND adds their within-class ranks ("append").
    "M6": ({**SECTOR_PRIMARY, **RANKED, f"{CSI}.mode": "append"}, SECTOR_HEADS),
}


def target_head(heads: dict) -> str:
    return "sector_neutral_rank_20d" if "sector_neutral_rank_20d" in heads else "rank_20d"


def base_patches() -> dict:
    return {"phase1.target.ranking.beta_estimation": "asof"}


def candidate_patches(grid_id: str) -> dict:
    patches, heads = GRID[grid_id]
    head = target_head(heads)
    return {
        **base_patches(),
        "phase_v2.rank_signal.heads": dict(heads),
        "phase_v2.rank_signal.model_priority": ["multitask"],
        "phase_v2.retraining.walk_forward.train_multitask": True,
        "phase_v2.retraining.walk_forward.train_sequence": False,
        "phase_v2.retraining.walk_forward.tracked_metrics": [
            {"name": "backtest_mcc", "artifact": "training_metrics.json", "path": "backtest.mcc"},
            {"name": "candidate_ic", "artifact": "multitask_training_metrics.json",
             "path": f"backtest.{head}_ic_non_overlapping.mean_ic"},
        ],
        **patches,
    }


def write_configs(base: dict, out: Path) -> dict[str, str]:
    from v640_research import patch_config

    out.mkdir(parents=True, exist_ok=True)
    shas = {}
    for name, patches in (("base_asof", base_patches()), *((grid_id, candidate_patches(grid_id)) for grid_id in GRID)):
        text = json.dumps(patch_config(base, patches), indent=4) + "\n"
        path = out / f"{name}.json"
        path.write_bytes(text.encode("utf-8"))
        shas[name] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return shas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default=str(ROOT_DIR / "config.json"))
    parser.add_argument("--out", default=str(ROOT_DIR / "ml" / "evaluation" / "v644" / "configs"))
    args = parser.parse_args()
    shas = write_configs(json.loads(Path(args.base).read_text(encoding="utf-8")), Path(args.out))
    print(json.dumps(shas, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
