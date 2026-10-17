"""Write one config.json per training variant (used with `train_multitask.py` / `train_sequence.py --config-path`).

The control is the shipped config. Each variant changes ONE thing under `phase_v2.retraining.<model>_training`
(`--model multitask` by default, `--model sequence` for the same changes on the sequence model):

    v1_gate_off     gate_aware_ranking_weights.enabled = false   (the missing #95 control)
    v2_book_heads   residual/sector-neutral head loss weights = 0 (#112: capacity only for heads that trade or gate)
    v3_listnet      ranking_loss.objective = "listnet"
    v4_stop_rank5d  early_stop_head = "rank_5d"                   (the shipped book trades rank_5d, early stopping watched rank_20d)
    v8_rank60       a 60-day rank target and head (V6.0.0): phase1 extra_horizon_days [60], label purge 60 days,
                    horizon_heads.rank_60d enabled (multitask only; its dataset must be built with the same config)
    v9_reg          weight decay x16 AND dropout 0.5 together (V6.1.0: train IC ~0.37 against ~0 on validation; the
                    single wd / dropout changes stayed inside the seed spread)
    v11_snr20       early stopping on the sector-neutral 20-day head, its loss weight 1.0 (V6.1.0: the only head that
                    passes its promotion gate on validation and backtest)

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
    # V5.7.0 overfitting controls (train rank_20d IC 0.44-0.52 against 0.03-0.04 on validation).
    "v5_wd_x4": [(("weight_decay",), 0.04)],
    "v6_dropout_35": [(("dropout",), 0.35)],
    "v7_small_net": [(("hidden_layers",), [32, 16])],
    "v8_rank60": [],
    "v9_reg": [(("weight_decay",), 0.16), (("dropout",), 0.5)],
    "v11_snr20": [(("early_stop_head",), "sector_neutral_rank_20d"), (("horizon_heads", "sector_neutral_rank_20d", "loss_weight"), 1.0)],
}

# Changes outside <model>_training, by absolute path; the leaf may be new (V6.0.0: the 60-day target).
GLOBAL_CHANGES: dict[str, list[tuple[tuple[str, ...], object]]] = {
    "v8_rank60": [
        (("phase1", "target", "ranking", "extra_horizon_days"), [60]),
        (("phase1", "windows", "purge_label_horizon_days"), 60),
    ],
}
# Keys a variant may ADD under <model>_training (every other change must hit an existing key).
NEW_MODEL_KEYS: dict[str, list[tuple[tuple[str, ...], object]]] = {
    "v8_rank60": [(("horizon_heads", "rank_60d"), {"enabled": True, "loss_weight": 1.0})],
}
MULTITASK_ONLY = {"v8_rank60"}

# The sequence model has no `hidden_layers`; its capacity knob is the TCN channel list.
SEQUENCE_OVERRIDES: dict[str, list[tuple[tuple[str, ...], object]]] = {
    "v7_small_net": [(("channels",), [16, 16])],
}


def apply_changes(
    config: dict, changes: list[tuple[tuple[str, ...], object]], model: str = "multitask",
    *, new_keys: list[tuple[tuple[str, ...], object]] = (), global_changes: list[tuple[tuple[str, ...], object]] = (),
) -> dict:
    """A deep copy of `config` with each dotted-path change applied under <model>_training; a missing
    intermediate key raises KeyError (a typo must fail loudly, not silently train the control). `new_keys` may add a
    leaf under <model>_training, `global_changes` set a leaf by absolute path (both need existing parents)."""
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
    for base, edits in ((root, new_keys), (result, global_changes)):
        for path, value in edits:
            node = base
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = copy.deepcopy(value)
    return result


def build_variant_configs(base_config: dict, model: str = "multitask") -> dict[str, dict]:
    return {
        name: apply_changes(
            base_config, SEQUENCE_OVERRIDES.get(name, changes) if model == "sequence" else changes, model,
            new_keys=NEW_MODEL_KEYS.get(name, []), global_changes=GLOBAL_CHANGES.get(name, []),
        )
        for name, changes in VARIANTS.items()
        if model == "multitask" or name not in MULTITASK_ONLY
    }


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
