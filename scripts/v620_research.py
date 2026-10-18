"""V6.2.0 research chain (pre-registered rules R-DEDUPE -> R-STAGGER -> R-MODEL10; plan V6.2.0).

The scoring is V6.1.0's (scripts/v610_research.py): the modelled portfolio (main book + legacy signal) on the calibrated
simulator, every rebalance phase, a statistic = the median across phases plus the share of phases beating the
comparator's median, margins from `rule_verdict` (backtest gain >= +0.10, validation not worse than -0.02, >= 60% of
phases on both splits, positive median on both splits, median drawdown within 1 pp). Alpha is judged ex-carry: the
T-bill sweep is off in every rule score and reported apart.

    dedupe   R-DEDUPE: `rolling_ic_gate.late_bar_event_count` "once" against "per_tick", scored GATED (as-live) because the
             gate is the mechanism under change; adopted iff `rule_verdict` passes on the as-live scores.
    stagger  R-STAGGER: S2 (2 tranches) and S4 (4 tranches) against 1, UNGATED (R-CAL2 branch B); adopted iff
             `rule_verdict` passes AND the validation phase range (max - min Sharpe) shrinks by >= 25% AND the median
             annual cost drag rises by <= 30%; the passing variant with the highest validation median wins.
    model    R-MODEL10: a 5-seed multitask (+3-seed sequence) ensemble candidate is installed iff
               1. validation decision IC - installed > the yardstick (2 x the std of resampled control ensembles,
                  floored at 0.02; model_candidate_research --bootstrap) and > 0,
               2. backtest IC >= installed - yardstick and backtest HAC t >= 2,
               3. the ungated all-phase book passes `rule_verdict` against the installed models,
               4. inference latency <= 1.5x the installed models', and the decision heads pass R-HEAD.

    python scripts/v620_research.py --dataset ml/datasets/v610_full_dataset.csv --legacy-probability ml/datasets/legacy_probability.csv
        [--candidates ml/evaluation/v620/candidates.json] [--model-ic ml/evaluation/v620/model_ic.json]
        [--stages dedupe stagger model] [--max-phases 10] [--workers 2] [--out ml/evaluation/v620/research.json]
"""

from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from v610_research import (  # noqa: E402
    MAX_LATENCY_RATIO,
    SPLITS,
    apply_dotted,
    best_decision_key,
    phase_summary,
    phases_for,
    rule_verdict,
)

DEDUPE_VARIANT = {"rolling_ic_gate.late_bar_event_count": "once"}
STAGGER_VARIANTS = {"S2": 2, "S4": 4}
MIN_PHASE_RANGE_CUT = 0.25
MAX_COST_RISE = 0.30


def model10_checks(model_ic: dict, name: str, installed: str = "installed") -> dict:
    """R-MODEL10 clauses 1-2 from model_candidate_research's output (`bootstrap` = the control ensembles' spread). Each
    side uses its own best decision key, as R-MODEL9; the yardstick is the one of the candidate's key."""
    candidates = model_ic["candidates"]
    candidate_key, installed_key = best_decision_key(candidates[name]), best_decision_key(candidates[installed])
    yardstick = float(((model_ic.get("bootstrap") or {}).get(candidate_key) or {}).get("yardstick", 0.02))
    decision = lambda entry, split, key: entry["ensemble"][split][key]  # noqa: E731
    cand_val = decision(candidates[name], "validation", candidate_key)["non_overlapping_mean_ic"] or 0.0
    inst_val = decision(candidates[installed], "validation", installed_key)["non_overlapping_mean_ic"] or 0.0
    cand_bt = decision(candidates[name], "backtest", candidate_key)
    inst_bt = decision(candidates[installed], "backtest", installed_key)
    return {
        "validation_beats_installed_by_yardstick": cand_val - inst_val > yardstick and cand_val > 0.0,
        "backtest_ic_not_below_installed_minus_yardstick": (cand_bt["daily_mean_ic"] or 0.0) >= (inst_bt["daily_mean_ic"] or 0.0) - yardstick,
        "backtest_hac_t_ge_2": (cand_bt["hac_t"] or 0.0) >= 2.0,
        "decision_priority": "swapped" if candidate_key.endswith("swapped_priority") else "live",
        "yardstick": yardstick,
    }


def stagger_checks(base: dict, variant: dict) -> dict:
    """R-STAGGER's clauses beyond `rule_verdict` (ungated scores): the phase luck it exists to remove, at bounded cost."""
    def spread(scores):
        return scores["validation"]["max_net_sharpe"] - scores["validation"]["min_net_sharpe"]

    base_cost = statistics.median(base["validation"]["cost_drag_by_phase"] + base["backtest"]["cost_drag_by_phase"])
    variant_cost = statistics.median(variant["validation"]["cost_drag_by_phase"] + variant["backtest"]["cost_drag_by_phase"])
    return {
        "validation_phase_range_cut_ge_25pct": spread(variant) <= (1.0 - MIN_PHASE_RANGE_CUT) * spread(base),
        "cost_drag_rise_le_30pct": variant_cost <= (1.0 + MAX_COST_RISE) * max(base_cost, 1e-9),
    }


