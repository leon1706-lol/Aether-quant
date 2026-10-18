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
LEGACY_PROBABILITY_COLUMN = "legacy_probability_up"
MODEL_FINGERPRINT_FILES = (
    "multitask_model.json", "multitask_feature_schema.json", "sequence_model.json", "sequence_feature_schema.json",
    "multitask_training_metrics.json", "sequence_training_metrics.json",
)


def _fingerprint(config: dict, dataset_path: Path, ml_dir: Path = ML_DIR) -> str:
    digest = hashlib.sha1()
    if ml_dir != ML_DIR:
        digest.update(str(ml_dir.resolve()).encode())
    for name in MODEL_FINGERPRINT_FILES:
        path = ml_dir / name
        digest.update(f"{name}:{path.stat().st_size if path.exists() else 0}:{int(path.stat().st_mtime) if path.exists() else 0}".encode())
    digest.update(f"dataset:{dataset_path.stat().st_size}:{int(dataset_path.stat().st_mtime)}".encode())
    digest.update(json.dumps(config.get("phase_v2", {}).get("rank_signal", {}), sort_keys=True).encode())
    return digest.hexdigest()[:16]


class AsLiveHarness:
    """The scored dataset of one split plus everything needed to run any as-live variant of it."""

    def __init__(
        self, split: str, *, use_cache: bool = True, dataset_path: str | Path | None = None, rl_model_path: str | Path | None = None,
        topology_inputs_fn=None, ml_dir: str | Path | None = None, config: dict | None = None,
        legacy_probability_path: str | Path | None = None, gate_warmup_days: int = 0,
    ):
        from aq_cli import _blend_raw_scores_for_dataset, _core_quality_tickers, _universe_asset_metadata
        from evaluation.live_parity import LATE_BAR_ASSET_CLASSES, build_candidate_metadata, lag_predictions_for_tickers
        from execution.cost_model import commission_bps_by_ticker, min_commission_usd_by_ticker
        from features import load_sector_mapping

        self.split = split
        splits = (split,) if isinstance(split, str) else tuple(split)  # V6.0.0: e.g. ("backtest", "holdout") for one Lean run
        self.rl_model_path = str(rl_model_path) if rl_model_path else None
        self.topology_inputs_fn = topology_inputs_fn
        self.config = config if config is not None else json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
        ranking = self.config["phase1"]["target"]["ranking"]
        net_perf = ranking["net_performance"]
        dataset_path = Path(dataset_path) if dataset_path else ML_DIR / "datasets" / "full_dataset.csv"
        # Every row, observation-only names included: main.py's percentile normalisation (hysteresis margins, the
        # confidence the sizing chain reads) runs over every symbol with features, eligible or not. Read in chunks
        # and keep only this split's rows: the whole 250-column file is ~0.5 GB resident on the 4 GB dev PC (V5.8.0).
        # V6.1.0: `gate_warmup_days` also keeps the rows that far before the first split's start, so the rolling-IC gate is
        # warm on day one as live's is (main.py fills its event buffer through the warm-up); they never enter the book.
        warmup_start = None
        if gate_warmup_days > 0:
            window_name = {"train": "training"}.get(splits[0], splits[0])
            first_start = self.config["phase1"]["windows"].get(window_name, {}).get("start")
            if first_start:
                warmup_start = (pd.Timestamp(first_start) - pd.Timedelta(int(gate_warmup_days), unit="D")).strftime("%Y-%m-%d")
        parts, context_parts = [], []
        for chunk in pd.read_csv(dataset_path, chunksize=40_000):
            parts.append(chunk[chunk["split"].isin(splits)])
            if warmup_start is not None:
                dates = chunk["date"].astype(str)
                context_parts.append(chunk[~chunk["split"].isin(splits) & (dates >= warmup_start) & (dates < str(first_start))])
        dataset = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        context = pd.concat(context_parts, ignore_index=True) if context_parts else pd.DataFrame()
        del parts, context_parts
        window = int(self.config.get("phase_v2", {}).get("sequence_model", {}).get("window_size", 30))

        self.ml_dir = Path(ml_dir) if ml_dir else ML_DIR
        warm_tag = f"_warm{int(gate_warmup_days)}" if warmup_start is not None else ""
        cache_path = CACHE_DIR / f"live_rank_score_allrows_{'+'.join(splits)}{warm_tag}_{_fingerprint(self.config, dataset_path, self.ml_dir)}.npy"
        scored = pd.concat([context, dataset], ignore_index=True) if len(context) else dataset
        if use_cache and cache_path.exists():
            raw_scores = np.load(cache_path)
        else:
            raw_scores, _policy = _blend_raw_scores_for_dataset(scored, self.config, window, ml_dir=self.ml_dir)
            raw_scores = np.asarray(raw_scores, dtype=float)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            np.save(cache_path, raw_scores)
        context_scores, raw_scores = raw_scores[: len(context)], raw_scores[len(context):]

        self.asset_class_by_ticker, eligible_by_ticker = _universe_asset_metadata(self.config)
        self.metadata = build_candidate_metadata(self.asset_class_by_ticker, eligible_by_ticker)
        from evaluation.live_parity import build_rank_groups

        self.rank_groups = build_rank_groups(self.config, self.asset_class_by_ticker)
        from evaluation.live_parity import load_live_venue_listing_dates

        self.venue_listing_dates = load_live_venue_listing_dates(self.config, ROOT_DIR)
        self.core_crypto = _core_quality_tickers()
        self.frame = dataset
        self.frame["live_rank_score"] = raw_scores
        self.context_frame = context.assign(live_rank_score=context_scores) if len(context) else None
        if legacy_probability_path:
            # V6.1.0: final_probability_up per (date, ticker) from scripts/build_legacy_probability.py (the legacy signal)
            probability = pd.read_parquet(legacy_probability_path) if str(legacy_probability_path).endswith(".parquet") \
                else pd.read_csv(legacy_probability_path)
            probability = probability.assign(date=probability["date"].astype(str).str[:10])[["date", "ticker", "final_probability_up"]]
            self.frame = self.frame.assign(date=self.frame["date"].astype(str).str[:10]).merge(
                probability.rename(columns={"final_probability_up": LEGACY_PROBABILITY_COLUMN}), on=["date", "ticker"], how="left"
            )
        from evaluation.live_parity import add_next_intraday_return

        add_next_intraday_return(self.frame)
        late = {t for t, kind in self.asset_class_by_ticker.items() if kind in LATE_BAR_ASSET_CLASSES}
        self.late_bar_tickers = frozenset(late)
        self.lagged_frame = lag_predictions_for_tickers(self.frame, prediction_column="live_rank_score", tickers=late)
        if self.context_frame is not None:
            self.context_frame = lag_predictions_for_tickers(self.context_frame, prediction_column="live_rank_score", tickers=late)
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
        # V6.0.0: the broker's per-order dollar floor at the live NAV (used when an as-live run asks for it).
        self.min_commission_usd_by_ticker = min_commission_usd_by_ticker(self.config["phase_v2"].get("costs", {}), security_types)
        # V6.0.0: live's cadence counts equity sessions only; the as-live runs rebalance on those dates.
        equity_tickers = {ticker for ticker, kind in security_types.items() if kind == "equity"}
        self.session_dates = {
            str(date) for date in self.frame.loc[self.frame["ticker"].astype(str).isin(equity_tickers), "date"].unique()
        }
        self.initial_cash = float(self.config.get("runtime", {}).get("initial_cash", 100_000.0))
        self.phase_v2 = self.config["phase_v2"]
        self.ic_config = dict(self.phase_v2.get("rolling_ic_gate", {}))
        self._states: dict = {}
        self._gates: dict = {}
        self._mechanisms: dict = {}

    # -- gates ---------------------------------------------------------------------------------------------------
    def gate_for(self, frame, *, ic_floor=None, horizon_days=None, rolling_window_days=None, min_names=None,
                 late_bar_event_count=None):
        """Rolling-IC gate for `frame`'s scores. The state depends on (horizon, window, min names, how late-bar events
        are counted) only, so every floor variant shares it; the floor is applied afterwards."""
        from portfolio.rolling_ic_gate import resolve_late_bar_event_count

        from evaluation.live_parity import make_rolling_ic_gate_fn
        from evaluation.rolling_ic_gate_calibration import build_event_buffer
        from evaluation.rolling_ic_series import make_rolling_ic_state_fn

        horizon = int(horizon_days if horizon_days is not None else self.ic_config.get("horizon_days", 20))
        window = int(rolling_window_days if rolling_window_days is not None else self.ic_config.get("rolling_window_days", 40))
        names = int(min_names if min_names is not None else self.ic_config.get("min_names_per_date", 10))
        event_count = resolve_late_bar_event_count(
            {"late_bar_event_count": late_bar_event_count} if late_bar_event_count else self.ic_config
        )
        state_key = (id(frame), horizon, window, names, event_count)
        if state_key not in self._states:
            from evaluation.live_parity import main_group_tickers

            main_tickers = main_group_tickers(self.rank_groups, frame["ticker"].unique())
            event_frame = frame
            if self.context_frame is not None:
                event_frame = pd.concat([self.context_frame[frame.columns.intersection(self.context_frame.columns)], frame],
                                        ignore_index=True)
            event_frame = event_frame if main_tickers is None else event_frame[event_frame["ticker"].astype(str).isin(main_tickers)]
            # live records a crypto event on its own tick and again on the equity tick (evaluation.live_parity.with_live_event_duplicates)
            from evaluation.live_parity import with_live_event_duplicates

            if event_count == "per_tick":
                event_frame = with_live_event_duplicates(event_frame, self.late_bar_tickers)
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

    def v610_mechanisms(self, config: dict | None = None, *, legacy: bool = True, extra_returns: dict | None = None) -> dict:
        """The V6.1.0 simulator options (rule R-CAL2), all replicas of live mechanisms: the daily member pass between
        rebalances, weekend accrual, the position cap, the legacy probability signal (when the harness has its column)
        and P&L outside the simulation that the kill switch reads."""
        from evaluation.live_parity import build_live_member_weight_fn
        from portfolio.legacy_sleeve import resolve_legacy_signal_params, resolve_legacy_sleeve_config

        config = config or self.config
        phase_v2 = config["phase_v2"]
        options = {
            "mid_cycle_member_updates": True,
            "accrue_skipped_dates": True,
            "max_active_positions": int(config.get("phase9", {}).get("portfolio", {}).get("max_active_positions", 12)),
            "kill_switch_extra_returns": extra_returns,
        }
        sleeve = resolve_legacy_sleeve_config(phase_v2.get("legacy_sleeve"))
        if legacy and sleeve["enabled"] and LEGACY_PROBABILITY_COLUMN in self.frame.columns:
            weights = json.loads((self.ml_dir / "model_weights.json").read_text(encoding="utf-8"))
            exits = phase_v2.get("exits", {})
            assets = config["phase1"]["universe"]["assets"]
            options["legacy_component"] = {
                "probability_column": LEGACY_PROBABILITY_COLUMN,
                "sleeve_config": sleeve,
                "signal": resolve_legacy_signal_params(config, float(weights["training"]["decision_threshold"])),
                "asset_classes": ("equity", "crypto"),
                "weight_fn": build_live_member_weight_fn(
                    config, security_type_by_ticker={str(a["ticker"]): str(a.get("security_type", "equity")) for a in assets},
                    nav=self.initial_cash, core_crypto_tickers=self.core_crypto, topology_inputs_fn=self.topology_inputs_fn,
                    use_live_analyzer=True,
                ),
                "max_holding_dates": int(exits["max_holding_bars"]) if exits.get("enabled") and exits.get("max_holding_bars") else None,
                "trailing_stop_pct": float(exits["trailing_stop_pct"]) if exits.get("enabled") and exits.get("trailing_stop_pct") else None,
            }
        return options

    # -- runs ----------------------------------------------------------------------------------------------------
    def idealized(self):
        from evaluation import simulate_rank_book

        return simulate_rank_book(self.frame, **dict(self.base))

    def as_live(self, *, lagged=True, ic_floor=None, gate="on", include=("kill_switch", "member_sizing", "hrp", "impact"),
                gate_window=None, gate_horizon=None, gate_min_names=None, config_overrides=None, cash_sweep=False,
                gate_event_count=None, tranches=1, **overrides):
        """One as-live run. `include` selects the optional mechanisms (kill switch, member sizing chain, HRP, impact);
        `config_overrides` ({dotted.phase_v2.key: value}) changes the live config for this run only; `cash_sweep` adds
        the V6.2.0 T-bill sweep (its own component, outside the kill switch) whatever the config says; `tranches` > 1 the
        staggered book (evaluation.tranche_book)."""
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
                late_bar_event_count=gate_event_count
                or (phase_v2.get("rolling_ic_gate", {}) or {}).get("late_bar_event_count"),
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
            class_weight_caps=resolve_class_weight_caps(phase_v2.get("class_weight_caps")),
            resize_threshold_weight=_resize_threshold(phase_v2),
            trade_cooldown_bars=int(config.get("phase6", {}).get("risk", {}).get("trade_cooldown_bars", 0)),
            **mechanisms,
        )
        kwargs["rebalance_session_dates"] = self.session_dates
        if cash_sweep:
            from evaluation.live_parity import build_cash_sweep_kwarg

            kwargs["cash_sweep"] = build_cash_sweep_kwarg(config, ROOT_DIR, force_enabled=True)
        kwargs.update(overrides)
        reset_member_state(kwargs)
        if int(tranches) > 1:
            from evaluation.tranche_book import simulate_tranche_book

            def fresh_run(data, **sub):  # every tranche run starts with a clean RL guard, as one whole run does
                reset_member_state(sub)
                return simulate_rank_book(data, **sub)

            return simulate_tranche_book(frame, tranches=int(tranches), simulate=fresh_run, **kwargs)
        return simulate_rank_book(frame, **kwargs)


def reset_member_state(kwargs: dict) -> None:
    """The member chain keeps the RL shadow guard's history between calls (`member_weight_fn.rl_state`); a closure reused by
    the next run (the harness caches it, a rule chain reuses one per split) would start that run with the previous run's
    guard verdict, so two identical runs could differ. Each run starts from a clean guard."""
    functions = [kwargs.get("member_weight_fn"), (kwargs.get("legacy_component") or {}).get("weight_fn")]
    for function in functions:
        holder = getattr(function, "rl_state", None)
        if isinstance(holder, dict):
            holder.update(history=[], positions={}, last_date=None, allows=True)


def _resize_threshold(phase_v2: dict) -> float:
    scaling = phase_v2.get("functionality", {}).get("position_scaling", {})
    return float(scaling.get("rebalance_threshold_weight", 0.03)) if scaling.get("enabled", False) else 0.0


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
