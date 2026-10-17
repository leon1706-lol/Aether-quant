"""Live rolling-IC gate value against the offline gate's value on the same dates (V6.1.0, Problems.md #190, #196).

R-CAL2 found the gate's reading to be what keeps the simulator from matching Lean's rebalance decisions (the book mechanics
replay to r 0.74-0.83). Since V6.1.0 the book history records the live gate's reading (`rolling_ic`: rolling mean IC and the
resolved-date count) on every rebalance attempt. This scores the same dates with the offline gate (the as-live harness: dataset
scores, the lagged late-bar frame, the rolling-IC state function) and reports how the two agree: correlation of the values,
mean absolute difference, how often both sit on the same side of the floor, and where they differ most.

    python scripts/gate_value_compare.py --book-history visualization/book_history/<run>.jsonl [--dataset ml/datasets/full_dataset.csv]
        [--splits backtest holdout] [--warmup-days 400] [--out ml/evaluation/v610/gate_value_compare_bt1.json]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def live_gate_values(book_history: list[dict]) -> dict[str, dict]:
    """{date: {"value": float | None, "resolved": int, "veto_reason": str | None}} for each record carrying `rolling_ic`;
    a later record of the same date wins (a retry)."""
    out: dict[str, dict] = {}
    for record in book_history:
        entry = record.get("rolling_ic")
        if not isinstance(entry, dict):
            continue
        value = entry.get("rolling_mean_ic")
        out[str(record.get("date", ""))[:10]] = {
            "value": float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None,
            "resolved": int(entry.get("num_resolved_dates") or 0),
            "veto_reason": record.get("gate_veto_reason"),
        }
    return out


def compare_values(live: dict[str, dict], offline: dict[str, float | None], floor: float, min_resolved: int) -> dict:
    """Agreement of the two gate readings over the dates where both exist and live had enough resolved dates."""
    pairs = [
        (date, entry["value"], offline.get(date))
        for date, entry in sorted(live.items())
        if entry["value"] is not None and offline.get(date) is not None and entry["resolved"] >= min_resolved
    ]
    if len(pairs) < 3:
        return {"dates": len(pairs)}
    live_values = [value for _, value, _ in pairs]
    offline_values = [value for _, _, value in pairs]
    mean_live, mean_offline = sum(live_values) / len(pairs), sum(offline_values) / len(pairs)
    covariance = sum((a - mean_live) * (b - mean_offline) for a, b in zip(live_values, offline_values))
    spread = math.sqrt(sum((a - mean_live) ** 2 for a in live_values) * sum((b - mean_offline) ** 2 for b in offline_values))
    same_side = sum(1 for a, b in zip(live_values, offline_values) if (a >= floor) == (b >= floor))
    worst = sorted(pairs, key=lambda item: -abs(item[1] - item[2]))[:5]
    return {
        "dates": len(pairs),
        "correlation": covariance / spread if spread > 0 else None,
        "mean_live": mean_live,
        "mean_offline": mean_offline,
        "mean_abs_difference": sum(abs(a - b) for a, b in zip(live_values, offline_values)) / len(pairs),
        "same_side_of_floor_share": same_side / len(pairs),
        "floor": floor,
        "largest_differences": [{"date": d, "live": a, "offline": b} for d, a, b in worst],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--book-history", required=True)
    parser.add_argument("--dataset", default=str(ROOT_DIR / "ml" / "datasets" / "full_dataset.csv"))
    parser.add_argument("--splits", nargs="*", default=["backtest", "holdout"])
    parser.add_argument("--warmup-days", type=int, default=400)
    parser.add_argument("--out", default=str(ROOT_DIR / "ml" / "evaluation" / "v610" / "gate_value_compare.json"))
    args = parser.parse_args()

    from as_live_levers import AsLiveHarness

    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    history = [json.loads(line) for line in Path(args.book_history).read_text(encoding="utf-8").splitlines() if line.strip()]
    live = live_gate_values(history)
    harness = AsLiveHarness(tuple(args.splits), dataset_path=args.dataset, config=config, gate_warmup_days=args.warmup_days)
    frame = harness.lagged_frame
    harness.gate_for(frame)  # builds the rolling-IC state function for this frame
    gate = config["phase_v2"]["rolling_ic_gate"]
    state_fn = next(fn for key, fn in harness._states.items() if key[0] == id(frame))
    offline = {date: (state_fn(date) or {}).get("rolling_mean_ic") for date in live}
    report = compare_values(live, offline, float(gate.get("min_rolling_mean_ic", 0.0)), int(gate.get("min_resolved_dates_required", 20)))
    report.update(book_history=str(args.book_history), splits=list(args.splits), warmup_days=args.warmup_days)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1, default=float), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "largest_differences"}, indent=1, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
