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
    python scripts/profile_inference.py [--iterations N] [--sort cumulative] [--batched] [--symbols-per-bar N] [--parallel] [--pool-workers N]

--batched also runs a separate, additive sequence-encoder symbol-batching
comparison (run_sequence_unbatched_workload() vs
run_sequence_batched_workload(), V4.9 Priority 1) - see their own
docstrings. This is a wall-clock-only comparison outside cProfile's
profiled region, reported as its own section; it never changes the
primary tail-latency numbers above, which always time the sequence step
unbatched (matching run_workload()'s own per-symbol-bar call pattern).

--parallel (V4.9 Priority 6) runs a further additive section: a real
ProcessPoolExecutor benchmark of inference/parallel_inference.py's
run_symbol_inference() (phase_v2.inference_parallelism) against an
identical sequential baseline calling the exact same function, answering
that module's own long-standing, never-measured IPC/pickling break-even
warning. See run_parallel_workload()/run_parallel_baseline_workload().
Degrades to a reported "FAILED" line (never crashes the whole run) on any
pool creation/spawn/submit failure, matching main.py's own
permanent-fallback-to-sequential philosophy for this same failure mode.

Writes a pstats dump (plus the tail-latency report) to
scripts/profile_inference_output.txt (overwritten each run) and prints
both to stdout.
"""

from __future__ import annotations

import argparse
import cProfile
import gc
import json
import pstats
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from inference import (  # noqa: E402
    convert_state_dict_arrays,
    init_worker,
    run_exported_model,
    run_exported_multitask_model,
    run_exported_sequence_multitask_model,
    run_symbol_inference,
)

try:
    from inference import (
        build_models_batched_cache,
        build_multitask_models_batched_cache,
        run_exported_models_batched,
        run_exported_multitask_models_batched,
        run_exported_sequence_multitask_model_batched,
    )
except ImportError:
    run_exported_models_batched = None
    run_exported_multitask_models_batched = None
    build_models_batched_cache = None
    build_multitask_models_batched_cache = None
    run_exported_sequence_multitask_model_batched = None

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


def bucket_durations_by_iteration_index(durations: list[float], n_buckets: int = 10) -> list[dict[str, float]]:
    """Splits `durations` (already in call order, NOT re-sorted) into
    n_buckets contiguous, equal-sized-ish chunks and summarizes each via
    summarize_durations() - lets a caller see whether early iterations
    (bucket 0) are disproportionately slow (a warmup/cold-cache effect -
    e.g. OS page-fault-in of the weight arrays, CPU frequency-scaling
    ramp-up) versus tail spikes being roughly uniformly distributed
    across the whole run (pointing at GC pauses or OS scheduler
    preemption instead - neither of which correlates with call order).

    Pure function: input is the exact same per-iteration duration list
    run_workload() already returns, in the exact order iterations ran -
    no new profiling region needed to use this. The last bucket absorbs
    any remainder when len(durations) doesn't divide evenly by
    n_buckets. Returns [] for an empty or non-positive n_buckets input."""
    if not durations or n_buckets <= 0:
        return []
    bucket_size = max(1, len(durations) // n_buckets)
    buckets = [durations[i : i + bucket_size] for i in range(0, len(durations), bucket_size)]
    return [summarize_durations(bucket) for bucket in buckets]


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


def run_sequence_unbatched_workload(sequence_export: dict, pregenerated_sequences: list[list[list[float]]]) -> list[float]:
    """Isolated per-symbol sequence-model timing - the exact same
    run_exported_sequence_multitask_model() call run_workload() above
    already makes as part of a full symbol-bar's inference, pulled out on
    its own so it can be compared apples-to-apples against
    run_sequence_batched_workload() below without any other model's cost
    mixed in. One duration entry per symbol."""
    durations: list[float] = []
    for sequence in pregenerated_sequences:
        start = time.perf_counter()
        run_exported_sequence_multitask_model(sequence_export, sequence)
        durations.append(time.perf_counter() - start)
    return durations


def run_sequence_batched_workload(
    sequence_export: dict, pregenerated_sequences: list[list[list[float]]], symbols_per_bar: int
) -> list[float]:
    """Bar-grouped sibling of run_sequence_unbatched_workload() above -
    main.py's V4.9 symbol-batching (on_data()'s Phase 1b,
    inference/exported_model.py::run_exported_sequence_multitask_model_batched())
    batches the sequence encoder across every PENDING SYMBOL IN ONE BAR,
    not across per-symbol model variants the way the expert/multitask
    --batched flag above does. Groups `pregenerated_sequences` (one entry
    per symbol) into chunks of `symbols_per_bar`, running ONE
    run_exported_sequence_multitask_model_batched() call per chunk.
    Returns one wall-clock duration PER BAR (per chunk), not per symbol,
    since that's the real unit of work main.py's own batching performs -
    divide by symbols_per_bar for a rough per-symbol-equivalent figure.
    Chunks with fewer than 2 symbols are skipped, matching main.py's own
    <2-present fallback threshold (not worth timing as "a batch" - the
    batched function itself would just degrade to the same individual
    calls run_sequence_unbatched_workload() already measures)."""
    durations: list[float] = []
    for start_index in range(0, len(pregenerated_sequences), symbols_per_bar):
        chunk = pregenerated_sequences[start_index : start_index + symbols_per_bar]
        if len(chunk) < 2:
            continue
        start = time.perf_counter()
        run_exported_sequence_multitask_model_batched(sequence_export, chunk)
        durations.append(time.perf_counter() - start)
    return durations


def run_parallel_baseline_workload(
    exports_for_workers: dict,
    pregenerated_inputs: list[tuple[list[float], list[list[float]]]],
    sequence_window_size: int,
    symbols_per_bar: int,
) -> list[float]:
    """Sequential sibling of run_parallel_workload() below, calling the
    EXACT SAME inference/parallel_inference.py::run_symbol_inference()
    function in a plain per-symbol loop instead of through a process pool
    - isolates IPC/pickling overhead specifically (both paths run
    identical inference work per symbol; only the submission mechanism
    differs), rather than conflating it with some other per-symbol cost
    difference a less careful comparison might introduce. Groups into
    chunks of symbols_per_bar purely so its per-bar duration list lines up
    one-to-one with run_parallel_workload()'s own bar grouping."""
    durations: list[float] = []
    for start_index in range(0, len(pregenerated_inputs), symbols_per_bar):
        chunk = pregenerated_inputs[start_index : start_index + symbols_per_bar]
        if not chunk:
            continue
        start = time.perf_counter()
        for flat_inputs, sequence_inputs in chunk:
            run_symbol_inference(flat_inputs, sequence_inputs, sequence_window_size)
        durations.append(time.perf_counter() - start)
    return durations


