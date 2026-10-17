"""Orchestration for the V5.8.0 `aq evaluate` audit flags (--ic-by-class, --audit-gates, --audit-data, --audit-heads,
--audit-features). The analysis lives in the pure modules (class_ic_audit, gate_audit, data_audit, head_audit,
feature_quality_audit); this module only loads the inputs the way the live path sees them and returns JSON-ready dicts.
Heavy imports stay inside the functions so `aq` starts fast.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
ML_DIR = ROOT_DIR / "ml"


def _harness(split: str, dataset_path: str | None):
    scripts_dir = str(ROOT_DIR / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from as_live_levers import AsLiveHarness

    return AsLiveHarness(split, dataset_path=dataset_path)


def run_ic_by_class(config: dict, *, split: str, dataset_path: str | None = None) -> dict:
    """Within/between-class decomposition of the LIVE blended score against the realized 5- and 20-day returns."""
    from evaluation.class_ic_audit import class_ic_decomposition

    harness = _harness(split, dataset_path)
    frame = harness.frame.copy()
    frame["asset_class"] = frame["ticker"].map(harness.asset_class_by_ticker)
    report = {"split": split, "rows": int(len(frame)), "heads": {}}
    for target, horizon in (("target_return_20d", 20), ("target_return_5d", 5)):
        if target not in frame.columns:
            continue
        report["heads"][target] = class_ic_decomposition(
            frame, prediction="live_rank_score", target=target, horizon=horizon, min_names_per_class=5
        )
    return report


def run_audit_gates(config: dict, *, split: str, dataset_path: str | None = None) -> dict:
    """The rolling-IC gate's own reading next to the fully resolved IC on every date of the split."""
    from evaluation.gate_audit import audit_rolling_ic_gate, daily_rank_ic
    from evaluation.live_parity import main_group_tickers

    harness = _harness(split, dataset_path)
    frame = harness.lagged_frame
    gate_fn = harness.gate_for(frame)
    state_fn = next(iter(harness._states.values()))
    ic_config = harness.ic_config
    horizon = int(ic_config.get("horizon_days", 20))
    window = int(ic_config.get("rolling_window_days", 40))
    main_tickers = main_group_tickers(harness.rank_groups, frame["ticker"].unique())
    scored = frame if main_tickers is None else frame[frame["ticker"].astype(str).isin(main_tickers)]
    target = f"target_return_{horizon}d" if f"target_return_{horizon}d" in scored.columns else "target_rank_20d"
    daily = daily_rank_ic(scored, score_column="live_rank_score", target_column=target,
                          min_names_per_date=int(ic_config.get("min_names_per_date", 10)))
    equity_dates = sorted(
        frame.loc[frame["ticker"].map(harness.asset_class_by_ticker).isin({"equity", "bond"}), "date"].astype(str).unique()
    )
    report = audit_rolling_ic_gate(
        decision_dates=equity_dates, gate_fn=gate_fn, state_fn=state_fn, daily_ic=daily, trading_dates=equity_dates,
        horizon=horizon, window=window,
    )
    report.update({"split": split, "gate_config": ic_config, "target": target,
                   "grouped_main_pool_only": main_tickers is not None})
    return report


def run_audit_data(config: dict, *, data_root: Path, start: str | None = None, end: str | None = None,
                   write_manifest: bool = True) -> dict:
    from data_pipeline.data_audit import audit_non_daily_files, audit_universe, build_data_manifest

    report = audit_universe(config, data_root, start=start, end=end)
    report["non_daily_files"] = audit_non_daily_files(config, data_root)
    if write_manifest:
        manifest = build_data_manifest(data_root)
        manifest_path = Path(data_root) / "manifest_v580.json"
        with manifest_path.open("w", encoding="utf-8", newline="\n") as handle:  # LF everywhere: same bytes on Windows and Linux
            handle.write(json.dumps(manifest, indent=1, sort_keys=True))
        report["manifest"] = {"path": str(manifest_path), "num_files": len(manifest)}
    return report


def live_consumers(config: dict) -> set[str]:
    """Components the live decision path reads, from the config: the blended rank heads of every model in
    `rank_signal.model_priority`, the gating network when enabled, the experts (MoE path), RL when enabled."""
    phase_v2 = config.get("phase_v2", {})
    rank_signal = phase_v2.get("rank_signal", {})
    consumers = {
        f"{model}.{head}"
        for model in rank_signal.get("model_priority", ["sequence", "multitask"])
        for head, weight in (rank_signal.get("heads") or {"rank_20d": 1.0}).items()
        if float(weight) > 0.0 and head not in set(rank_signal.get("demoted", []))
    }
    if phase_v2.get("gating_network", {}).get("learned_model_enabled", False):
        consumers.add("gating")
    consumers.update({f"expert.{name}" for name in ("bullish", "bearish", "sideways", "volatility")})
    consumers.update({"multitask.direction", "sequence.direction", "baseline.direction"})
    if phase_v2.get("dynamic_risk", {}).get("rl_sizing_enabled", False):
        consumers.add("rl_sizing")
    if phase_v2.get("forex_sleeve", {}).get("rl_sizing_enabled", False):
        consumers.add("rl_sizing_forex")
    return consumers


def run_audit_heads(config: dict, *, ml_dir: Path = ML_DIR) -> dict:
    from evaluation.head_audit import audit_heads, load_head_metrics

    from portfolio.rank_signal import resolve_rank_signal_policy

    report = audit_heads(load_head_metrics(ml_dir), consumers=live_consumers(config))
    report["consumers"] = sorted(live_consumers(config))
    metrics_by_model = {}
    for model_name in ("sequence", "multitask"):
        path = ml_dir / f"{model_name}_training_metrics.json"
        try:
            metrics_by_model[model_name] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        except (OSError, ValueError):
            metrics_by_model[model_name] = None
    # The policy main.py resolves at Initialize(): shows when every decision head failed and live fell back to the blend.
    report["rank_signal_policy"] = resolve_rank_signal_policy(metrics_by_model, config)
    return report


def run_audit_features(config: dict, *, dataset_path: str | None = None, permutation: bool = False) -> dict:
    """Feature quality over every split of the dataset (column-pruned read), optionally with the multitask model's
    permutation IC drop on the validation split."""
    import numpy as np
    import pandas as pd

    from evaluation.feature_quality_audit import feature_quality, permutation_ic_drop

    schema = json.loads((ML_DIR / "multitask_feature_schema.json").read_text(encoding="utf-8"))
    features = list(schema["model_input_names"])
    path = Path(dataset_path) if dataset_path else ML_DIR / "datasets" / "full_dataset.csv"
    wanted = set(features) | {"date", "ticker", "split", "target_rank_20d", "training_eligible"}
    frame = pd.concat(
        [chunk for chunk in pd.read_csv(path, usecols=lambda name: name in wanted, chunksize=50_000)], ignore_index=True
    )
    asset_class = {a["ticker"]: a.get("asset_class") or a.get("security_type") for a in config["phase1"]["universe"]["assets"]}
    frame["asset_class"] = frame["ticker"].map(asset_class)
    report = feature_quality(frame, features)
    if permutation:
        from evaluation.model_predictions import predict_multitask_head

        model = json.loads((ML_DIR / "multitask_model.json").read_text(encoding="utf-8"))
        validation = frame[frame["split"] == "validation"].reset_index(drop=True)

        def predict(data):
            return np.asarray(predict_multitask_head(data, model, features, "rank_20d"))

        report["permutation_ic_drop"] = permutation_ic_drop(validation, features, predict)
    return report
