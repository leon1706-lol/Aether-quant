"""Time main.py's per-tick feature path outside Lean (V6.0.0, todo lead 7).

`scripts/profile_subsystems.py` could not profile `main.py` ("it only runs inside Lean"), but the first-bar smoke test
already builds the real algorithm against a permissive stub. This does the same, fills every symbol's windows from the real
Lean zips, and then runs, for N timed days, what `on_data` runs per tick before inference:

    topology payload (`_build_topology_payload`), macro / bond / alt-data / sensitivity-driver payloads, and
    `_build_model_input` for every symbol

reporting wall time per stage and (with --cprofile) the hottest functions. It is a micro-benchmark of the same code the
Lean run executes, so a speed-up measured here is comparable with the TimingProbe stages of a backtest.

    python scripts/profile_main_tick.py [--warm 300] [--days 20] [--cprofile] [--json PATH]
"""

from __future__ import annotations

import argparse
import cProfile
import datetime
import io
import json
import pstats
import re
import sys
import types
import zipfile
from pathlib import Path
from time import process_time as perf_counter  # CPU time: a busy machine does not move it
from unittest.mock import MagicMock

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))


class _PermissiveQCAlgorithm:
    """Any PUBLIC attribute is a MagicMock (QCAlgorithm's surface is huge); private ones must be set by main.py."""

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        value = MagicMock(name=name)
        object.__setattr__(self, name, value)
        return value


def build_algorithm(start: datetime.datetime):
    """The real `AetherQuantAlgorithm`, initialised and `_ensure_ready()`-ed against the repository's config and ml/."""
    import os

    os.chdir(ROOT_DIR)
    stub = types.ModuleType("AlgorithmImports")
    stub.QCAlgorithm = _PermissiveQCAlgorithm
    stub.Slice = object
    stub.time = datetime.time
    sys.modules["AlgorithmImports"] = stub
    sys.modules.pop("main", None)
    import main

    algorithm = main.AetherQuantAlgorithm()
    algorithm._write_state = lambda *args, **kwargs: None
    algorithm.Debug = lambda message: None
    algorithm.Log = lambda message: None
    algorithm.Time = start
    for _ in range(120):
        try:
            if "_initialized_once" not in algorithm.__dict__:
                algorithm.initialize()
                algorithm.__dict__["_initialized_once"] = True
            algorithm._ensure_ready()
            break
        except NameError as error:
            match = re.search(r"name '(\w+)' is not defined", str(error))
            if not match:
                raise
            main.__dict__[match.group(1)] = MagicMock(name=match.group(1))
    return algorithm


def read_bars(config: dict, ticker_asset: dict) -> list[tuple[datetime.date, dict]]:
    scale = 1.0 / 10_000.0 if ticker_asset["security_type"] == "equity" else 1.0
    with zipfile.ZipFile(ROOT_DIR / ticker_asset["data_path"]) as archive:
        member = next(name for name in archive.namelist() if name.endswith(".csv"))
        lines = archive.read(member).decode("utf-8").splitlines()
    bars = []
    for line in lines:
        fields = line.split(",")
        day = datetime.date(int(fields[0][:4]), int(fields[0][4:6]), int(fields[0][6:8]))
        volume = float(fields[5]) if len(fields) > 5 and ticker_asset["security_type"] != "forex" else 0.0
        bars.append((day, {"open": float(fields[1]) * scale, "high": float(fields[2]) * scale, "low": float(fields[3]) * scale,
                           "close": float(fields[4]) * scale, "volume": volume}))
    return bars


