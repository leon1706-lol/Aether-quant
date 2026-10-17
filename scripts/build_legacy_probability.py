"""The legacy signal's probability for every dataset row (V6.1.0, rule R-CAL2 / R-LEGACY; Problems.md #190).

main.py's legacy signal trades non-members on `final_probability_up`: the gating blend of the baseline model, the four
regime experts (quality- and regime-weighted) and the sequence model's direction head (`moe.gating.build_gating_decision`,
`phase_v2.gating_network`). The dataset has no such column; this replays it per row with the installed models (or a
candidate's sequence members, averaged as live's ensemble does) so the offline simulator can model the legacy component.

The gating regime is `regime.market_regime.build_market_regime_vector` on the row's raw features with the configured
thresholds and `portfolio_drawdown=0.0`: live passes the account drawdown, which a dataset row cannot know (in a
backtest the drawdown never triggers risk-off - `bypass_regime_drawdown_gate` - so only the risk-on clause differs).

    python scripts/build_legacy_probability.py [--dataset ml/datasets/full_dataset.csv] [--ml-dir ml]
        [--sequence-members DIR ...] [--splits validation backtest holdout] [--out ml/datasets/legacy_probability.csv]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

CONTEXT_DAYS = 60  # the sequence windows of the first rows need earlier bars


def regime_thresholds(config: dict) -> dict:
    """The thresholds main.py passes to build_market_regime_vector (dynamic_risk volatility, regime_detection)."""
    risk = config.get("phase_v2", {}).get("dynamic_risk", {})
    regime = config.get("phase_v2", {}).get("regime_detection", {})
    return {
        "bullish_threshold": float(regime.get("bullish_threshold", 0.02)),
        "bearish_threshold": float(regime.get("bearish_threshold", -0.02)),
        "low_volatility_threshold": float(risk.get("low_volatility_threshold", 0.01)),
        "high_volatility_threshold": float(risk.get("high_volatility_threshold", 0.03)),
        "risk_off_drawdown_threshold": float(regime.get("risk_off_drawdown_threshold", 0.08)),
        "risk_on_drawdown_threshold": float(regime.get("risk_on_drawdown_threshold", 0.03)),
        "high_correlation_threshold": float(regime.get("high_correlation_threshold", 0.75)),
    }


def legacy_probability(raw_features: dict, baseline: float | None, experts: dict[str, float | None],
                       sequence_direction: float | None, expert_metrics: dict, config: dict) -> float:
    """One row's final_probability_up, through the same gating call main.py's Pass 1c makes (learned gating off)."""
    from moe.gating import build_gating_decision
    from regime.market_regime import build_market_regime_vector

    gating = config.get("phase_v2", {}).get("gating_network", {})
    regime = build_market_regime_vector(
        raw_features, portfolio_drawdown=0.0,
        average_correlation=float(raw_features.get("topology_correlation_strength", 0.0) or 0.0), **regime_thresholds(config),
    ).to_dict()
    decision = build_gating_decision(
        regime=regime, expert_training_metrics=expert_metrics, expert_probabilities=experts,
        baseline_probability_up=baseline, baseline_weight=float(gating.get("baseline_weight", 0.25)),
        sequence_prediction={"direction": sequence_direction} if sequence_direction is not None else None,
        sequence_weight=float(gating.get("sequence_weight", 0.0)),
    )
    return float(decision.final_probability_up)


def main() -> int:
    from evaluation.model_predictions import predict_heads_ensemble
    from inference.exported_model import convert_state_dict_arrays, run_exported_model_rows
    from moe.gating import EXPERT_NAMES

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=str(ROOT_DIR / "ml" / "datasets" / "full_dataset.csv"))
    parser.add_argument("--ml-dir", default=str(ROOT_DIR / "ml"))
    parser.add_argument("--sequence-members", nargs="*", default=None, help="sequence version dirs (an ensemble)")
    parser.add_argument("--splits", nargs="*", default=["validation", "backtest", "holdout"])
    parser.add_argument("--out", default=str(ROOT_DIR / "ml" / "datasets" / "legacy_probability.csv"))
    args = parser.parse_args()
    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    ml_dir = Path(args.ml_dir)
    window_name = {"train": "training"}.get(args.splits[0], args.splits[0])
    first_start = pd.Timestamp(config["phase1"]["windows"][window_name]["start"])
    context_start = (first_start - pd.Timedelta(CONTEXT_DAYS, unit="D")).strftime("%Y-%m-%d")
    parts = [chunk[chunk["date"].astype(str) >= context_start] for chunk in pd.read_csv(args.dataset, chunksize=40_000)]
    frame = pd.concat(parts, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)
    wanted = frame["split"].isin(args.splits).to_numpy()

    schema = json.loads((ml_dir / "feature_schema.json").read_text(encoding="utf-8"))
    inputs = frame[schema["model_input_names"]].to_numpy(dtype=np.float64).tolist()
    baseline_export = json.loads((ml_dir / "model_weights.json").read_text(encoding="utf-8"))
    convert_state_dict_arrays(baseline_export)
    baseline = np.asarray(run_exported_model_rows(baseline_export, inputs))
    experts: dict[str, np.ndarray] = {}
    for name in EXPERT_NAMES:
        path = ml_dir / "expert_models" / name / "model_weights.json"
        if path.exists():
            export = json.loads(path.read_text(encoding="utf-8"))
            convert_state_dict_arrays(export)
            experts[name] = np.asarray(run_exported_model_rows(export, inputs))
    del inputs
    metrics_path = ml_dir / "expert_training_metrics.json"
    expert_metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}

    sequence_schema = json.loads((ml_dir / "sequence_feature_schema.json").read_text(encoding="utf-8"))
    member_dirs = [Path(item) for item in (args.sequence_members or [])] or [ml_dir]
    sequence_exports = [json.loads((directory / "sequence_model.json").read_text(encoding="utf-8")) for directory in member_dirs]
    window = int(config.get("phase_v2", {}).get("sequence_model", {}).get("window_size", 30))
    direction = predict_heads_ensemble(
        frame, sequence_exports, sequence_schema["model_input_names"], ["direction"], model_kind="sequence",
        sequence_feature_schema=sequence_schema, configured_window_size=window, batched=True,
    )["direction"]

    raw_names = [name for name in schema["feature_names"] if name in frame.columns]
    raw = frame[raw_names].to_dict("records")
    probabilities = np.full(len(frame), np.nan)
    for index in np.flatnonzero(wanted):
        expert_values = {name: float(values[index]) for name, values in experts.items()}
        seq = float(direction[index]) if direction[index] == direction[index] else None
        probabilities[index] = legacy_probability(raw[index], float(baseline[index]), expert_values, seq, expert_metrics, config)
    out = frame.loc[wanted, ["date", "ticker"]].assign(final_probability_up=probabilities[wanted])
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    print(f"written {args.out}: {len(out)} rows, mean {np.nanmean(out['final_probability_up']):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