def run_parallel_workload(
    exports_for_workers: dict,
    pregenerated_inputs: list[tuple[list[float], list[list[float]]]],
    sequence_window_size: int,
    symbols_per_bar: int,
    max_workers: int = 4,
) -> list[float] | None:
    """V4.9 Priority 6 - real ProcessPoolExecutor benchmark for
    phase_v2.inference_parallelism (inference/parallel_inference.py),
    answering that module's own long-standing, never-measured break-even
    warning: does IPC/pickling overhead for submitting
    run_symbol_inference() calls to a separate process exceed the win at
    this project's real per-symbol inference cost (~4.8ms mean, post the
    weight-caching/batching pass)? Groups pregenerated_inputs into chunks
    of symbols_per_bar (one ProcessPoolExecutor.submit() burst per chunk,
    matching main.py::on_data()'s own per-bar fan-out shape via
    init_worker()/run_symbol_inference() - see that module's docstring),
    timing wall-clock submit-through-gather for each chunk.

    Returns None (never raises) on ANY pool creation/spawn/submit failure
    - matches main.py's own "any pool failure permanently falls back to
    the sequential path" philosophy exactly, including on this dev
    machine's own Windows 'spawn' start method, which re-bootstraps a full
    new interpreter per worker and has never been verified inside Lean's
    embedded-Python runtime (inference/parallel_inference.py's own module
    docstring)."""
    try:
        pool = ProcessPoolExecutor(max_workers=max_workers, initializer=init_worker, initargs=(exports_for_workers,))
    except Exception:
        return None

    durations: list[float] = []
    try:
        for start_index in range(0, len(pregenerated_inputs), symbols_per_bar):
            chunk = pregenerated_inputs[start_index : start_index + symbols_per_bar]
            if not chunk:
                continue
            start = time.perf_counter()
            try:
                futures = [
                    pool.submit(run_symbol_inference, flat_inputs, sequence_inputs, sequence_window_size)
                    for flat_inputs, sequence_inputs in chunk
                ]
                for future in futures:
                    future.result(timeout=30)
            except Exception:
                return None
            durations.append(time.perf_counter() - start)
    finally:
        pool.shutdown(wait=True)
    return durations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=10_000, help="Symbol-bar iterations to profile (default: 10000)")
    parser.add_argument("--sort", default="cumulative", help="pstats sort key (default: cumulative)")
    parser.add_argument(
        "--batched", action="store_true",
        help="Use run_exported_models_batched()/run_exported_multitask_models_batched() (plus their precomputed stack caches, matching main.py's real optimized path) instead of a per-expert loop",
    )
    parser.add_argument(
        "--bucket-report", action="store_true",
        help="Print/write a 10-bucket breakdown of durations by iteration index (see bucket_durations_by_iteration_index()) - reveals whether the tail is a warmup effect (bucket 0 much slower) or spread evenly (points at GC/OS scheduling instead). Print-only, zero effect on the existing tail-latency/pstats numbers.",
    )
    parser.add_argument(
        "--no-gc", action="store_true",
        help="Disable Python's garbage collector for the profiled region only (gc.disable()/gc.enable() around run_workload()) - isolates whether GC pauses are a material tail-latency contributor. Compare a --no-gc run against a normal run, back-to-back, to see if p99/max drop while p50 stays flat.",
    )
    parser.add_argument(
        "--symbols-per-bar", type=int, default=74,
        help="V4.9 Priority 1/6: symbols-per-bar grouping for the sequence-encoder symbol-batching comparison (--batched, see run_sequence_batched_workload()) AND the --parallel IPC-overhead benchmark below (see run_parallel_workload()). Default 74 matches this repo's real universe size (development/v2_architecture.md).",
    )
    parser.add_argument(
        "--parallel", action="store_true",
        help="V4.9 Priority 6: run a real ProcessPoolExecutor benchmark of inference/parallel_inference.py's run_symbol_inference() (phase_v2.inference_parallelism) against an identical sequential baseline, answering that module's own never-measured IPC/pickling break-even warning. Independent of --batched (each stack_cache built here is reused if --batched is also passed).",
    )
    parser.add_argument(
        "--pool-workers", type=int, default=4,
        help="Worker process count for --parallel's ProcessPoolExecutor (default: 4).",
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
    if args.no_gc:
        gc.disable()
    profiler.enable()
    try:
        durations = run_workload(
            exports, pregenerated_inputs, use_batched=args.batched,
            stack_cache=stack_cache, multitask_stack_cache=multitask_stack_cache,
        )
    finally:
        profiler.disable()
        if args.no_gc:
            gc.enable()

    tail_latency = summarize_durations(durations)
    tail_latency_lines = [f"  {key}: {value:.4f} ms" for key, value in tail_latency.items()]

    bucket_lines: list[str] = []
    if args.bucket_report:
        buckets = bucket_durations_by_iteration_index(durations)
        bucket_lines.append("Duration by iteration-index bucket (0 = earliest iterations):")
        for index, bucket in enumerate(buckets):
            bucket_lines.append(
                f"  bucket {index}: p50={bucket['p50_ms']:.4f}ms p99={bucket['p99_ms']:.4f}ms max={bucket['max_ms']:.4f}ms"
            )

    # V4.9 Priority 1 - sequence-encoder symbol-batching comparison,
    # additional/additive: run OUTSIDE cProfile's own profiled region
    # (this is a wall-clock-only comparison, not a hotspot breakdown) and
    # reported as its own separate section - never mixed into the primary
    # tail_latency numbers above, which stay exactly what they always
    # measured (a full symbol-bar's worth of every model, sequence always
    # unbatched, see run_workload()'s own sequence step). Only runs with
    # --batched and a real sequence export on disk.
    sequence_batch_lines: list[str] = []
    if args.batched and exports["sequence"] and run_exported_sequence_multitask_model_batched is not None:
        sequence_only_inputs = [sequence_inputs for _, sequence_inputs in pregenerated_inputs]
        unbatched_sequence_durations = run_sequence_unbatched_workload(exports["sequence"], sequence_only_inputs)
        batched_sequence_durations = run_sequence_batched_workload(
            exports["sequence"], sequence_only_inputs, symbols_per_bar=args.symbols_per_bar
        )
        unbatched_summary = summarize_durations(unbatched_sequence_durations)
        batched_summary = summarize_durations(batched_sequence_durations)
        per_symbol_equivalent_ms = (
            batched_summary["mean_ms"] / args.symbols_per_bar if batched_summary["mean_ms"] else 0.0
        )
        sequence_batch_lines.append(
            f"Sequence-encoder symbol-batching comparison (--symbols-per-bar {args.symbols_per_bar}, "
            f"isolated to JUST the sequence-model call, no other model's cost included):"
        )
        sequence_batch_lines.append(
            f"  unbatched, per symbol   ({len(unbatched_sequence_durations)} symbols): "
            f"p50={unbatched_summary['p50_ms']:.4f}ms p99={unbatched_summary['p99_ms']:.4f}ms mean={unbatched_summary['mean_ms']:.4f}ms"
        )
        sequence_batch_lines.append(
            f"  batched, per BAR        ({len(batched_sequence_durations)} bars): "
            f"p50={batched_summary['p50_ms']:.4f}ms p99={batched_summary['p99_ms']:.4f}ms mean={batched_summary['mean_ms']:.4f}ms"
        )
        sequence_batch_lines.append(
            f"  batched, per-symbol-equivalent (mean bar duration / symbols_per_bar): {per_symbol_equivalent_ms:.4f}ms "
            f"(vs {unbatched_summary['mean_ms']:.4f}ms unbatched mean)"
        )

    # V4.9 Priority 6 - real ProcessPoolExecutor IPC-overhead benchmark,
    # additional/additive, run OUTSIDE cProfile's own profiled region (a
    # ProcessPoolExecutor's own worker processes wouldn't be captured by
    # this process's cProfile instance anyway). Independent of --batched -
    # reuses stack_cache/multitask_stack_cache when --batched was ALSO
    # passed (a more realistic worker payload matching main.py's real
    # optimized path), but runs fine without them either way, same
    # graceful degrade run_exported_models_batched(stack_cache=None)
    # already has.
    parallel_lines: list[str] = []
    if args.parallel:
        exports_for_workers = {
            "expert_names": EXPERT_NAMES,
            "baseline": exports["baseline"],
            "sequence": exports["sequence"],
            "experts": exports["experts"],
            "multitask": exports["multitask"],
            "expert_multitask": exports["expert_multitask"],
            "expert_stack_cache": stack_cache,
            "expert_multitask_stack_cache": multitask_stack_cache,
        }
        sequential_baseline_durations = run_parallel_baseline_workload(
            exports_for_workers, pregenerated_inputs, sequence_window_size=30, symbols_per_bar=args.symbols_per_bar,
        )
        parallel_durations = run_parallel_workload(
            exports_for_workers, pregenerated_inputs, sequence_window_size=30,
            symbols_per_bar=args.symbols_per_bar, max_workers=args.pool_workers,
        )
        baseline_summary = summarize_durations(sequential_baseline_durations)
        parallel_lines.append(
            f"ProcessPoolExecutor IPC-overhead comparison (--symbols-per-bar {args.symbols_per_bar}, "
            f"--pool-workers {args.pool_workers}, same run_symbol_inference() call both ways):"
        )
        parallel_lines.append(
            f"  sequential baseline, per BAR ({len(sequential_baseline_durations)} bars): "
            f"p50={baseline_summary['p50_ms']:.4f}ms p99={baseline_summary['p99_ms']:.4f}ms mean={baseline_summary['mean_ms']:.4f}ms"
        )
        if parallel_durations is None:
            parallel_lines.append(
                "  process-pool: FAILED (pool creation/spawn/submit error - see "
                "inference/parallel_inference.py's own module docstring on Windows 'spawn'-start-method risk; "
                "main.py's own pool would fall back to the sequential path permanently on this same failure)"
            )
        else:
            pool_summary = summarize_durations(parallel_durations)
            verdict = "FASTER" if pool_summary["mean_ms"] < baseline_summary["mean_ms"] else "SLOWER (IPC overhead exceeds the win)"
            parallel_lines.append(
                f"  process-pool, per BAR        ({len(parallel_durations)} bars): "
                f"p50={pool_summary['p50_ms']:.4f}ms p99={pool_summary['p99_ms']:.4f}ms mean={pool_summary['mean_ms']:.4f}ms"
            )
            parallel_lines.append(f"  verdict at this symbols-per-bar/worker-count: pool is {verdict}")

    header = f"--iterations {args.iterations} --batched {args.batched} --no-gc {args.no_gc}"
    stats = pstats.Stats(profiler).sort_stats(args.sort)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        f.write(header + "\n\n")
        f.write("Tail latency (wall-clock per iteration, independent of cProfile overhead):\n")
        f.write("\n".join(tail_latency_lines) + "\n\n")
        if bucket_lines:
            f.write("\n".join(bucket_lines) + "\n\n")
        if sequence_batch_lines:
            f.write("\n".join(sequence_batch_lines) + "\n\n")
        if parallel_lines:
            f.write("\n".join(parallel_lines) + "\n\n")
        stats_out = pstats.Stats(profiler, stream=f).sort_stats(args.sort)
        stats_out.print_stats(40)

    print(header)
    print("Tail latency (wall-clock per iteration, independent of cProfile overhead):")
    print("\n".join(tail_latency_lines))
    if bucket_lines:
        print()
        print("\n".join(bucket_lines))
    if sequence_batch_lines:
        print()
        print("\n".join(sequence_batch_lines))
    if parallel_lines:
        print()
        print("\n".join(parallel_lines))
    print()
    stats.print_stats(25)
    print(f"\nFull pstats + tail-latency dump written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