def feed_day(algorithm, bars_by_symbol: dict, day: datetime.date) -> None:
    """Append one day's bar of every symbol that has one, the way on_data's window block does."""
    from main import ALT_DATA_PUBLICATION_LAG_DAYS, CROSS_ASSET_SENSITIVITY_DRIVERS, series_value_asof

    drivers = algorithm.phase1.get("features", {}).get("cross_asset_sensitivity", {}).get("drivers", CROSS_ASSET_SENSITIVITY_DRIVERS)
    lags = {**ALT_DATA_PUBLICATION_LAG_DAYS, **algorithm.phase1.get("features", {}).get("alt_data_publication_lag_days", {})}
    levels = {key: series_value_asof(algorithm.fred_series.get(name, []), day, lags.get(name, 0)) for key, name in drivers.items()}
    for symbol, by_day in bars_by_symbol.items():
        bar = by_day.get(day)
        if bar is None:
            continue
        algorithm.symbol_windows[symbol].append(bar)
        algorithm.symbol_long_windows[symbol].append(bar["close"])
        algorithm.symbol_treasury_10yr_history[symbol].append(None)
        for key, history in algorithm.symbol_sensitivity_driver_history[symbol].items():
            history.append(levels.get(key))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--warm", type=int, default=300, help="days of history fed before timing (windows hold up to 260 bars)")
    parser.add_argument("--days", type=int, default=20, help="timed days")
    parser.add_argument("--end", default="2024-06-28", help="last timed day (a weekday inside every class's data)")
    parser.add_argument("--repeat", type=int, default=1, help="repeat the timed days; the fastest repeat is reported")
    parser.add_argument("--scalar-beta", action="store_true", help="A/B: force the pre-V6.0.0 scalar OLS in the sensitivity betas")
    parser.add_argument("--cprofile", action="store_true")
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    if args.scalar_beta:
        import features.bond_features as bond_features

        bond_features._VECTOR_BETA_MIN_LENGTH = 10**9
    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    end = datetime.date.fromisoformat(args.end)
    algorithm = build_algorithm(datetime.datetime.combine(end, datetime.time(16, 0)))
    assets = {str(asset["ticker"]): asset for asset in config["phase1"]["universe"]["assets"]}
    symbol_by_ticker = {symbol_key: symbol for symbol_key, symbol in ((str(s), s) for s in algorithm.symbols)}
    bars_by_symbol = {}
    for key, symbol in symbol_by_ticker.items():
        ticker = algorithm.asset_lookup[key]["ticker"]
        bars_by_symbol[symbol] = dict(read_bars(config, assets[ticker]))
    calendar = sorted({day for by_day in bars_by_symbol.values() for day in by_day if day <= end})
    timed = calendar[-args.days:]
    warm = calendar[-(args.days + args.warm):-args.days]
    for day in warm:
        feed_day(algorithm, bars_by_symbol, day)

    best_stages = None
    calls = 0
    profiler = cProfile.Profile() if args.cprofile else None
    if profiler:
        profiler.enable()
    for _repeat in range(max(1, args.repeat)):
        stages = {"topology_payload": 0.0, "macro_bond_alt_payloads": 0.0, "build_model_input": 0.0}
        calls = 0
        for day in timed:
            if _repeat == 0:
                feed_day(algorithm, bars_by_symbol, day)
            algorithm.Time = datetime.datetime.combine(day, datetime.time(16, 0))
            started = perf_counter()
            algorithm.latest_topology_payload = algorithm._build_topology_payload()
            stages["topology_payload"] += perf_counter() - started
            started = perf_counter()
            algorithm.latest_macro_payload = algorithm._build_macro_payload()
            algorithm.latest_bond_payload = algorithm._build_bond_payload()
            algorithm.latest_alt_data_payload = algorithm._build_alt_data_payload()
            algorithm.latest_sensitivity_driver_levels = algorithm._build_sensitivity_driver_levels()
            stages["macro_bond_alt_payloads"] += perf_counter() - started
            nodes = {node["symbol"]: node for node in algorithm.latest_topology_payload.get("nodes", [])}
            started = perf_counter()
            for symbol in algorithm.symbols:
                if len(algorithm.symbol_windows[symbol]) >= 2:
                    algorithm._build_model_input(symbol, nodes.get(str(symbol)))
                    calls += 1
            stages["build_model_input"] += perf_counter() - started
        if best_stages is None or sum(stages.values()) < sum(best_stages.values()):
            best_stages = stages
    stages = best_stages
    if profiler:
        profiler.disable()
    per_day = {name: 1000.0 * value / max(1, len(timed)) for name, value in stages.items()}
    report = {"days": len(timed), "symbols": len(algorithm.symbols), "model_input_calls": calls,
              "ms_per_day": per_day, "ms_per_model_input_call": 1000.0 * stages["build_model_input"] / max(1, calls)}
    print(json.dumps(report, indent=1))
    if profiler:
        buffer = io.StringIO()
        pstats.Stats(profiler, stream=buffer).sort_stats("cumulative").print_stats(28)
        print(buffer.getvalue())
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