_JOB: dict = {}


def _phase_worker(phase: int) -> dict:
    from as_live_levers import summarize
    from lean_calibration import ANALYZER_INCLUDE, calibrated_overrides

    job = _JOB
    harness = job["harness"]
    kwargs = dict(calibrated_overrides(harness, phase=phase), **job["mechanisms"], include=ANALYZER_INCLUDE)
    if job["mode"] == "ungated":
        kwargs.update(gate="off", min_rank_confidence_spread=0.0)
    result = harness.as_live(config_overrides=job["resolved"] or None, tranches=job.get("tranches", 1),
                             cash_sweep=job.get("cash_sweep", False), **kwargs)
    summary = summarize(result)
    components = result.per_date_component_returns or {}
    summary["legacy_net_return"] = sum(components.get("legacy", {}).values())
    summary["cash_sweep_return"] = sum(components.get("cash_sweep", {}).values())
    return summary


def map_phases(phases: list[int], workers: int) -> list[dict]:
    import multiprocessing

    if workers > 1 and len(phases) > 1 and sys.platform.startswith("linux"):
        with multiprocessing.get_context("fork").Pool(min(workers, len(phases))) as pool:
            return pool.map(_phase_worker, phases)
    return [_phase_worker(phase) for phase in phases]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=str(ROOT_DIR / "ml" / "datasets" / "full_dataset.csv"))
    parser.add_argument("--legacy-probability", required=True)
    parser.add_argument("--candidates", default=None)
    parser.add_argument("--model-ic", default=str(ROOT_DIR / "ml" / "evaluation" / "v620" / "model_ic.json"))
    parser.add_argument("--stages", nargs="*", default=["dedupe", "stagger", "model"])
    parser.add_argument("--max-phases", type=int, default=10)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--gate-warmup-days", type=int, default=400)
    parser.add_argument("--out", default=str(ROOT_DIR / "ml" / "evaluation" / "v620" / "research.json"))
    args = parser.parse_args()

    from as_live_levers import AsLiveHarness
    from lean_calibration import topology_inputs_fn_for, use_topology

    base_config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    out_path = Path(args.out)
    report = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    report.update({"branch": "B", "max_phases": args.max_phases, "sweep_in_rule_scores": False})
    adopted = report.setdefault("adopted", {"config": {}, "tranches": 1, "model": None, "rank_signal": None})
    candidates = json.loads(Path(args.candidates).read_text(encoding="utf-8")) if args.candidates else {}
    cache: dict = {}
    memo: dict = {}

    def harness_for(model: str | None, rank_signal: dict | None, split: str):
        spec = candidates.get(model, {}) if model else {}
        key = (model, json.dumps(rank_signal, sort_keys=True), split)
        if key not in cache:
            if len(cache) >= 2:
                cache.pop(next(iter(cache)))
            cfg = copy.deepcopy(base_config)
            if rank_signal:
                cfg["phase_v2"]["rank_signal"].update(rank_signal)
                cfg["phase_v2"]["rank_signal"]["demote_not_promotable_heads"] = False
            if spec.get("ensemble"):
                cfg["phase_v2"]["model_ensemble"]["enabled"] = True
            harness = AsLiveHarness(
                split, dataset_path=args.dataset, config=cfg,
                ml_dir=(ROOT_DIR / spec["ml_dir"]) if spec.get("ml_dir") else None,
                legacy_probability_path=spec.get("legacy_probability") or args.legacy_probability,
                gate_warmup_days=args.gate_warmup_days,
            )
            cache[key] = (harness, topology_inputs_fn_for(harness, cfg), cfg)
        return cache[key]

    def score(changes: dict, *, tranches: int = 1, model=None, rank_signal=None, splits=SPLITS, modes=("ungated",),
              cash_sweep: bool = False) -> dict:
        memo_key = json.dumps([changes, tranches, model, rank_signal, list(splits), list(modes), cash_sweep], sort_keys=True, default=str)
        if memo_key in memo:
            return memo[memo_key]
        out: dict = {mode: {} for mode in modes}
        for split in splits:
            harness, topology_fn, cfg = harness_for(model, rank_signal, split)
            merged = apply_dotted(cfg, changes)
            cadence = int(merged["phase_v2"]["portfolio_book"].get("rebalance_every_bars", 20))
            use_topology(harness, topology_fn)
            mechanisms = harness.v610_mechanisms(merged)
            for mode in modes:
                _JOB.update(harness=harness, mechanisms=mechanisms, resolved=dict(changes), mode=mode, tranches=tranches,
                            cash_sweep=cash_sweep)
                per_phase = map_phases(phases_for(cadence, args.max_phases), args.workers)
                summary = phase_summary(per_phase)
                summary["legacy_net_return_median"] = statistics.median(row["legacy_net_return"] for row in per_phase)
                summary["cost_drag_by_phase"] = [row["cost_drag_annual_bps"] for row in per_phase]
                summary["cash_sweep_return_median"] = statistics.median(row["cash_sweep_return"] for row in per_phase)
                out[mode][split] = summary
        memo[memo_key] = out
        return out

    def save():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=1, default=float), encoding="utf-8")

    current = lambda: adopted["config"]  # noqa: E731

    if "dedupe" in args.stages:
        print("=== stage dedupe (R-DEDUPE, as-live)", flush=True)
        base = score(current(), modes=("as_live",))
        variant = score({**current(), **DEDUPE_VARIANT}, modes=("as_live",))
        verdict = rule_verdict(base["as_live"], variant["as_live"])
        if verdict["passes"]:
            adopted["config"].update(DEDUPE_VARIANT)
        report["dedupe"] = {"base": base, "variant": variant, "verdict": verdict, "adopted": verdict["passes"]}
        print(f"  once: adopted={verdict['passes']} gain {verdict['backtest_gain']:+.3f} val {verdict['validation_change']:+.3f}", flush=True)
        save()

    if "stagger" in args.stages:
        print("=== stage stagger (R-STAGGER, ungated)", flush=True)
        base = score(current())
        stage = {"base": base, "variants": {}}
        for name, count in STAGGER_VARIANTS.items():
            result = score(current(), tranches=count)
            verdict = rule_verdict(base["ungated"], result["ungated"])
            extra = stagger_checks(base["ungated"], result["ungated"])
            verdict["extra_checks"] = extra
            verdict["adopted"] = verdict["passes"] and all(extra.values())
            stage["variants"][name] = {"tranches": count, "scores": result, "verdict": verdict}
            print(f"  {name}: adopted={verdict['adopted']} gain {verdict['backtest_gain']:+.3f} val {verdict['validation_change']:+.3f} "
                  f"extra {extra}", flush=True)
            save()
        winners = [name for name, entry in stage["variants"].items() if entry["verdict"]["adopted"]]
        chosen = max(winners, key=lambda n: stage["variants"][n]["scores"]["ungated"]["validation"]["median_net_sharpe"]) if winners else None
        adopted["tranches"] = STAGGER_VARIANTS[chosen] if chosen else 1
        stage["adopted"] = chosen
        report["stagger"] = stage
        save()

    if "model" in args.stages and candidates:
        print("=== stage model (R-MODEL10, ungated)", flush=True)
        model_ic = json.loads(Path(args.model_ic).read_text(encoding="utf-8"))
        stage = {"variants": {}}
        for name, spec in candidates.items():
            if name == "installed":
                continue
            ic = spec.get("ic_checks") or model10_checks(model_ic, name)
            if not spec.get("ic_pass"):
                stage["variants"][name] = {"skipped": "IC clauses failed", "ic_checks": ic}
                print(f"  {name}: skipped, IC clauses {ic}", flush=True)
                continue
            signal = {"model_priority": ["multitask", "sequence"]} if ic.get("decision_priority") == "swapped" else None
            base = score(current(), tranches=adopted["tranches"], rank_signal=signal)
            result = score(current(), tranches=adopted["tranches"], model=name, rank_signal=signal)
            verdict = rule_verdict(base["ungated"], result["ungated"])
            extra = {"decision_heads_pass_r_head": bool(spec.get("decision_heads_pass_r_head")),
                     "latency_within_1.5x": float(spec.get("latency_ratio", 1.0)) <= MAX_LATENCY_RATIO}
            verdict["extra_checks"] = extra
            verdict["adopted"] = verdict["passes"] and all(extra.values())
            stage["variants"][name] = {"ic_checks": ic, "scores": result, "base": base, "verdict": verdict, "rank_signal": signal}
            print(f"  {name}: adopted={verdict['adopted']} gain {verdict['backtest_gain']:+.3f}", flush=True)
            save()
        winners = [name for name, entry in stage["variants"].items() if (entry.get("verdict") or {}).get("adopted")]
        if winners:
            adopted["model"] = max(winners, key=lambda n: stage["variants"][n]["scores"]["ungated"]["validation"]["median_net_sharpe"])
            adopted["rank_signal"] = stage["variants"][adopted["model"]]["rank_signal"]
        stage["adopted"] = adopted["model"]
        report["model"] = stage
        save()

    # informational: the adopted configuration with and without the T-bill sweep (as-live), and the seen holdout
    report["sweep_report"] = {
        "without": score(current(), tranches=adopted["tranches"], model=adopted["model"], rank_signal=adopted["rank_signal"],
                         modes=("as_live",)),
        "with": score(current(), tranches=adopted["tranches"], model=adopted["model"], rank_signal=adopted["rank_signal"],
                      modes=("as_live",), cash_sweep=True) if adopted["tranches"] == 1 else None,
    }
    save()
    report["final_holdout_seen"] = score(current(), tranches=adopted["tranches"], model=adopted["model"],
                                         rank_signal=adopted["rank_signal"], splits=("holdout",), modes=("ungated", "as_live"))
    save()
    print("adopted:", json.dumps(adopted))
    print(f"written {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
