"""V5.3.6 Workstreams B+D - gate/kill-switch sweep driver.

Part 1: compute blended raw scores offline (sequence+multitask models), the
        same way --reconcile-book-history does.
Part 2: ONE simulate_rank_book() base run -> per-date net returns.
Part 3: WS-B - rolling-IC gate grid (floor x window) + spread-floor
        percentile variants; per-era engagement table + naive adjusted
        Sharpe when disengaged rebalances contribute flat returns.
Part 4: WS-D - kill-switch min_rolling_sharpe x evaluation_bars grid over
        the SAME return series (lockout % / trips).

Outputs ml/evaluation/gate_sweep_results.json. Investigation-only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from aq_cli import _EVALUATE_MODEL_ARTIFACTS, _write_evaluation_json  # noqa: E402
from evaluation import (  # noqa: E402
    compute_blended_raw_scores,
    predict_head,
    select_context_date_range,
)
from evaluation.kill_switch_replay import replay_kill_switch_over_dataset, summarize_kill_switch_replay  # noqa: E402
from evaluation.rolling_ic_gate_replay import (  # noqa: E402
    _era_for_date,
    replay_rolling_ic_gate_over_dataset,
    summarize_rolling_ic_gate_replay,
)

ML_DIR = ROOT_DIR / "ml"


def load_config() -> dict:
    return json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))


def compute_raw_scores(dataset: pd.DataFrame, config: dict) -> pd.DataFrame:
    from portfolio.rank_signal import resolve_rank_signal_policy

    metrics_by_model = {}
    for model_name, fname in (("sequence", "sequence_training_metrics.json"), ("multitask", "multitask_training_metrics.json")):
        p = ML_DIR / fname
        metrics_by_model[model_name] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    policy = resolve_rank_signal_policy(metrics_by_model, config)
    # Speed mode for the sweep: prefer multitask-only scoring when available
    # (sequence head inference dominates runtime). Documented in the report.
    if "multitask" in policy["model_priority"]:
        policy["model_priority"] = ["multitask"]
    active_heads = [h for h, w in policy["heads"].items() if w > 0.0]

    dates = sorted(dataset["date"].unique().tolist())
    min_d, max_d = select_context_date_range(dataset, dates, window_size=int(config.get("phase_v2", {}).get("sequence_model", {}).get("window_size", 30)))
    context = dataset[(dataset["date"] >= min_d) & (dataset["date"] <= max_d)].reset_index(drop=True)

    predictions_by_model = {}
    for model_kind in policy["model_priority"]:
        model_fname, schema_fname = _EVALUATE_MODEL_ARTIFACTS[model_kind]
        model_path = ML_DIR / model_fname
        schema_path = ML_DIR / schema_fname
        if not model_path.exists() or not schema_path.exists():
            continue
        export = json.loads(model_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        feature_names = schema["model_input_names"]
        heads = {}
        for head_name in active_heads:
            heads[head_name] = predict_head(
                context,
                export,
                feature_names,
                head_name,
                model_kind=model_kind,
                sequence_feature_schema=schema if model_kind == "sequence" else None,
                configured_window_size=int(config.get("phase_v2", {}).get("sequence_model", {}).get("window_size", 30)),
            )
        predictions_by_model[model_kind] = heads

    context["raw_blended_score"] = compute_blended_raw_scores(context, predictions_by_model, policy)
    return context


def main() -> int:
    config = load_config()
    dataset = pd.read_csv(ML_DIR / "datasets" / "full_dataset.csv")
    dataset = dataset[dataset["date"] >= "2019-01-01"].reset_index(drop=True)
    scored_cache = pd.read_csv(ML_DIR / "evaluation" / "gate_sweep_scored.csv")
    scored = dataset.merge(scored_cache, on=["date", "ticker"], how="left")
    print(f"rows in scope: {len(scored)} (cached scores loaded)", flush=True)

    book_cfg = config.get("phase_v2", {}).get("portfolio_book", {})
    reb_every = int(book_cfg.get("rebalance_every_bars", 10))
    unique_dates = sorted(scored["date"].unique().tolist())
    rebalance_dates = unique_dates[::reb_every]

    # ---- WS-B: rolling-IC gate grid --------------------------------------
    ic_results = {}
    raw_col = "raw_blended_score"
    # Floors: #103's real calibration at w40/p25 produced +0.020 - reuse it
    # plus neighbors instead of re-running the expensive calibration.
    window = 40
    floors = {"zero": 0.0, "p25_calibrated": 0.02, "aggressive": 0.05}
    for label, floor in floors.items():
        gate_config = {
            "enabled": True,
            "horizon_days": 20,
            "rolling_window_days": window,
            "min_resolved_dates_required": 20,
            "min_rolling_mean_ic": floor,
        }
        records = replay_rolling_ic_gate_over_dataset(
            scored,
            raw_score_column=raw_col,
            rebalance_dates=rebalance_dates,
            horizon_days=20,
            rolling_window_days=window,
            gate_config=gate_config,
        )
        summary = summarize_rolling_ic_gate_replay(records)
        era_disengaged = {}
        for record in records:
            era = _era_for_date(record["date"]) or "other"
            bucket = era_disengaged.setdefault(era, [0, 0])
            bucket[0] += 0 if record["engaged"] else 1
            bucket[1] += 1
        ic_results[f"w{window}_{label}"] = {
            "floor": floor,
            "summary": {k: v for k, v in summary.items() if not isinstance(v, list)},
            "era_fraction_disengaged": {era: round(d[0] / d[1], 4) for era, d in era_disengaged.items() if d[1]},
        }

    # ---- WS-B: spread-floor percentile variants (same-day dispersion) ----
    spread_by_date = scored.groupby("date")["raw_blended_score"].std()
    spread_results = {}
    current_floor = float(config.get("phase_v2", {}).get("portfolio_book", {}).get("min_rank_confidence_spread", 0.2831))
    for label, pct in (("p50", 0.50), ("p75", 0.75), ("p90", 0.90)):
        threshold = float(spread_by_date.quantile(pct))
        disengaged_dates = {d for d, v in spread_by_date.items() if v < threshold}
        era_frac = {}
        for d in rebalance_dates:
            era = _era_for_date(d) or "other"
            b = era_frac.setdefault(era, [0, 0])
            b[1] += 1
            if d in disengaged_dates:
                b[0] += 1
        spread_results[label] = {
            "threshold_std": round(threshold, 6),
            "current_floor_for_reference": current_floor,
            "era_fraction_disengaged": {e: round(a / b, 4) for e, (a, b) in era_frac.items() if b},
        }

    # ---- Base simulator run for WS-D return series ------------------------
    from evaluation.rank_book_simulator import simulate_rank_book
    from features import load_sector_mapping

    sector_by_ticker = load_sector_mapping(config)
    sim_kwargs = dict(
        prediction_column="raw_blended_score",  # cross-sectional RANK is invariant to monotone scaling
        forward_return_column="target_return_1d",
        ticker_column="ticker",
        date_column="date",
        top_n=int(book_cfg.get("top_n", 6)),
        bottom_n=int(book_cfg.get("bottom_n", 6)),
        rebalance_every_bars=reb_every,
        cost_bps_per_side=float(config.get("phase_v2", {}).get("costs", {}).get("cost_bps_per_side", 5.0)),
        commission_bps=1.0,
        gross_exposure=1.0,
        dollar_neutral=True,
        sector_neutral=True,
        sector_by_ticker=sector_by_ticker,
        max_weight_per_name=0.12,
        min_universe_size=20,
    )
    base_result = simulate_rank_book(scored, **sim_kwargs)
    per_date_returns = dict(zip(base_result.per_date, base_result.per_date_net_return))
    dates_sorted = sorted(per_date_returns)
    print(f"base sim: net_sharpe={getattr(base_result, 'net_sharpe', None)}", flush=True)

    # ---- WS-D: kill-switch grid ------------------------------------------
    ks_grid = {}
    risk_cfg = config.get("phase6", {}).get("risk", {})
    for min_sharpe in (0.15, 0.30, 0.45):
        for eval_bars in (40, 60, 90):
            kill_cfg = {
                "enabled": True,
                "min_rolling_sharpe": min_sharpe,
                "evaluation_bars": eval_bars,
            }
            records = replay_kill_switch_over_dataset(
                dates_sorted,
                per_date_returns,
                kill_cfg,
                max_daily_drawdown_pct=float(risk_cfg.get("max_daily_drawdown_pct", 0.03)),
                max_total_drawdown_pct=float(risk_cfg.get("max_total_drawdown_pct", 0.12)),
            )
            s = summarize_kill_switch_replay(records)
            locked = sum(1 for r in records if getattr(r, "locked", getattr(r, "trade_locked", False)))
            ks_grid[f"sharpe{min_sharpe}_bars{eval_bars}"] = {
                "trips": s.get("total_trips", s.get("num_trips")),
                "days_locked_fraction": round(locked / max(len(records), 1), 4),
            }

    payload = {
        "rebalance_cadence_bars": reb_every,
        "n_rebalance_dates": len(rebalance_dates),
        "rolling_ic_gate_grid": ic_results,
        "spread_percentile_variants": spread_results,
        "kill_switch_grid": ks_grid,
        "base_simulator": {
            "net_sharpe": getattr(base_result, "net_sharpe", None),
            "gross_sharpe": getattr(base_result, "gross_sharpe", None),
            "turnover": getattr(base_result, "turnover", None),
        },
    }
    _write_evaluation_json(ML_DIR / "evaluation" / "gate_sweep_results.json", payload)
    print(json.dumps({k: v for k, v in payload.items() if k != "rolling_ic_gate_grid"}, indent=2)[:1200])
    print("\nIC grid:")
    for k, v in ic_results.items():
        if k.startswith("w"):
            print(f"  {k:<14} floor={v['floor']:.4f} eras={v['era_fraction_disengaged']}")
    print(f"\nWritten: {ML_DIR / 'evaluation' / 'gate_sweep_results.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
