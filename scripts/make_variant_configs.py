"""Write one config.json per training variant (used with `train_multitask.py` / `train_sequence.py --config-path`).

The control is the shipped config. Each variant changes ONE thing under `phase_v2.retraining.<model>_training`
(`--model multitask` by default, `--model sequence` for the same changes on the sequence model):

    v1_gate_off     gate_aware_ranking_weights.enabled = false   (the missing #95 control)
    v2_book_heads   residual/sector-neutral head loss weights = 0 (#112: capacity only for heads that trade or gate)
    v3_listnet      ranking_loss.objective = "listnet"
    v4_stop_rank5d  early_stop_head = "rank_5d"                   (the shipped book trades rank_5d, early stopping watched rank_20d)

    python scripts/make_variant_configs.py <out_dir> [--base config.json] [--model multitask|sequence]
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

MODEL_ROOTS = {
    "multitask": ("phase_v2", "retraining", "multitask_training"),
    "sequence": ("phase_v2", "retraining", "sequence_training"),
}
MULTITASK_PATH = MODEL_ROOTS["multitask"]

VARIANTS: dict[str, list[tuple[tuple[str, ...], object]]] = {
    "v1_gate_off": [(("gate_aware_ranking_weights", "enabled"), False)],
    "v2_book_heads": [
        (("horizon_heads", "residual_rank_5d", "loss_weight"), 0.0),
        (("horizon_heads", "residual_rank_20d", "loss_weight"), 0.0),
        (("horizon_heads", "sector_neutral_rank_20d", "loss_weight"), 0.0),
    ],
    "v3_listnet": [(("ranking_loss", "objective"), "listnet")],
    "v4_stop_rank5d": [(("early_stop_head",), "rank_5d")],
}


def apply_changes(
    config: dict, changes: list[tuple[tuple[str, ...], object]], model: str = "multitask"
) -> dict:
    """A deep copy of `config` with each dotted-path change applied under <model>_training; a missing
    intermediate key raises KeyError (a typo must fail loudly, not silently train the control)."""
    result = copy.deepcopy(config)
    root = result
    for key in MODEL_ROOTS[model]:
        root = root[key]
    for path, value in changes:
        node = root
        for key in path[:-1]:
            node = node[key]
        if path[-1] not in node:
            raise KeyError(f"{'.'.join(path)} is not a key of {model}_training")
        node[path[-1]] = value
    return result


def build_variant_configs(base_config: dict, model: str = "multitask") -> dict[str, dict]:
    return {name: apply_changes(base_config, changes, model) for name, changes in VARIANTS.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out_dir")
    parser.add_argument("--base", default="config.json")
    parser.add_argument("--model", choices=sorted(MODEL_ROOTS), default="multitask")
    args = parser.parse_args()
    base = json.loads(Path(args.base).read_text(encoding="utf-8"))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, config in build_variant_configs(base, args.model).items():
        target = out / f"cfg_{args.model}_{name}.json"
        target.write_text(json.dumps(config, indent=2), encoding="utf-8")
        print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
