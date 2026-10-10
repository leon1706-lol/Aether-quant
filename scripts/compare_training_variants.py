"""Compare retrain variants and pick the winner on VALIDATION IC, never on the backtest split.

Reads `ml/versions/<id>/multitask_training_metrics.json` (or sequence_...) for each version id and prints one table:
validation and backtest non-overlapping rank IC (mean, t) for the book heads, the backtest ranking-quality verdicts, the
net Sharpe of the head the book trades, and whether the variant beats the reference by more than the reference's own
seed-to-seed spread. The backtest columns are for the record; selecting on them would overfit the 2019-21 window that
Lean also tests.

    python scripts/compare_training_variants.py --reference v0_s1 --noise v0_s1 v0_s2 --variants v1 v2 v3
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

DEFAULT_HEADS = ("rank_5d", "rank_20d")


def _ic(metrics: dict, split: str, head: str) -> dict:
    block = (metrics.get(split) or {}).get(f"{head}_ic_non_overlapping") or {}
    return {"mean_ic": block.get("mean_ic"), "t_stat": block.get("t_stat"), "num_dates": block.get("num_dates")}


def summarize_variant(metrics: dict, heads: tuple[str, ...] = DEFAULT_HEADS) -> dict:
    """Validation/backtest IC per head, the mean validation IC across `heads` (the selection score), and the
    backtest verdicts. Heads without a finite validation IC are ignored; no usable head -> score None."""
    row: dict = {"heads": {}}
    scores = []
    for head in heads:
        validation = _ic(metrics, "validation", head)
        backtest = _ic(metrics, "backtest", head)
        quality = ((metrics.get("backtest") or {}).get(f"{head}_ranking_quality") or {}).get("quality_status")
        net = (((metrics.get("backtest") or {}).get(f"{head}_net_performance") or {}).get("observed") or {}).get("net_sharpe")
        row["heads"][head] = {"validation": validation, "backtest": backtest, "quality_status": quality, "net_sharpe": net}
        value = validation["mean_ic"]
        if isinstance(value, (int, float)) and math.isfinite(value):
            scores.append(float(value))
    row["validation_score"] = sum(scores) / len(scores) if scores else None
    row["seed"] = metrics.get("seed")
    return row


def seed_spread(scores: list[float]) -> float:
    """Max-min of the reference's validation scores across seeds (0.0 with fewer than two): the noise a
    variant has to clear before it counts as an improvement."""
    return (max(scores) - min(scores)) if len(scores) >= 2 else 0.0


def choose_winner(rows: dict[str, dict], reference: str, noise_ids: list[str]) -> dict:
    reference_row = rows.get(reference)
    reference_score = reference_row["validation_score"] if reference_row else None
    noise_scores = [rows[i]["validation_score"] for i in noise_ids if i in rows and rows[i]["validation_score"] is not None]
    spread = seed_spread(noise_scores)
    best_id, best_score = reference, reference_score
    for version_id, row in rows.items():
        score = row["validation_score"]
        if version_id == reference or score is None or reference_score is None:
            continue
        if score > reference_score + spread and (best_score is None or score > best_score):
            best_id, best_score = version_id, score
    return {
        "winner": best_id,
        "reference": reference,
        "reference_score": reference_score,
        "seed_spread": spread,
        "winner_score": best_score,
        "beats_reference": best_id != reference,
    }


def load_rows(ids: list[str], versions_dir: Path, metrics_filename: str) -> dict[str, dict]:
    rows = {}
    for version_id in ids:
        path = versions_dir / version_id / metrics_filename
        if not path.exists():
            continue
        rows[version_id] = summarize_variant(json.loads(path.read_text(encoding="utf-8")))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--versions-dir", default="ml/versions")
    parser.add_argument("--metrics-file", default="multitask_training_metrics.json")
    parser.add_argument("--reference", required=True, help="version id of the control (current config)")
    parser.add_argument("--noise", nargs="*", default=[], help="control re-runs with other seeds: they define the seed spread")
    parser.add_argument("--variants", nargs="*", default=[])
    parser.add_argument("--output", default="ml/evaluation/training_variant_comparison.json")
    args = parser.parse_args()

    ids = list(dict.fromkeys([args.reference, *args.noise, *args.variants]))
    rows = load_rows(ids, Path(args.versions_dir), args.metrics_file)
    verdict = choose_winner(rows, args.reference, args.noise or [args.reference])
    print(f"{'version':32s} {'val score':>9s}  " + "  ".join(f"{h}: val IC (t) | bt IC (t) | status" for h in DEFAULT_HEADS))
    for version_id, row in rows.items():
        cells = []
        for head in DEFAULT_HEADS:
            info = row["heads"][head]
            v, b = info["validation"], info["backtest"]
            fmt = lambda block: "n/a" if block["mean_ic"] is None else f"{block['mean_ic']:+.3f} ({block['t_stat']:.1f})"  # noqa: E731
            cells.append(f"{head}: {fmt(v)} | {fmt(b)} | {info['quality_status']}")
        score = "n/a" if row["validation_score"] is None else f"{row['validation_score']:+.4f}"
        print(f"{version_id:32s} {score:>9s}  " + "  ".join(cells))
    print(json.dumps(verdict, indent=2))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps({"rows": rows, "verdict": verdict}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
