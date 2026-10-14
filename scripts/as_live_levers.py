"""One-lever-at-a-time attribution of the as-live rank book (V5.6.0, rebuilt in V5.7.0).

`aq evaluate --rank-book --as-live` reports one number; this scores the dataset ONCE with the live blended head, then
re-runs the same simulator with each live mechanism switched off (or each gate value changed) so the gap between the
idealized and the as-live Sharpe is attributed instead of guessed. Investigation-only; writes
ml/evaluation/as_live_levers.json. The slow part is scoring (minutes, cached on disk per split and model fingerprint);
every variant afterwards takes seconds because the rolling-IC state is computed once per score set.

    python scripts/as_live_levers.py [--split backtest] [--only "veto" "hold-on"]

`AsLiveHarness` is the reusable part (scripts/gate_research.py builds its grids on it).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

ML_DIR = ROOT_DIR / "ml"
CACHE_DIR = ML_DIR / "evaluation" / "cache"
MODEL_FINGERPRINT_FILES = (
    "multitask_model.json", "multitask_feature_schema.json", "sequence_model.json", "sequence_feature_schema.json",
    "multitask_training_metrics.json", "sequence_training_metrics.json",
)


def _fingerprint(config: dict, dataset_path: Path) -> str:
    digest = hashlib.sha1()
    for name in MODEL_FINGERPRINT_FILES:
        path = ML_DIR / name
        digest.update(f"{name}:{path.stat().st_size if path.exists() else 0}:{int(path.stat().st_mtime) if path.exists() else 0}".encode())
    digest.update(f"dataset:{dataset_path.stat().st_size}:{int(dataset_path.stat().st_mtime)}".encode())
    digest.update(json.dumps(config.get("phase_v2", {}).get("rank_signal", {}), sort_keys=True).encode())
    return digest.hexdigest()[:16]


class AsLiveHarness:
    """The scored dataset of one split plus everything needed to run any as-live variant of it."""

    def __init__(
        self, split: str, *, use_cache: bool = True, dataset_path: str | Path | None = None, rl_model_path: str | Path | None = None,
        topology_inputs_fn=None,
    ):
        from aq_cli import _blend_raw_scores_for_dataset, _core_quality_tickers, _universe_asset_metadata
        from evaluation.live_parity import LATE_BAR_ASSET_CLASSES, build_candidate_metadata, lag_predictions_for_tickers
        from execution.cost_model import commission_bps_by_ticker
        from features import load_sector_mapping

        self.split = split
        self.rl_model_path = str(rl_model_path) if rl_model_path else None
        self.topology_inputs_fn = topology_inputs_fn
        self.config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
        ranking = self.config["phase1"]["target"]["ranking"]
        net_perf = ranking["net_performance"]
        dataset_path = Path(dataset_path) if dataset_path else ML_DIR / "datasets" / "full_dataset.csv"
        # Every row, observation-only names included: main.py's percentile normalisation (hysteresis margins, the
        # confidence the sizing chain reads) runs over every symbol with features, eligible or not. Read in chunks
        # and keep only this split's rows: the whole 250-column file is ~0.5 GB resident on the 4 GB dev PC (V5.8.0).
        parts = [
            chunk[chunk["split"] == split]
            for chunk in pd.read_csv(dataset_path, chunksize=40_000)
        ]
        dataset = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        del parts
        window = int(self.config.get("phase_v2", {}).get("sequence_model", {}).get("window_size", 30))

        cache_path = CACHE_DIR / f"live_rank_score_allrows_{split}_{_fingerprint(self.config, dataset_path)}.npy"
        if use_cache and cache_path.exists():
            raw_scores = np.load(cache_path)
        else:
            raw_scores, _policy = _blend_raw_scores_for_dataset(dataset, self.config, window)
            raw_scores = np.asarray(raw_scores, dtype=float)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            np.save(cache_path, raw_scores)

        self.asset_class_by_ticker, eligible_by_ticker = _universe_asset_metadata(self.config)
        self.metadata = build_candidate_metadata(self.asset_class_by_ticker, eligible_by_ticker)
        from evaluation.live_parity import build_rank_groups

        self.rank_groups = build_rank_groups(self.config, self.asset_class_by_ticker)
        from evaluation.live_parity import load_live_venue_listing_dates

        self.venue_listing_dates = load_live_venue_listing_dates(self.config, ROOT_DIR)
        self.core_crypto = _core_quality_tickers()
        self.frame = dataset
        self.frame["live_rank_score"] = raw_scores
        late = {t for t, kind in self.asset_class_by_ticker.items() if kind in LATE_BAR_ASSET_CLASSES}
        self.lagged_frame = lag_predictions_for_tickers(self.frame, prediction_column="live_rank_score", tickers=late)
        security_types = {str(a["ticker"]): str(a["security_type"]) for a in self.config["phase1"]["universe"]["assets"]}
        self.base = dict(
            prediction_column="live_rank_score", forward_return_column="target_return_1d", ticker_column="ticker", date_column="date",
            top_n=int(net_perf.get("top_n", 6)), bottom_n=int(net_perf.get("bottom_n", 6)),
            rebalance_every_bars=int(net_perf.get("rebalance_every_bars", 10)),
            cost_bps_per_side=float(net_perf.get("cost_bps_per_side", 5.0)), commission_bps=float(net_perf.get("commission_bps", 1.0)),
            gross_exposure=float(net_perf.get("gross_exposure", 1.0)), dollar_neutral=bool(net_perf.get("dollar_neutral", True)),
            sector_neutral=bool(net_perf.get("sector_neutral", True)), sector_by_ticker=load_sector_mapping(self.config),
            hysteresis_rank_margin=float(net_perf.get("hysteresis_rank_margin", 0.0)),
            max_weight_per_name=float(net_perf.get("max_weight_per_name", 0.12)),
            min_universe_size=int(ranking.get("min_universe_size", 20)),
            commission_bps_by_ticker=commission_bps_by_ticker(self.config["phase_v2"].get("costs", {}), security_types) or None,
        )
        self.phase_v2 = self.config["phase_v2"]
        self.ic_config = dict(self.phase_v2.get("rolling_ic_gate", {}))
        self._states: dict = {}
        self._gates: dict = {}
        self._mechanisms: dict = {}

    # -- gates ---------------------------------------------------------------------------------------------------
    def gate_for(self, frame, *, ic_floor=None, horizon_days=None, rolling_window_days=None, min_names=None):
        """Rolling-IC gate for `frame`'s scores. The state depends on (horizon, window, min names) only, so every floor
        variant shares it; the floor is applied afterwards."""
        from evaluation.live_parity import make_rolling_ic_gate_fn
        from evaluation.rolling_ic_gate_calibration import build_event_buffer
        from evaluation.rolling_ic_series import make_rolling_ic_state_fn

        horizon = int(horizon_days if horizon_days is not None else self.ic_config.get("horizon_days", 20))
        window = int(rolling_window_days if rolling_window_days is not None else self.ic_config.get("rolling_window_days", 40))
        names = int(min_names if min_names is not None else self.ic_config.get("min_names_per_date", 10))
        state_key = (id(frame), horizon, window, names)
        if state_key not in self._states:
            from evaluation.live_parity import main_group_tickers

            main_tickers = main_group_tickers(self.rank_groups, frame["ticker"].unique())
            event_frame = frame if main_tickers is None else frame[frame["ticker"].astype(str).isin(main_tickers)]
            self._states[state_key] = make_rolling_ic_state_fn(
                build_event_buffer(event_frame, raw_score_column="live_rank_score"),
                horizon_days=horizon, rolling_window_days=window, min_names_per_date=names,
            )
        gate_config = dict(self.ic_config, horizon_days=horizon, rolling_window_days=window, min_names_per_date=names)
        if ic_floor is not None:
            gate_config["min_rolling_mean_ic"] = ic_floor
        gate_key = (state_key, gate_config.get("min_rolling_mean_ic"), gate_config.get("min_resolved_dates_required"))
        if gate_key not in self._gates:
            self._gates[gate_key] = make_rolling_ic_gate_fn(
                frame, raw_score_column="live_rank_score", gate_config=gate_config, state_fn=self._states[state_key]
            )
        return self._gates[gate_key]

    def mechanisms(self, frame, include):
        from evaluation.live_parity import build_live_mechanisms

        key = (id(frame), tuple(include))
        if key not in self._mechanisms:
            self._mechanisms[key] = build_live_mechanisms(
                self.config, frame, core_crypto_tickers=self.core_crypto, include=tuple(include), rl_model_path=self.rl_model_path,
                topology_inputs_fn=self.topology_inputs_fn,
            )
        return self._mechanisms[key]

    # -- runs ----------------------------------------------------------------------------------------------------
    def idealized(self):
        from evaluation import simulate_rank_book

        return simulate_rank_book(self.frame, **dict(self.base))

    def as_live(self, *, lagged=True, ic_floor=None, gate="on", include=("kill_switch", "member_sizing", "hrp", "impact"),
                gate_window=None, gate_horizon=None, gate_min_names=None, config_overrides=None, **overrides):
        """One as-live run. `include` selects the optional mechanisms (kill switch, member sizing chain, HRP, impact);
        `config_overrides` ({dotted.phase_v2.key: value}) changes the live config for this run only."""
        from evaluation import simulate_rank_book
        from evaluation.live_parity import build_as_live_kwargs
        from portfolio.book_construction import resolve_class_weight_caps

        frame = self.lagged_frame if lagged else self.frame
        config = self.config
        if config_overrides:
            import copy

            config = copy.deepcopy(self.config)
            for dotted, value in config_overrides.items():
                node = config["phase_v2"]
                *parents, leaf = dotted.split(".")
                for part in parents:
                    node = node.setdefault(part, {})
                node[leaf] = value
        phase_v2 = config["phase_v2"]
        gate_fn = None
        if gate != "off":
            gate_fn = self.gate_for(
                frame, ic_floor=ic_floor if ic_floor is not None else phase_v2.get("rolling_ic_gate", {}).get("min_rolling_mean_ic"),
                horizon_days=gate_horizon, rolling_window_days=gate_window, min_names=gate_min_names,
            )
        if config is self.config:
            mechanisms = self.mechanisms(frame, include)
        else:
            from evaluation.live_parity import build_live_mechanisms

            mechanisms = build_live_mechanisms(
                config, frame, core_crypto_tickers=self.core_crypto, include=tuple(include), rl_model_path=self.rl_model_path,
                topology_inputs_fn=self.topology_inputs_fn,
            )
        kwargs = build_as_live_kwargs(
            dict(self.base), book_config=phase_v2.get("portfolio_book", {}), exits_config=phase_v2.get("exits", {}),
            max_position_weight=float(config.get("phase6", {}).get("risk", {}).get("max_position_weight", 0.25)),
            candidate_metadata=self.metadata, rolling_ic_gate_fn=gate_fn, topology_config=phase_v2.get("topology", {}),
            rank_group_by_ticker=self.rank_groups, venue_listing_dates=self.venue_listing_dates,
            class_weight_caps=resolve_class_weight_caps(phase_v2.get("class_weight_caps")), **mechanisms,
        )
        kwargs.update(overrides)
        return simulate_rank_book(frame, **kwargs)


def add_split_dataset_args(parser) -> None:
    """--dataset-validation / --dataset-backtest: dataset CSVs holding those splits (V5.8.0: a candidate's split files)."""
    parser.add_argument("--dataset-validation", default=None, help="dataset CSV holding the validation split")
    parser.add_argument("--dataset-backtest", default=None, help="dataset CSV holding the backtest split")


def dataset_for_split(args, split: str):
    return {"validation": args.dataset_validation, "backtest": args.dataset_backtest}[split]


def summarize(result) -> dict:
    return {
        "net_sharpe": result.net_sharpe, "net_total_return": result.net_total_return,
        "net_max_drawdown": result.net_max_drawdown, "num_rebalances": result.num_rebalances,
        "num_vetoed_rebalances": result.num_vetoed_rebalances, "veto_reasons": result.veto_reasons,
        "mean_names_long": result.mean_names_long, "mean_names_short": result.mean_names_short,
        "kill_switch_locked_dates": result.num_kill_switch_locked_dates,
        "kill_switch_frozen_decisions": result.num_kill_switch_frozen_decisions,
        "annualized_turnover": result.annualized_turnover, "cost_drag_annual_bps": result.cost_drag_annual_bps,
        "mean_gross_exposure": result.mean_gross_exposure, "mean_net_exposure": result.mean_net_exposure,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", default="backtest")
    parser.add_argument("--only", nargs="*", help="run only variants whose name contains one of these substrings (plus the as-live baseline)")
    parser.add_argument("--no-cache", action="store_true", help="re-score the dataset instead of reading the cached scores")
    args = parser.parse_args()

    harness = AsLiveHarness(args.split, use_cache=not args.no_cache)
    variants = {
        "idealized (no live mechanism)": lambda: harness.idealized(),
        "as-live (config)": lambda: harness.as_live(),
        "as-live without kill switch": lambda: harness.as_live(include=("member_sizing", "hrp", "impact")),
        "as-live without member sizing chain": lambda: harness.as_live(include=("kill_switch", "hrp", "impact")),
        "as-live without either (V5.6 simulator)": lambda: harness.as_live(include=("hrp", "impact")),
        "no gates at all": lambda: harness.as_live(gate="off", min_rank_confidence_spread=0.0),
        "spread gate only": lambda: harness.as_live(gate="off"),
        "IC gate only": lambda: harness.as_live(min_rank_confidence_spread=0.0),
        "no elevated-topology entry veto": lambda: harness.as_live(entry_veto_column=None),
        "veto applies to members (pre-round-3)": lambda: harness.as_live(entry_veto_column="topology_risk_elevated"),
        "no max-holding age exit": lambda: harness.as_live(max_holding_dates=None),
        "entry lag 0": lambda: harness.as_live(entry_lag_bars=0),
        "forex/crypto not lagged a day": lambda: harness.as_live(lagged=False),
        "no hold-on-veto (anchor kept)": lambda: harness.as_live(hold_positions_on_veto=False),
        "no hold-on-veto (anchor also off)": lambda: harness.as_live(hold_positions_on_veto=False, hysteresis_anchor_on_formed_book=False),
        "no confidence weighting": lambda: harness.as_live(live_weighting=False),
        "no hysteresis": lambda: harness.as_live(hysteresis_rank_margin=0.0),
        "spread 0.2831 (old models' value)": lambda: harness.as_live(min_rank_confidence_spread=0.2831),
        "IC floor 0.00": lambda: harness.as_live(ic_floor=0.0),
        "IC floor 0.02": lambda: harness.as_live(ic_floor=0.02),
        "IC floor 0.10": lambda: harness.as_live(ic_floor=0.10),
        "HRP allocation": lambda: harness.as_live(config_overrides={"portfolio_book.allocation_method": "hrp"}),
    }
    if args.only:
        variants = {name: run for name, run in variants.items() if name.startswith("as-live (") or any(token in name for token in args.only)}
    rows = {}
    print(f"{'variant':44s} {'net_sharpe':>10s} {'net_ret%':>9s} {'maxDD%':>8s} {'rebal':>6s} {'veto':>5s} {'ks_lock':>7s} {'names L/S':>10s}")
    for name, run in variants.items():
        started = perf_counter()
        result = run()
        rows[name] = summarize(result)
        print(
            f"{name:44s} {result.net_sharpe:10.3f} {100 * result.net_total_return:9.2f} {100 * result.net_max_drawdown:8.2f} "
            f"{result.num_rebalances:6d} {result.num_vetoed_rebalances:5d} {result.num_kill_switch_locked_dates:7d} "
            f"{result.mean_names_long:4.1f}/{result.mean_names_short:4.1f}  ({perf_counter() - started:.0f}s)",
            flush=True,
        )
    suffix = "" if args.split == "backtest" else "_" + args.split
    out = ML_DIR / "evaluation" / f"as_live_levers{suffix}.json"
    out.write_text(json.dumps({"split": args.split, "variants": rows}, indent=2), encoding="utf-8")
    print(f"written {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
