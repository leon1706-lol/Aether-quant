"""cProfile + wall-clock harness for main.py's per-bar inference hot path
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

Two things a first version of this harness got wrong, fixed here:
- Random input GENERATION used to happen INSIDE the profiled region, so
  cProfile measured the harness's own `random.uniform` overhead as if it
  were inference cost (~150s of an early 448s baseline was this, not
  inference - see development/Problems.md). All inputs are now
  pre-generated once, before profiling starts.
- No per-iteration wall-clock visibility existed - only cProfile's own
  aggregate totals, which include cProfile's own instrumentation overhead
  and say nothing about tail latency. Every iteration is now timed
  independently via time.perf_counter(), reported as p50/p95/p99/max/mean.

Mirrors main.py's own load-time optimizations: every loaded export gets
convert_state_dict_arrays() applied once (matching main.py's model
loaders), and --batched additionally builds+uses the same
BatchedLayerStackCache/BatchedMultitaskLayerStackCache main.py builds once
in _ensure_ready() - so this harness's --batched numbers reflect the real
optimized production path, not just "batched but rebuilding stacks every
call."

Usage:
    python scripts/profile_inference.py [--iterations N] [--sort cumulative] [--batched]

Writes a pstats dump (plus the tail-latency report) to
scripts/profile_inference_output.txt (overwritten each run) and prints
both to stdout.
"""

from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import random
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from inference import (  # noqa: E402
    convert_state_dict_arrays,
    run_exported_model,
    run_exported_multitask_model,
    run_exported_sequence_multitask_model,
)

try:
    from inference import (
        build_models_batched_cache,
        build_multitask_models_batched_cache,
        run_exported_models_batched,
        run_exported_multitask_models_batched,
    )
except ImportError:
    run_exported_models_batched = None
    run_exported_multitask_models_batched = None
    build_models_batched_cache = None
    build_multitask_models_batched_cache = None

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
    layer shapes/counts, not a toy stand-in. Applies
    convert_state_dict_arrays() to each loaded export, matching
    main.py's own model loaders - this harness's numbers should reflect
    the real, already-optimized load-time behavior, not the pre-caching
    state."""
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

    for export in [baseline, multitask, sequence, *experts.values(), *expert_multitask.values()]:
        if export is not None:
            convert_state_dict_arrays(export)

    return {
        "baseline": baseline,
        "multitask": multitask,
        "sequence": sequence,
        "experts": experts,
        "expert_multitask": expert_multitask,
    }


def pregenerate_inputs(
    width: int, sequence_window: int, iterations: int, seed: int = 7
) -> list[tuple[list[float], list[list[float]]]]:
    """Pre-generates every iteration's (flat_inputs, sequence_inputs) pair
    OUTSIDE the profiled region, so profiling measures real inference cost
    only - not this harness's own random-number-generation overhead."""
    rng = random.Random(seed)
    return [
        (_random_inputs(width, rng), [_random_inputs(width, rng) for _ in range(sequence_window)])
        for _ in range(iterations)
    ]


def percentile(sorted_values: list[float], p: float) -> float:
    """Nearest-rank percentile over an already-sorted list, p in [0, 100].
    Returns 0.0 for an empty list rather than raising - a harness reporting
    helper should never itself crash a profiling run."""
    if not sorted_values:
        return 0.0
    index = min(int(round(p / 100.0 * (len(sorted_values) - 1))), len(sorted_values) - 1)
    return sorted_values[index]


