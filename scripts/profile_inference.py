"""cProfile harness for main.py's per-bar inference hot path
(inference/exported_model.py).

No profiling harness existed anywhere in this repo before this - see
development/Problems.md for the full writeup. A real Lean backtest is
off the table for repeated profiling runs on this dev machine (a single
run takes over an hour), so this harness uses REAL exported model weights
already on disk under ml/ (not synthetic/random ones - the point is
realistic layer shapes and call volume, not realistic predictions) fed
synthetic-but-correctly-shaped input vectors, called in a loop sized to
approximate a real backtest's call volume (N_BARS * N_SYMBOLS calls to
each of baseline/experts/multitask/expert-multitask, matching
main.py::on_data()'s actual per-symbol-per-bar call pattern).

Usage:
    python scripts/profile_inference.py [--iterations N] [--sort cumulative]

Writes a pstats dump to scripts/profile_inference_output.txt (overwritten
each run) and also prints the top 25 lines by cumulative time to stdout.
"""

from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import random
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from inference import (  # noqa: E402
    run_exported_model,
    run_exported_multitask_model,
    run_exported_sequence_multitask_model,
)

try:
    from inference import run_exported_models_batched, run_exported_multitask_models_batched
except ImportError:
    run_exported_models_batched = None
    run_exported_multitask_models_batched = None

EXPERT_NAMES = ["bullish", "bearish", "sideways", "volatility"]
OUTPUT_PATH = Path(__file__).resolve().parent / "profile_inference_output.txt"


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _random_inputs(width: int, rng: random.Random) -> list[float]:
    return [rng.uniform(-2.0, 2.0) for _ in range(width)]


def load_real_exports() -> dict:
    """Loads every real model export this repo has on disk under ml/ -
    never synthetic/fake weights, so profiled call cost reflects real
    layer shapes/counts, not a toy stand-in."""
    baseline = _load_json(ROOT_DIR / "ml" / "model_weights.json")
    multitask = _load_json(ROOT_DIR / "ml" / "multitask_model.json")
    sequence = _load_json(ROOT_DIR / "ml" / "sequence_model.json")
    experts = {
        name: _load_json(ROOT_DIR / "ml" / "expert_models" / name / "model_weights.json") for name in EXPERT_NAMES
    }
    expert_multitask = {
        name: _load_json(ROOT_DIR / "ml" / "expert_models" / name / "multitask_model.json") for name in EXPERT_NAMES
    }
    missing = [
        label
        for label, value in [("baseline", baseline), ("multitask", multitask), ("sequence", sequence)]
        + [(f"expert:{n}", e) for n, e in experts.items()]
        + [(f"expert_multitask:{n}", e) for n, e in expert_multitask.items()]
        if value is None
    ]
    if missing:
        print(f"warning: missing real exports, profiling will skip them: {missing}", file=sys.stderr)
    return {
        "baseline": baseline,
        "multitask": multitask,
        "sequence": sequence,
        "experts": experts,
        "expert_multitask": expert_multitask,
    }


def run_workload(exports: dict, iterations: int, use_batched: bool, seed: int = 7) -> None:
    """One iteration == one symbol-bar's worth of inference calls, matching
    main.py::on_data()'s per-symbol call pattern: 1x baseline, 4x experts
    (or 1 batched call), 1x multitask, 4x expert-multitask (or 1 batched
    call), 1x sequence (fixed 30-bar window, matching the trained
    sequence_feature_schema's window_size)."""
    rng = random.Random(seed)
    baseline = exports["baseline"]
    multitask = exports["multitask"]
    sequence = exports["sequence"]
    expert_list = [exports["experts"][name] for name in EXPERT_NAMES if exports["experts"][name]]
    expert_multitask_list = [exports["expert_multitask"][name] for name in EXPERT_NAMES if exports["expert_multitask"][name]]

    input_width = baseline["export"]["architecture"][0]["in_features"] if baseline else 85
    sequence_window = 30

    for _ in range(iterations):
        inputs = _random_inputs(input_width, rng)

        if baseline:
            run_exported_model(baseline, inputs)

        if expert_list:
            if use_batched and run_exported_models_batched is not None:
                run_exported_models_batched(expert_list, inputs)
            else:
                for export in expert_list:
                    run_exported_model(export, inputs)

        if multitask:
            run_exported_multitask_model(multitask, inputs)

        if expert_multitask_list:
            if use_batched and run_exported_multitask_models_batched is not None:
                run_exported_multitask_models_batched(expert_multitask_list, inputs)
            else:
                for export in expert_multitask_list:
                    run_exported_multitask_model(export, inputs)

        if sequence:
            seq = [_random_inputs(input_width, rng) for _ in range(sequence_window)]
            run_exported_sequence_multitask_model(sequence, seq)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=10_000, help="Symbol-bar iterations to profile (default: 10000)")
    parser.add_argument("--sort", default="cumulative", help="pstats sort key (default: cumulative)")
    parser.add_argument(
        "--batched", action="store_true",
        help="Use run_exported_models_batched()/run_exported_multitask_models_batched() for experts instead of a per-expert loop, if available",
    )
    args = parser.parse_args()

    exports = load_real_exports()

    profiler = cProfile.Profile()
    profiler.enable()
    run_workload(exports, args.iterations, use_batched=args.batched)
    profiler.disable()

    stats = pstats.Stats(profiler).sort_stats(args.sort)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        stats_out = pstats.Stats(profiler, stream=f).sort_stats(args.sort)
        stats_out.print_stats(40)

    print(f"--iterations {args.iterations} --batched {args.batched}")
    stats.print_stats(25)
    print(f"\nFull pstats dump written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
