"""One-lever-at-a-time attribution of the as-live rank book (V5.6.0).

`aq evaluate --rank-book --as-live` reports one number; this scores the dataset ONCE with the live blended head, then
re-runs the same simulator with each live mechanism switched off (or each gate value changed) so the gap between the
idealized and the as-live Sharpe is attributed instead of guessed. Investigation-only; writes
ml/evaluation/as_live_levers.json. Slow part is the scoring (minutes); every variant afterwards takes seconds.

    python scripts/as_live_levers.py [--split backtest] [--only "veto" "hold-on"]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

ML_DIR = ROOT_DIR / "ml"


def build_inputs(split: str):
    from aq_cli import _blend_raw_scores_for_dataset, _universe_asset_metadata
    from evaluation.live_parity import LATE_BAR_ASSET_CLASSES, build_candidate_metadata, lag_predictions_for_tickers
    from execution.cost_model import commission_bps_by_ticker
    from features import load_sector_mapping

    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    ranking = config["phase1"]["target"]["ranking"]
    net_perf = ranking["net_performance"]
    dataset = pd.read_csv(ML_DIR / "datasets" / "full_dataset.csv")
    dataset = dataset[dataset["training_eligible"]]
    dataset = dataset[dataset["split"] == split].reset_index(drop=True)
    window = int(config.get("phase_v2", {}).get("sequence_model", {}).get("window_size", 30))
    raw_scores, _policy = _blend_raw_scores_for_dataset(dataset, config, window)
    asset_class_by_ticker, eligible_by_ticker = _universe_asset_metadata(config)
    frame = dataset.copy()
    frame["live_rank_score"] = raw_scores
    late = {ticker for ticker, kind in asset_class_by_ticker.items() if kind in LATE_BAR_ASSET_CLASSES}
    lagged = lag_predictions_for_tickers(frame, prediction_column="live_rank_score", tickers=late)
    security_types = {str(a["ticker"]): str(a["security_type"]) for a in config["phase1"]["universe"]["assets"]}
    base = dict(
        prediction_column="live_rank_score", forward_return_column="target_return_1d", ticker_column="ticker", date_column="date",
        top_n=int(net_perf.get("top_n", 6)), bottom_n=int(net_perf.get("bottom_n", 6)),
        rebalance_every_bars=int(net_perf.get("rebalance_every_bars", 10)),
        cost_bps_per_side=float(net_perf.get("cost_bps_per_side", 5.0)), commission_bps=float(net_perf.get("commission_bps", 1.0)),
        gross_exposure=float(net_perf.get("gross_exposure", 1.0)), dollar_neutral=bool(net_perf.get("dollar_neutral", True)),
        sector_neutral=bool(net_perf.get("sector_neutral", True)), sector_by_ticker=load_sector_mapping(config),
        hysteresis_rank_margin=float(net_perf.get("hysteresis_rank_margin", 0.0)),
        max_weight_per_name=float(net_perf.get("max_weight_per_name", 0.12)),
        min_universe_size=int(ranking.get("min_universe_size", 20)),
        commission_bps_by_ticker=commission_bps_by_ticker(config["phase_v2"].get("costs", {}), security_types) or None,
    )
    return config, frame, lagged, base, build_candidate_metadata(asset_class_by_ticker, eligible_by_ticker)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", default="backtest")
    parser.add_argument("--only", nargs="*", help="run only variants whose name contains one of these substrings (plus the as-live baseline)")
    args = parser.parse_args()

    from evaluation import simulate_rank_book
    from evaluation.live_parity import build_as_live_kwargs, make_rolling_ic_gate_fn

    config, frame, lagged_frame, base, metadata = build_inputs(args.split)
    phase_v2 = config["phase_v2"]
    ic_config = dict(phase_v2.get("rolling_ic_gate", {}))

    gates: dict = {}

    def gate_for(frame_for_run, ic_floor):
        # the gate caches per date, so variants on the same scores and floor share one
        key = (id(frame_for_run), ic_floor)
        if key not in gates:
            gate_config = dict(ic_config)
            if ic_floor is not None:
                gate_config["min_rolling_mean_ic"] = ic_floor
            gates[key] = make_rolling_ic_gate_fn(frame_for_run, raw_score_column="live_rank_score", gate_config=gate_config)
        return gates[key]

    def as_live(frame_for_run, *, ic_floor=None, **overrides):
        gate = gate_for(frame_for_run, ic_floor) if ic_floor != "off" else None
        kwargs = build_as_live_kwargs(
            dict(base), book_config=phase_v2.get("portfolio_book", {}), exits_config=phase_v2.get("exits", {}),
            max_position_weight=float(config.get("phase6", {}).get("risk", {}).get("max_position_weight", 0.25)),
            candidate_metadata=metadata, rolling_ic_gate_fn=gate, topology_config=phase_v2.get("topology", {}),
        )
        kwargs.update(overrides)
        return simulate_rank_book(frame_for_run, **kwargs)

    variants = {
        "idealized (no live mechanism)": lambda: simulate_rank_book(frame, **dict(base)),
        "as-live (config)": lambda: as_live(lagged_frame),
        "no gates at all": lambda: as_live(lagged_frame, ic_floor="off", min_rank_confidence_spread=0.0),
        "spread gate only": lambda: as_live(lagged_frame, ic_floor="off"),
        "IC gate only": lambda: as_live(lagged_frame, min_rank_confidence_spread=0.0),
        "no elevated-topology entry veto": lambda: as_live(lagged_frame, entry_veto_column=None),
        "no max-holding age exit": lambda: as_live(lagged_frame, max_holding_dates=None),
        "entry lag 0": lambda: as_live(lagged_frame, entry_lag_bars=0),
        "forex/crypto not lagged a day": lambda: as_live(frame),
        "no hold-on-veto": lambda: as_live(lagged_frame, hold_positions_on_veto=False),
        "no confidence weighting": lambda: as_live(lagged_frame, live_weighting=False),
        "no hysteresis": lambda: as_live(lagged_frame, hysteresis_rank_margin=0.0),
        "spread 0.2831 (old models' value)": lambda: as_live(lagged_frame, min_rank_confidence_spread=0.2831),
        "IC floor 0.00": lambda: as_live(lagged_frame, ic_floor=0.0),
        "IC floor 0.02": lambda: as_live(lagged_frame, ic_floor=0.02),
        "IC floor 0.10": lambda: as_live(lagged_frame, ic_floor=0.10),
    }
    if args.only:
        variants = {name: run for name, run in variants.items() if name.startswith("as-live") or any(token in name for token in args.only)}
    rows = {}
    print(f"{'variant':38s} {'net_sharpe':>10s} {'net_ret%':>9s} {'maxDD%':>8s} {'rebal':>6s} {'veto':>5s} {'names L/S':>10s}")
    for name, run in variants.items():
        started = perf_counter()
        result = run()
        rows[name] = {
            "net_sharpe": result.net_sharpe, "net_total_return": result.net_total_return,
            "net_max_drawdown": result.net_max_drawdown, "num_rebalances": result.num_rebalances,
            "num_vetoed_rebalances": result.num_vetoed_rebalances, "veto_reasons": result.veto_reasons,
            "mean_names_long": result.mean_names_long, "mean_names_short": result.mean_names_short,
        }
        print(
            f"{name:38s} {result.net_sharpe:10.3f} {100 * result.net_total_return:9.2f} {100 * result.net_max_drawdown:8.2f} "
            f"{result.num_rebalances:6d} {result.num_vetoed_rebalances:5d} {result.mean_names_long:4.1f}/{result.mean_names_short:4.1f}"
            f"  ({perf_counter() - started:.0f}s)",
            flush=True,
        )
    suffix = "" if args.split == "backtest" else "_" + args.split
    out = ML_DIR / "evaluation" / f"as_live_levers{suffix}.json"
    out.write_text(json.dumps({"split": args.split, "variants": rows}, indent=2), encoding="utf-8")
    print(f"written {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
