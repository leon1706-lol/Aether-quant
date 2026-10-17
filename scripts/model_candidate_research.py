"""Rule R-MODEL9 / R-HEAD2 inputs (V6.1.0): rank IC of every retrained candidate, single seeds and seed ensembles.

A candidate is a set of member version directories per model kind (`ml/versions/<id>` as `train_multitask.py` /
`train_sequence.py` write them). Each member's heads are scored on the validation, backtest and holdout rows; an
ensemble averages the members' raw head outputs (`evaluation.model_predictions.predict_heads_ensemble`, the rule live
uses). The decision score is the live blend (`phase_v2.rank_signal.heads`, sequence before multitask per head), also with the
priority swapped (`decision_rank_20d_swapped_priority`). IC is
taken inside the main rank group (equity + crypto, the book's pool) against each head's own target: daily mean, HAC t,
and the non-overlapping mean / t at the head's horizon. The holdout is reported, never used to select.

    python scripts/model_candidate_research.py --dataset ml/datasets/v610_full_dataset.csv \\
        --candidate ctl=multitask:ml/versions/v610_mt_ctl_s1,...;sequence:ml/versions/v610_seq_ctl_s1,... \\
        [--each-member] [--out ml/evaluation/v610/model_ic.json]

`--each-member` also scores every member alone (the seed spread R-MODEL9 clause 1 needs).
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

HEADS = {
    "rank_5d": ("target_rank_5d", 5), "rank_20d": ("target_rank_20d", 20),
    "sector_neutral_rank_20d": ("target_sector_neutral_rank_20d", 20),
    "residual_rank_5d": ("target_residual_rank_5d", 5), "residual_rank_20d": ("target_residual_rank_20d", 20),
}
SPLITS = ("validation", "backtest", "holdout")
MODEL_FILES = {"multitask": ("multitask_model.json", "multitask_feature_schema.json"),
               "sequence": ("sequence_model.json", "sequence_feature_schema.json")}
CONTEXT_START = "2021-09-01"  # the sequence windows of the first validation rows need earlier bars


def parse_candidate(text: str) -> tuple[str, dict[str, list[str]]]:
    """`name=multitask:dir1,dir2;sequence:dir3` -> (name, {"multitask": [...], "sequence": [...]})."""
    name, _, rest = text.partition("=")
    members: dict[str, list[str]] = {}
    for part in filter(None, rest.split(";")):
        kind, _, dirs = part.partition(":")
        if kind not in MODEL_FILES or not dirs:
            raise ValueError(f"bad --candidate part {part!r}")
        members[kind] = [item for item in dirs.split(",") if item]
    if not name or not members:
        raise ValueError(f"bad --candidate {text!r}")
    return name, members


def ic_stats(frame: pd.DataFrame, prediction: np.ndarray, target: str, horizon: int) -> dict:
    from evaluation.rank_ic_core import newey_west_t_stat, rank_ic_from_arrays

    mask = ~np.isnan(prediction) & frame[target].notna().to_numpy()
    if mask.sum() < 50:
        return {"daily_mean_ic": None, "hac_t": None, "non_overlapping_mean_ic": None, "non_overlapping_t": None, "dates": 0}
    values, targets, dates = prediction[mask], frame[target].to_numpy()[mask], frame["date"].to_numpy()[mask]
    daily = rank_ic_from_arrays(values, targets, dates, min_names_per_date=10)
    non_overlapping = rank_ic_from_arrays(values, targets, dates, non_overlapping_stride=horizon, min_names_per_date=10)
    return {
        "daily_mean_ic": daily["mean_ic"], "hac_t": newey_west_t_stat(daily["ic_values"], horizon - 1),
        "non_overlapping_mean_ic": non_overlapping["mean_ic"], "non_overlapping_t": non_overlapping["t_stat"],
        "dates": daily["num_dates"],
    }


def blend_decision_score(predictions: dict[str, dict[str, np.ndarray]], policy_heads: dict[str, float],
                         model_priority: list[str]) -> np.ndarray:
    """Per row: each configured head from the first model in `model_priority` that has a finite value, weighted by the
    configured blend (portfolio.rank_signal.select_raw_rank_score, vectorised)."""
    length = len(next(iter(next(iter(predictions.values())).values())))
    weighted, weights = np.zeros(length), np.zeros(length)
    for head, weight in policy_heads.items():
        if weight <= 0:
            continue
        value = np.full(length, np.nan)
        for kind in model_priority:
            if kind in predictions and head in predictions[kind]:
                value = np.where(np.isnan(value), predictions[kind][head], value)
        finite = ~np.isnan(value)
        weighted[finite] += weight * value[finite]
        weights[finite] += weight
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(weights > 0, weighted / np.where(weights > 0, weights, 1.0), np.nan)


def predict_kind(frame: pd.DataFrame, member_dirs: list[str], kind: str, window: int) -> dict[str, np.ndarray]:
    from evaluation.model_predictions import predict_heads_ensemble

    model_file, schema_file = MODEL_FILES[kind]
    schema = json.loads((ROOT_DIR / member_dirs[0] / schema_file).read_text(encoding="utf-8"))
    exports = [json.loads((ROOT_DIR / directory / model_file).read_text(encoding="utf-8")) for directory in member_dirs]
    return predict_heads_ensemble(
        frame, exports, schema["model_input_names"], list(HEADS), model_kind=kind,
        sequence_feature_schema=schema if kind == "sequence" else None, configured_window_size=window, batched=True,
    )


def score(frame: pd.DataFrame, predictions: dict[str, dict[str, np.ndarray]], config: dict) -> dict:
    rank_signal = config["phase_v2"]["rank_signal"]
    decision = blend_decision_score(predictions, rank_signal["heads"], list(rank_signal["model_priority"]))
    # The same heads with the other model served first: live's priority is sequence first, which hides every
    # multitask-only change (a variant that differs only in the multitask model scores identically); R-HEAD2 may flip it.
    swapped = blend_decision_score(predictions, rank_signal["heads"], list(reversed(rank_signal["model_priority"])))
    out: dict = {}
    for split in SPLITS:
        rows = (frame["split"] == split).to_numpy() & frame["in_main_group"].to_numpy() & frame["training_eligible"].astype(bool).to_numpy()
        part = frame.loc[rows]
        entry = {
            "decision_rank_20d": ic_stats(part, decision[rows], "target_rank_20d", 20),
            "decision_rank_20d_swapped_priority": ic_stats(part, swapped[rows], "target_rank_20d", 20),
        }
        for kind, heads in predictions.items():
            for head, (target, horizon) in HEADS.items():
                if target in part.columns:
                    entry[f"{kind}.{head}"] = ic_stats(part, heads[head][rows], target, horizon)
        out[split] = entry
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=str(ROOT_DIR / "ml" / "datasets" / "full_dataset.csv"))
    parser.add_argument("--candidate", action="append", required=True)
    parser.add_argument("--each-member", action="store_true")
    parser.add_argument("--out", default=str(ROOT_DIR / "ml" / "evaluation" / "v610" / "model_ic.json"))
    args = parser.parse_args()
    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    window = int(config.get("phase_v2", {}).get("sequence_model", {}).get("window_size", 30))
    parts = [chunk[chunk["date"].astype(str) >= CONTEXT_START] for chunk in pd.read_csv(args.dataset, chunksize=40_000)]
    frame = pd.concat(parts, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)
    classes = {a["ticker"]: a.get("asset_class") or a.get("security_type") for a in config["phase1"]["universe"]["assets"]}
    separate = {kind for kinds in (config["phase1"]["target"]["ranking"].get("separate_rank_groups") or {}).values() for kind in kinds}
    frame["in_main_group"] = ~frame["ticker"].map(classes).isin(separate)
    report: dict = {"dataset": args.dataset, "candidates": {}}
    for text in args.candidate:
        name, members = parse_candidate(text)
        predictions = {kind: predict_kind(frame, dirs, kind, window) for kind, dirs in members.items()}
        report["candidates"][name] = {"members": members, "ensemble": score(frame, predictions, config)}
        print(name, "validation decision IC:", json.dumps(report["candidates"][name]["ensemble"]["validation"]["decision_rank_20d"]), flush=True)
        if args.each_member:
            singles = {}
            for kind, dirs in members.items():
                for directory in dirs:
                    single = {kind: predict_kind(frame, [directory], kind, window)}
                    # a member is scored with the other kind's ensemble as the fallback, as live would serve it
                    for other, other_dirs in members.items():
                        if other != kind:
                            single[other] = predictions[other]
                    singles[directory] = score(frame, single, config)
            report["candidates"][name]["members_scored"] = singles
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1, default=float), encoding="utf-8")
    print(f"written {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
