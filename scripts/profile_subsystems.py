"""cProfile + wall-clock harness for main.py's per-bar subsystems OTHER
than inference (see scripts/profile_inference.py for that one).

A sibling of profile_inference.py, not an extension of it - the input
shapes are completely different per subsystem (dict-of-scalars vs.
dict-of-lists vs. flat feature vectors), and that file's own docstring
scopes it specifically to "the neural-net inference step." Shares its
percentile()/summarize_durations() helpers rather than duplicating them
(already unit-tested in tests/test_profile_inference.py).

Covers, each pure and Lean-free by construction:
- regime          -> regime/market_regime.py::build_market_regime_vector()
- topology        -> topology/market_topology.py::build_market_topology()
- learned_topology -> topology/learned_topology.py::apply_learned_topology()
- liquidity       -> liquidity/market_liquidity.py::build_liquidity_decision()
- gating          -> moe/gating.py::build_gating_decision()
- analyzer        -> analyzer/market_analyzer.py::build_market_analysis_decision()
- indicators      -> the 7 pure functions in features/technical_indicators.py,
                     each timed INDEPENDENTLY (not summed) so a dominant one
                     is visible rather than averaged away

Deliberate scope decision: main.py::_build_model_input() itself is NOT
profiled here - it's a bound instance method reading ~15 pieces of
self.* state (symbol_windows, scaler_stats, latest_macro_payload, etc.),
not cleanly synthesizable the way inference's exported model weights
were. Profiling its underlying pure indicator primitives (the
`indicators` workload above) instead is a documented partial-coverage
choice, not silent scope-narrowing - see development/Problems.md.

Usage:
    python scripts/profile_subsystems.py [--iterations N] [--sort cumulative]
        [--regime] [--topology] [--learned-topology] [--liquidity]
        [--gating] [--analyzer] [--indicators]
    (no subsystem flags -> profiles all of them)

Writes a pstats dump (plus tail-latency report) per subsystem to
scripts/profile_subsystems_output.txt (overwritten each run) and prints
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

from scripts.profile_inference import percentile, summarize_durations  # noqa: E402

from analyzer import build_market_analysis_decision  # noqa: E402
from features.technical_indicators import (  # noqa: E402
    average_true_range_pct,
    bollinger_pctb,
    cross_sectional_momentum_rank,
    distance_from_52w_high,
    macd_histogram_normalized,
    relative_strength_index,
    volume_zscore,
)
from liquidity import build_liquidity_decision  # noqa: E402
from moe import build_gating_decision  # noqa: E402
from regime import build_market_regime_vector  # noqa: E402
from topology import apply_learned_topology, build_market_topology  # noqa: E402

OUTPUT_PATH = Path(__file__).resolve().parent / "profile_subsystems_output.txt"
SYNTHETIC_SYMBOLS = [f"SYM{i:02d}" for i in range(30)]  # matches this project's real universe size


# ---------------------------------------------------------------------------
# regime
# ---------------------------------------------------------------------------


def build_regime_workload(iterations: int, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    return [
        {
            "momentum_5d": rng.uniform(-0.1, 0.1),
            "momentum_20d": rng.uniform(-0.1, 0.1),
            "rolling_volatility_20d": rng.uniform(0.0, 0.05),
            "drawdown_20d": rng.uniform(-0.3, 0.0),
            "average_correlation": rng.uniform(-1.0, 1.0),
        }
        for _ in range(iterations)
    ]


def run_regime_workload(pregenerated: list[dict]) -> list[float]:
    durations: list[float] = []
    for features in pregenerated:
        start = time.perf_counter()
        build_market_regime_vector(features)
        durations.append(time.perf_counter() - start)
    return durations


# ---------------------------------------------------------------------------
# topology (deterministic)
# ---------------------------------------------------------------------------


def build_topology_workload(iterations: int, n_symbols: int = 30, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    symbols = SYNTHETIC_SYMBOLS[:n_symbols]
    return [
        {
            "returns_by_symbol": {sym: [rng.uniform(-0.03, 0.03) for _ in range(25)] for sym in symbols},
            "regime_labels_by_symbol": {sym: rng.choice(["bullish", "bearish", "neutral"]) for sym in symbols},
        }
        for _ in range(iterations)
    ]


def run_topology_workload(pregenerated: list[dict]) -> list[float]:
    durations: list[float] = []
    for inputs in pregenerated:
        start = time.perf_counter()
        build_market_topology(inputs["returns_by_symbol"], inputs["regime_labels_by_symbol"])
        durations.append(time.perf_counter() - start)
    return durations


# ---------------------------------------------------------------------------
# topology (learned overlay) - reuses ONE precomputed deterministic
# topology per iteration's symbol_features, not regenerated each call
# (regenerating it would double-count deterministic topology cost into
# this subsystem's own number).
# ---------------------------------------------------------------------------


def build_learned_topology_workload(iterations: int, n_symbols: int = 30, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    symbols = SYNTHETIC_SYMBOLS[:n_symbols]
    returns_by_symbol = {sym: [rng.uniform(-0.03, 0.03) for _ in range(25)] for sym in symbols}
    deterministic = build_market_topology(returns_by_symbol).to_dict()
    return [
        {
            "deterministic_topology": deterministic,
            "symbol_features": {
                sym: {"momentum_20d": rng.uniform(-0.1, 0.1), "rolling_volatility_20d": rng.uniform(0.0, 0.05)}
                for sym in symbols
            },
        }
        for _ in range(iterations)
    ]


def run_learned_topology_workload(pregenerated: list[dict]) -> list[float]:
    """No trained ml/topology_model.json is assumed present - model=None
    exercises apply_learned_topology()'s graceful-degrade path only. This
    is a documented limitation of this subsystem's number, not a bug: a
    real trained model's cost is architecture-dependent and this harness
    doesn't assume one exists on disk (matching load_real_exports()'s own
    "missing exports just print a warning, never raise" posture)."""
    durations: list[float] = []
    for inputs in pregenerated:
        start = time.perf_counter()
        apply_learned_topology(inputs["deterministic_topology"], inputs["symbol_features"], model=None)
        durations.append(time.perf_counter() - start)
    return durations


# ---------------------------------------------------------------------------
# liquidity
# ---------------------------------------------------------------------------


def build_liquidity_workload(iterations: int, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    return [
        {
            "close": rng.uniform(10.0, 500.0),
            "volume": rng.uniform(1e5, 1e7),
            "target_weight": rng.uniform(-0.2, 0.2),
            "portfolio_value": 1_000_000.0,
            "annualized_volatility": rng.uniform(0.1, 0.6),
            "dynamic_spread": rng.uniform(0.0001, 0.01),
        }
        for _ in range(iterations)
    ]


def run_liquidity_workload(pregenerated: list[dict]) -> list[float]:
    durations: list[float] = []
    for inputs in pregenerated:
        start = time.perf_counter()
        build_liquidity_decision(**inputs)
        durations.append(time.perf_counter() - start)
    return durations


# ---------------------------------------------------------------------------
# gating
# ---------------------------------------------------------------------------


def _synthetic_expert_training_metrics() -> dict:
    return {
        "experts": {
            name: {
                "quality_gate": {"quality_status": "stable", "gating_eligible": True},
                "validation": {"balanced_accuracy": 0.55},
                "backtest": {"balanced_accuracy": 0.53, "mcc": 0.06},
            }
            for name in ("bullish", "bearish", "sideways", "volatility")
        }
    }


def build_gating_workload(iterations: int, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    metrics = _synthetic_expert_training_metrics()
    return [
        {
            "regime": {"confidence": rng.uniform(0.0, 1.0), "risk_regime": "risk_neutral"},
            "expert_training_metrics": metrics,
            "expert_probabilities": {
                "bullish": rng.uniform(0.0, 1.0),
                "bearish": rng.uniform(0.0, 1.0),
                "sideways": rng.uniform(0.0, 1.0),
                "volatility": rng.uniform(0.0, 1.0),
            },
            "baseline_probability_up": rng.uniform(0.0, 1.0),
        }
        for _ in range(iterations)
    ]


def run_gating_workload(pregenerated: list[dict]) -> list[float]:
    durations: list[float] = []
    for inputs in pregenerated:
        start = time.perf_counter()
        build_gating_decision(**inputs)
        durations.append(time.perf_counter() - start)
    return durations


# ---------------------------------------------------------------------------
# analyzer
# ---------------------------------------------------------------------------


def build_analyzer_workload(iterations: int, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    return [
        {
            "signal_name": rng.choice(["buy", "sell", "hold", "short"]),
            "confidence": rng.uniform(0.0, 1.0),
            "probability_up": rng.uniform(0.0, 1.0),
            "target_weight": rng.uniform(-0.2, 0.2),
            "regime": {"confidence": rng.uniform(0.0, 1.0), "risk_regime": "risk_neutral"},
            "gating": {"decision_source": "baseline_and_experts"},
            "trading_eligible": True,
            "trade_lock_active": False,
        }
        for _ in range(iterations)
    ]


def run_analyzer_workload(pregenerated: list[dict]) -> list[float]:
    durations: list[float] = []
    for inputs in pregenerated:
        start = time.perf_counter()
        build_market_analysis_decision(**inputs)
        durations.append(time.perf_counter() - start)
    return durations


# ---------------------------------------------------------------------------
# indicators - 7 pure primitives, timed INDEPENDENTLY so a dominant one is
# visible rather than averaged into one number.
# ---------------------------------------------------------------------------


def build_indicators_workload(iterations: int, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    return [
        {
            "closes": [rng.uniform(10.0, 500.0) for _ in range(260)],
            "highs": [rng.uniform(10.0, 500.0) for _ in range(260)],
            "lows": [rng.uniform(10.0, 500.0) for _ in range(260)],
            "volumes": [rng.uniform(1e5, 1e7) for _ in range(260)],
            "momentum_by_symbol": {sym: rng.uniform(-0.1, 0.1) for sym in SYNTHETIC_SYMBOLS},
        }
        for _ in range(iterations)
    ]


def run_indicators_workload(pregenerated: list[dict]) -> dict[str, list[float]]:
    """Returns one duration list PER indicator function (not summed) -
    see module docstring for why."""
    per_function: dict[str, list[float]] = {
        "relative_strength_index": [],
        "average_true_range_pct": [],
        "bollinger_pctb": [],
        "volume_zscore": [],
        "cross_sectional_momentum_rank": [],
        "macd_histogram_normalized": [],
        "distance_from_52w_high": [],
    }
    for inputs in pregenerated:
        closes, highs, lows, volumes = inputs["closes"], inputs["highs"], inputs["lows"], inputs["volumes"]

        start = time.perf_counter()
        relative_strength_index(closes)
        per_function["relative_strength_index"].append(time.perf_counter() - start)

        start = time.perf_counter()
        average_true_range_pct(highs, lows, closes)
        per_function["average_true_range_pct"].append(time.perf_counter() - start)

        start = time.perf_counter()
        bollinger_pctb(closes)
        per_function["bollinger_pctb"].append(time.perf_counter() - start)

        start = time.perf_counter()
        volume_zscore(volumes)
        per_function["volume_zscore"].append(time.perf_counter() - start)

        start = time.perf_counter()
        cross_sectional_momentum_rank(inputs["momentum_by_symbol"], SYNTHETIC_SYMBOLS[0])
        per_function["cross_sectional_momentum_rank"].append(time.perf_counter() - start)

        start = time.perf_counter()
        macd_histogram_normalized(closes)
        per_function["macd_histogram_normalized"].append(time.perf_counter() - start)

        start = time.perf_counter()
        distance_from_52w_high(closes)
        per_function["distance_from_52w_high"].append(time.perf_counter() - start)

    return per_function


SUBSYSTEM_RUNNERS = {
    "regime": (build_regime_workload, run_regime_workload),
    "topology": (build_topology_workload, run_topology_workload),
    "learned-topology": (build_learned_topology_workload, run_learned_topology_workload),
    "liquidity": (build_liquidity_workload, run_liquidity_workload),
    "gating": (build_gating_workload, run_gating_workload),
    "analyzer": (build_analyzer_workload, run_analyzer_workload),
    "indicators": (build_indicators_workload, run_indicators_workload),
}


def _report_tail_latency(name: str, durations: list[float], out) -> None:
    tail_latency = summarize_durations(durations)
    lines = [f"  {key}: {value:.4f} ms" for key, value in tail_latency.items()]
    header = f"--- {name} ---"
    print(header)
    print("\n".join(lines))
    out.write(header + "\n")
    out.write("\n".join(lines) + "\n\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # Default is far lower than profile_inference.py's 10,000 - a real,
    # surprising finding from building this harness: build_market_topology()
    # costs ~400-500ms per call at this project's real ~30-symbol universe
    # size (likely its O(n^2)-ish correlation/embedding math, default
    # embedding_iterations=100), orders of magnitude above every other
    # subsystem here. 10,000 iterations of that alone would take over an
    # hour - 200 is enough for a stable percentile read across all 7
    # subsystems in well under 2 minutes total. Override with --iterations
    # for a longer, more stable run of a specific --<subsystem>.
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--sort", default="cumulative")
    for name in SUBSYSTEM_RUNNERS:
        parser.add_argument(f"--{name}", action="store_true", help=f"Profile only the {name} subsystem")
    args = parser.parse_args()

    requested = [name for name in SUBSYSTEM_RUNNERS if getattr(args, name.replace("-", "_"))]
    if not requested:
        requested = list(SUBSYSTEM_RUNNERS)

    with OUTPUT_PATH.open("w", encoding="utf-8") as out:
        out.write(f"--iterations {args.iterations} --subsystems {','.join(requested)}\n\n")
        for name in requested:
            build_fn, run_fn = SUBSYSTEM_RUNNERS[name]
            pregenerated = build_fn(args.iterations)

            profiler = cProfile.Profile()
            profiler.enable()
            result = run_fn(pregenerated)
            profiler.disable()

            if name == "indicators":
                for function_name, durations in result.items():
                    _report_tail_latency(f"indicators::{function_name}", durations, out)
            else:
                _report_tail_latency(name, result, out)

            stats = pstats.Stats(profiler, stream=out).sort_stats(args.sort)
            stats.print_stats(20)
            out.write("\n")

    print(f"\nFull pstats + tail-latency dump written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
