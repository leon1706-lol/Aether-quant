"""R-BOOK (V6.0.0, todo lead 1): can any single change to the main equity book beat its costs? Pre-registered rule.

The V5.8.0 stack shows a pooled rank IC of +0.05 that does not pay a top-6 / bottom-6 book's costs (BT2: main-book members
+$1,184 net of fees over 3.25 years, legacy -$834). This runs each candidate change ALONE against the current config on the
Lean-calibrated simulator (`scripts/lean_calibration.py`'s calibrated rung: next-open fills, the broker's per-order floor,
live's resize / cooldown / trailing stop, the learned-topology sizing), on the validation and backtest splits:

    B0  current config                          B6  sector-neutral rank head (watchlist heads only to adopt)
    B1  rebalance 20 bars, max hold 40          B7  residual rank head
    B2a hysteresis margin 0.10                  B8a/b  4/4 and 10/10 names
    B2b hysteresis margin 0.15                  B9  60-day rank head (`v8_rank60`, candidate version dirs)
    B3  rank_20d only (no rank_5d)
    B4  class slots {equity 5/5, crypto 1/1}
    B5  class slots {equity 6/6} (crypto leaves the main book)

Decision (R-CAL branch from `ml/evaluation/v600/calibration.json`): a variant is ADOPTED iff, against B0 on the same rows,
  1. its UNGATED net Sharpe improves by >= +0.10 on the backtest split and is not worse by more than 0.02 on validation,
  2. its ungated net Sharpe is > 0 on both splits,
  3. branch A only: the as-live (gated) book passes the margins of clause 1 as well,
  4. its max drawdown is not worse by more than 1.0 pp on either split,
and a head variant must be at least `watchlist` on its promotion gate (R-HEAD). Passing variants are combined greedily in
order of validation Sharpe, each addition tested against the running best. The holdout is reported, never used.

    python scripts/book_variant_research.py --dataset ml/datasets/full_dataset.csv [--branch B] [--only B1 B2a]
    -> ml/evaluation/v600/book_research.json
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

MIN_BACKTEST_GAIN = 0.10
MAX_VALIDATION_LOSS = 0.02
MAX_DRAWDOWN_WORSENING = 0.01

# id -> {"config": {phase_v2 dotted key: value}, "heads": {head: weight} | None, "ml_dir": version dir | None, "dataset": str | None}
VARIANTS: dict[str, dict] = {
    "B0": {},
    "B1": {"config": {"portfolio_book.rebalance_every_bars": 20, "exits.max_holding_bars": 40}},
    "B2a": {"config": {"portfolio_book.hysteresis_rank_margin": 0.10}},
    "B2b": {"config": {"portfolio_book.hysteresis_rank_margin": 0.15}},
    "B3": {"heads": {"rank_20d": 1.0}},
    "B4": {"config": {"portfolio_book.per_asset_class_slots": {"equity": [5, 5], "crypto": [1, 1]}}},
    "B5": {"config": {"portfolio_book.per_asset_class_slots": {"equity": [6, 6]}}},
    "B6": {"heads": {"sector_neutral_rank_20d": 1.0}},
    "B7": {"heads": {"residual_rank_20d": 1.0}},
    "B8a": {"config": {"portfolio_book.top_n": 4, "portfolio_book.bottom_n": 4}},
    "B8b": {"config": {"portfolio_book.top_n": 10, "portfolio_book.bottom_n": 10}},
    "B9": {"heads": {"rank_60d": 1.0}, "config": {"portfolio_book.rebalance_every_bars": 20},
           "ml_dir": "ml/versions/v600cs20261015_mt_v8_rank60_s1", "dataset": "ml/datasets/v600_rank60_dataset.csv"},
}


def passes_margins(base: dict, variant: dict) -> dict:
    """R-BOOK clauses 1, 2 and 4 on one scoring mode. `base` / `variant` = {split: {"net_sharpe", "net_max_drawdown"}}."""
    gain_backtest = variant["backtest"]["net_sharpe"] - base["backtest"]["net_sharpe"]
    change_validation = variant["validation"]["net_sharpe"] - base["validation"]["net_sharpe"]
    drawdown_ok = all(
        variant[split]["net_max_drawdown"] - base[split]["net_max_drawdown"] >= -MAX_DRAWDOWN_WORSENING for split in ("validation", "backtest")
    )
    checks = {
        "backtest_gain_ge_0.10": gain_backtest >= MIN_BACKTEST_GAIN,
        "validation_not_worse_than_0.02": change_validation >= -MAX_VALIDATION_LOSS,
        "positive_on_both_splits": variant["validation"]["net_sharpe"] > 0.0 and variant["backtest"]["net_sharpe"] > 0.0,
        "drawdown_within_1pp": drawdown_ok,
    }
    return {"checks": checks, "backtest_gain": gain_backtest, "validation_change": change_validation, "passes": all(checks.values())}


def decide(base: dict, variant: dict, branch: str, *, head_status_ok: bool = True) -> dict:
    """base / variant = {"ungated": {...}, "as_live": {...}}. Branch A also requires the as-live margins (clause 3); the
    positivity clause is judged on the ungated book only."""
    ungated = passes_margins(base["ungated"], variant["ungated"])
    verdict = {"ungated": ungated, "head_status_ok": head_status_ok}
    adopted = ungated["passes"] and head_status_ok
    if branch == "A":
        as_live = passes_margins(base["as_live"], variant["as_live"])
        as_live["checks"].pop("positive_on_both_splits", None)
        as_live["passes"] = all(as_live["checks"].values())
        verdict["as_live"] = as_live
        adopted = adopted and as_live["passes"]
    verdict["adopted"] = bool(adopted)
    return verdict


def merge_variants(chosen: list[str]) -> dict:
    """The combined spec of several variants; None when two of them set the same key or the head blend (no silent winner)."""
    merged: dict = {"config": {}, "heads": None, "ml_dir": None, "dataset": None}
    for name in chosen:
        spec = VARIANTS[name]
        for key, value in (spec.get("config") or {}).items():
            if key in merged["config"] and merged["config"][key] != value:
                return {}
            merged["config"][key] = value
        for field in ("heads", "ml_dir", "dataset"):
            if spec.get(field):
                if merged[field] and merged[field] != spec[field]:
                    return {}
                merged[field] = spec[field]
    return merged


def greedy_combination(passing: list[str], validation_sharpe: dict[str, float], evaluate, base: dict, branch: str,
                       head_ok) -> tuple[list[str], list[dict]]:
    """Add passing variants in order of ungated validation Sharpe; each must pass against the running best."""
    chosen: list[str] = []
    running = base
    log = []
    for name in sorted(passing, key=lambda item: -validation_sharpe[item]):
        spec = merge_variants(chosen + [name])
        if not spec:
            log.append({"variant": name, "skipped": "conflicts with an adopted variant"})
            continue
        result = evaluate(spec)
        verdict = decide(running, result, branch, head_status_ok=head_ok(spec))
        log.append({"variant": name, "combined": chosen + [name], "verdict": verdict})
        if verdict["adopted"]:
            chosen.append(name)
            running = result
    return chosen, log


# The owner kept the four rank heads of the installed multitask / sequence models as watchlist on 2026-10-13 (R-MODEL8, Problems
# #162) although the single-split gate calls them not_promotable; a variant that only re-weights them inherits that decision.
OWNER_WATCHLIST_HEADS = frozenset({"rank_5d", "rank_20d", "residual_rank_5d", "residual_rank_20d"})


def head_status_ok(spec: dict, config: dict, version_metrics: dict | None) -> bool:
    """R-HEAD for a head variant: every head it blends must be `watchlist` or better on its backtest promotion gate (the
    owner's watchlist decision covers the installed model's rank heads, never a new candidate's)."""
    heads = (spec or {}).get("heads")
    if not heads:
        return True
    allowed = set(config["phase_v2"]["rank_signal"].get("min_promotion_status", ["promotable", "watchlist"]))
    metrics = version_metrics or {}
    for head in heads:
        if not spec.get("ml_dir") and head in OWNER_WATCHLIST_HEADS:
            continue
        quality = (metrics.get("backtest", {}) or {}).get(f"{head}_ranking_quality") or {}
        if quality.get("quality_status") not in allowed:
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=str(ROOT_DIR / "ml" / "datasets" / "full_dataset.csv"))
    parser.add_argument("--branch", choices=("A", "B"), default=None, help="default: read ml/evaluation/v600/calibration.json")
    parser.add_argument("--only", nargs="*", default=None, help="variant ids (B0 always runs)")
    parser.add_argument("--out", default=str(ROOT_DIR / "ml" / "evaluation" / "v600" / "book_research.json"))
    args = parser.parse_args()

    from as_live_levers import AsLiveHarness, summarize
    from lean_calibration import calibrated_overrides, topology_inputs_fn_for, use_topology

    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    branch = args.branch
    if branch is None:
        branch = json.loads((ROOT_DIR / "ml" / "evaluation" / "v600" / "calibration.json").read_text(encoding="utf-8"))["verdict"]["branch"]
    cache: dict = {}
    current_group: list = [None]

    def harness_for(spec: dict, split: str):
        dataset = spec.get("dataset") or args.dataset
        group = (json.dumps(spec.get("heads"), sort_keys=True), spec.get("ml_dir"), dataset)
        if current_group[0] != group:  # one scoring group resident at a time (each frame is 100-200 MB)
            cache.clear()
            current_group[0] = group
        key = (split, *group)
        if key not in cache:
            cfg = copy.deepcopy(config)
            if spec.get("heads"):
                cfg["phase_v2"]["rank_signal"]["heads"] = dict(spec["heads"])
                cfg["phase_v2"]["rank_signal"]["demote_not_promotable_heads"] = False  # R-HEAD is judged separately
            ml_dir = ROOT_DIR / spec["ml_dir"] if spec.get("ml_dir") else None
            harness = AsLiveHarness(split, dataset_path=ROOT_DIR / dataset, config=cfg, ml_dir=ml_dir)
            cache[key] = (harness, topology_inputs_fn_for(harness, cfg))
        return cache[key]

    def run(spec: dict, split: str, *, gated: bool) -> dict:
        harness, topology_fn = harness_for(spec, split)
        use_topology(harness, topology_fn)
        kwargs = calibrated_overrides(harness)
        if not gated:
            kwargs.update(gate="off", min_rank_confidence_spread=0.0)
        result = harness.as_live(config_overrides={f"{k}": v for k, v in (spec.get("config") or {}).items()} or None, **kwargs)
        return summarize(result)

    def evaluate(spec: dict, which=("validation", "backtest")) -> dict:
        return {mode: {split: run(spec, split, gated=(mode == "as_live")) for split in which} for mode in ("ungated", "as_live")}

    selected = [name for name in VARIANTS if name != "B0" and (not args.only or name in args.only)]
    # config-only variants share B0's scoring, so they run first; each head variant then loads its own scores
    chosen_ids = ["B0"] + sorted(selected, key=lambda name: bool(VARIANTS[name].get("heads") or VARIANTS[name].get("dataset")))
    results: dict[str, dict] = {}
    for name in chosen_ids:
        spec = VARIANTS[name]
        results[name] = evaluate(spec)
        print(f"{name:4s} ungated v/b {results[name]['ungated']['validation']['net_sharpe']:+.3f}/{results[name]['ungated']['backtest']['net_sharpe']:+.3f}"
              f"  as-live v/b {results[name]['as_live']['validation']['net_sharpe']:+.3f}/{results[name]['as_live']['backtest']['net_sharpe']:+.3f}", flush=True)

    version_metrics = {}
    for name in chosen_ids:
        ml_dir = VARIANTS[name].get("ml_dir")
        metrics_path = ROOT_DIR / (ml_dir or "ml") / "multitask_training_metrics.json"
        version_metrics[name] = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else None

    verdicts = {}
    for name in chosen_ids[1:]:
        base = results["B0"]
        if VARIANTS[name].get("dataset"):  # a different row set (60-day purge): compare with B0 on the SAME rows
            base = evaluate({"dataset": VARIANTS[name]["dataset"]})
            results[f"B0@{name}"] = base
        verdicts[name] = decide(base, results[name], branch, head_status_ok=head_status_ok(VARIANTS[name], config, version_metrics[name]))
        print(f"{name:4s} adopted={verdicts[name]['adopted']}  ungated gain {verdicts[name]['ungated']['backtest_gain']:+.3f} "
              f"validation {verdicts[name]['ungated']['validation_change']:+.3f}  checks {verdicts[name]['ungated']['checks']}", flush=True)

    passing = [name for name, verdict in verdicts.items() if verdict["adopted"] and not VARIANTS[name].get("dataset")]
    validation_sharpe = {name: results[name]["ungated"]["validation"]["net_sharpe"] for name in passing}
    chosen, combination_log = greedy_combination(
        passing, validation_sharpe, evaluate, results["B0"], branch,
        head_ok=lambda spec: head_status_ok(spec, config, version_metrics.get("B0")),
    )
    final = {"adopted": chosen, "spec": merge_variants(chosen) if chosen else {}}
    if chosen:
        final["holdout_seen"] = {
            "b0": {mode: run({}, "holdout", gated=(mode == "as_live")) for mode in ("ungated", "as_live")},
            "final": {mode: run(final["spec"], "holdout", gated=(mode == "as_live")) for mode in ("ungated", "as_live")},
        }
    else:
        final["holdout_seen"] = {"b0": {mode: run({}, "holdout", gated=(mode == "as_live")) for mode in ("ungated", "as_live")}}
    print("R-BOOK adopted:", chosen or "none (no variant beats costs)")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps({"branch": branch, "results": results, "verdicts": verdicts, "combination": combination_log, "final": final}, indent=1, default=float),
        encoding="utf-8",
    )
    print(f"written {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