def summarize_durations(durations: list[float]) -> dict[str, float]:
    """p50/p95/p99/max/mean over a list of per-iteration wall-clock
    durations (seconds), reported in milliseconds - the first tail-latency
    visibility this repo has had for this hot path (cProfile's own
    aggregate stats say nothing about the worst-case bar)."""
    if not durations:
        return {"p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "max_ms": 0.0, "mean_ms": 0.0}
    sorted_durations = sorted(durations)
    return {
        "p50_ms": percentile(sorted_durations, 50) * 1000,
        "p95_ms": percentile(sorted_durations, 95) * 1000,
        "p99_ms": percentile(sorted_durations, 99) * 1000,
        "max_ms": sorted_durations[-1] * 1000,
        "mean_ms": (sum(sorted_durations) / len(sorted_durations)) * 1000,
    }


def run_workload(
    exports: dict,
    pregenerated_inputs: list[tuple[list[float], list[list[float]]]],
    use_batched: bool,
    stack_cache=None,
    multitask_stack_cache=None,
) -> list[float]:
    """Runs one full symbol-bar's worth of inference per pregenerated
    input tuple, matching main.py::on_data()'s per-symbol call pattern:
    1x baseline, 4x experts (or 1 batched call), 1x multitask, 4x
    expert-multitask (or 1 batched call), 1x sequence. Returns the
    wall-clock duration (seconds) of EACH iteration, timed independently
    of cProfile (whose own instrumentation adds overhead that would
    otherwise skew absolute numbers)."""
    baseline = exports["baseline"]
    multitask = exports["multitask"]
    sequence = exports["sequence"]
    expert_list = [exports["experts"][name] for name in EXPERT_NAMES if exports["experts"][name]]
    expert_multitask_list = [exports["expert_multitask"][name] for name in EXPERT_NAMES if exports["expert_multitask"][name]]

    durations: list[float] = []
    for flat_inputs, sequence_inputs in pregenerated_inputs:
        start = time.perf_counter()

        if baseline:
            run_exported_model(baseline, flat_inputs)

        if expert_list:
            if use_batched and run_exported_models_batched is not None:
                run_exported_models_batched(expert_list, flat_inputs, stack_cache=stack_cache)
            else:
                for export in expert_list:
                    run_exported_model(export, flat_inputs)

        if multitask:
            run_exported_multitask_model(multitask, flat_inputs)

        if expert_multitask_list:
            if use_batched and run_exported_multitask_models_batched is not None:
                run_exported_multitask_models_batched(
                    expert_multitask_list, flat_inputs, stack_cache=multitask_stack_cache
                )
            else:
                for export in expert_multitask_list:
                    run_exported_multitask_model(export, flat_inputs)

        if sequence:
            run_exported_sequence_multitask_model(sequence, sequence_inputs)

        durations.append(time.perf_counter() - start)
    return durations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=10_000, help="Symbol-bar iterations to profile (default: 10000)")
    parser.add_argument("--sort", default="cumulative", help="pstats sort key (default: cumulative)")
    parser.add_argument(
        "--batched", action="store_true",
        help="Use run_exported_models_batched()/run_exported_multitask_models_batched() (plus their precomputed stack caches, matching main.py's real optimized path) instead of a per-expert loop",
    )
    args = parser.parse_args()

    exports = load_real_exports()

    stack_cache = None
    multitask_stack_cache = None
    if args.batched and build_models_batched_cache is not None:
        stack_cache = build_models_batched_cache([exports["experts"].get(name) for name in EXPERT_NAMES])
        multitask_stack_cache = build_multitask_models_batched_cache(
            [exports["expert_multitask"].get(name) for name in EXPERT_NAMES]
        )

    input_width = exports["baseline"]["export"]["architecture"][0]["in_features"] if exports["baseline"] else 85
    pregenerated_inputs = pregenerate_inputs(input_width, sequence_window=30, iterations=args.iterations)

    profiler = cProfile.Profile()
    profiler.enable()
    durations = run_workload(
        exports, pregenerated_inputs, use_batched=args.batched,
        stack_cache=stack_cache, multitask_stack_cache=multitask_stack_cache,
    )
    profiler.disable()

    tail_latency = summarize_durations(durations)
    tail_latency_lines = [f"  {key}: {value:.4f} ms" for key, value in tail_latency.items()]

    stats = pstats.Stats(profiler).sort_stats(args.sort)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        f.write(f"--iterations {args.iterations} --batched {args.batched}\n\n")
        f.write("Tail latency (wall-clock per iteration, independent of cProfile overhead):\n")
        f.write("\n".join(tail_latency_lines) + "\n\n")
        stats_out = pstats.Stats(profiler, stream=f).sort_stats(args.sort)
        stats_out.print_stats(40)

    print(f"--iterations {args.iterations} --batched {args.batched}")
    print("Tail latency (wall-clock per iteration, independent of cProfile overhead):")
    print("\n".join(tail_latency_lines))
    print()
    stats.print_stats(25)
    print(f"\nFull pstats + tail-latency dump written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
