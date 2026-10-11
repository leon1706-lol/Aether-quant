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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.rank_ic_core import newey_west_t_stat  # noqa: E402

DEFAULT_HEADS = ("rank_5d", "rank_20d")
HORIZON_DAYS = {"rank_5d": 5, "rank_20d": 20}


def _ic(metrics: dict, split: str, head: str) -> dict:
    """Non-overlapping IC (honest t, few dates) plus the FULL daily IC series' mean and Newey-West t: the daily mean
    has the same expectation with far less noise (261 dates against 14 on validation) and the HAC t corrects the
    autocorrelation the plain daily t ignores."""
    block = (metrics.get(split) or {}).get(f"{head}_ic_non_overlapping") or {}
    daily = (metrics.get(split) or {}).get(f"{head}_ic") or {}
    values = daily.get("ic_values") or []
    return {
        "mean_ic": block.get("mean_ic"), "t_stat": block.get("t_stat"), "num_dates": block.get("num_dates"),
        "daily_mean_ic": daily.get("mean_ic"), "daily_num_dates": daily.get("num_dates"),
        "hac_t_stat": newey_west_t_stat(values, HORIZON_DAYS.get(head, 20) - 1) if values else None,
    }


def summarize_variant(metrics: dict, heads: tuple[str, ...] = DEFAULT_HEADS, score_basis: str = "daily") -> dict:
    """Validation/backtest IC per head, the mean validation IC across `heads` (the selection score: the full-daily mean
    by default, `score_basis="non_overlapping"` reproduces the V5.6.0 14-date score) and the backtest verdicts. Heads
    without a finite validation IC are ignored; no usable head -> score None."""
    row: dict = {"heads": {}}
    scores = []
    for head in heads:
        validation = _ic(metrics, "validation", head)
        backtest = _ic(metrics, "backtest", head)
        quality = ((metrics.get("backtest") or {}).get(f"{head}_ranking_quality") or {}).get("quality_status")
        net = (((metrics.get("backtest") or {}).get(f"{head}_net_performance") or {}).get("observed") or {}).get("net_sharpe")
        row["heads"][head] = {"validation": validation, "backtest": backtest, "quality_status": quality, "net_sharpe": net}
        value = validation["daily_mean_ic"] if score_basis == "daily" and validation["daily_mean_ic"] is not None else validation["mean_ic"]
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


def group_rows(rows: dict[str, dict], groups: dict[str, list[str]]) -> dict[str, dict]:
    """One row per group (a variant trained with several seeds): `validation_score` is the mean over the members that
    have a score, `member_scores` keeps each seed's own. Groups with no scored member get score None."""
    grouped = {}
    for name, ids in groups.items():
        members = {i: rows[i]["validation_score"] for i in ids if i in rows and rows[i]["validation_score"] is not None}
        grouped[name] = {
            "validation_score": sum(members.values()) / len(members) if members else None,
            "member_scores": members,
            "heads": rows[next(iter(members))]["heads"] if members else {},
        }
    return grouped


def choose_group_winner(grouped: dict[str, dict], reference: str) -> dict:
    """R-MODEL (selection half): a variant group wins only if its MEAN validation score beats the control group's mean by
    more than the control's own single-seed spread (max-min over its seeds) - noise the variant has to clear."""
    reference_row = grouped.get(reference) or {}
    spread = seed_spread(list((reference_row.get("member_scores") or {}).values()))
    reference_score = reference_row.get("validation_score")
    best_name, best_score = reference, reference_score
    for name, row in grouped.items():
        score = row["validation_score"]
        if name == reference or score is None or reference_score is None:
            continue
        if score > reference_score + spread and (best_score is None or score > best_score):
            best_name, best_score = name, score
    return {
        "winner": best_name, "reference": reference, "reference_score": reference_score, "seed_spread": spread,
        "winner_score": best_score, "beats_reference": best_name != reference,
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
    parser.add_argument(
        "--groups", nargs="*", default=[],
        help="V5.7.0 multi-seed mode: NAME=id1,id2,... per arm (the control arm is the one named by --reference). Each arm is "
        "scored by its mean validation IC (full daily series); a variant wins only above the control mean + the control's seed spread.",
    )
    parser.add_argument("--output", default="ml/evaluation/training_variant_comparison.json")
    args = parser.parse_args()

    if args.groups:
        groups = {name: ids.split(",") for name, ids in (item.split("=", 1) for item in args.groups)}
        all_ids = list(dict.fromkeys(i for ids in groups.values() for i in ids))
        rows = load_rows(all_ids, Path(args.versions_dir), args.metrics_file)
        grouped = group_rows(rows, groups)
        verdict = choose_group_winner(grouped, args.reference)
        for name, row in grouped.items():
            score = "n/a" if row["validation_score"] is None else f"{row['validation_score']:+.4f}"
            print(f"{name:24s} mean validation IC {score}  seeds {row['member_scores']}")
        print(json.dumps(verdict, indent=2))
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps({"rows": rows, "groups": grouped, "verdict": verdict}, indent=2), encoding="utf-8")
        return 0

    ids = list(dict.fromkeys([args.reference, *args.noise, *args.variants]))
    rows = load_rows(ids, Path(args.versions_dir), args.metrics_file)
    verdict = choose_winner(rows, args.reference, args.noise or [args.reference])
    print(f"{'version':32s} {'val score':>9s}  " + "  ".join(f"{h}: val daily IC (HAC t) | bt IC (t) | status" for h in DEFAULT_HEADS))
    for version_id, row in rows.items():
        cells = []
        for head in DEFAULT_HEADS:
            info = row["heads"][head]
            v, b = info["validation"], info["backtest"]
            fmt = lambda block: "n/a" if block["mean_ic"] is None else f"{block['mean_ic']:+.3f} ({block['t_stat']:.1f})"  # noqa: E731
            fmt_daily = lambda block: "n/a" if block["daily_mean_ic"] is None or block["hac_t_stat"] is None else f"{block['daily_mean_ic']:+.3f} ({block['hac_t_stat']:.1f})"  # noqa: E731
            cells.append(f"{head}: {fmt_daily(v)} | {fmt(b)} | {info['quality_status']}")
        score = "n/a" if row["validation_score"] is None else f"{row['validation_score']:+.4f}"
        print(f"{version_id:32s} {score:>9s}  " + "  ".join(cells))
    print(json.dumps(verdict, indent=2))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps({"rows": rows, "verdict": verdict}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
