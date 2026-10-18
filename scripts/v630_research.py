"""V6.3.0 research chain (pre-registered rules R-KILL -> R-STAGGER2 -> R-GATE3; plan V6.3.0). Written before any score.

Scoring is V6.2.0's (scripts/v620_research.py): the modelled portfolio (main book + legacy signal) on the calibrated
simulator, every rebalance phase (10 at cadence 20) of both splits, the T-bill sweep off (alpha judged ex-carry),
`rule_verdict` margins (backtest median gain >= +0.10, validation not worse than -0.02, >= 60% of phases beat the base
median on both splits, positive median on both splits, median drawdown within 1 pp). Each stage scores on top of what
the earlier stages adopted. The holdout is never read.

    gate    R-CAL3 (scripts/lean_calibration.py, R-CAL2's unchanged clauses against V6.2.0's BT2: daily correlation >= 0.50,
            |annual gap| <= 2 pp, decision agreement >= 80% on every window), passed in as --calibration. Branch A allows
            stage 3; branch B keeps the gates frozen as safety controls (V6.0-V6.2).
    kill    R-KILL (todo lead 3, Problems #200 / #205: the kill switch at its -1.0 floor flips its lock path on cents).
            Scored UNGATED (the gates are frozen under branch B; the kill switch is the mechanism under change and stays on).
              KS1  risk.kill_switch.evaluation_bars 120
              KS2  risk.kill_switch.release_rolling_sharpe -0.5 (a trip holds until the rolling Sharpe recovers above -0.5)
              KS3  KS1 + KS2
            Clauses, per variant:
              (a) stability: the kill switch's input perturbed by N(0, 0.5 bp) noise (seeds 1-3) on 5 backtest phases; the
                  median Jaccard overlap of locked dates against the unperturbed run is >= 0.80 and >= KS0's;
              (b) safety: the median number of locked dates is >= 50% of KS0's on both splits;
              (c) performance: `rule_verdict` against KS0.
            Branch A: variants passing (a)+(b)+(c); the highest backtest median ships.
            Branch B: none passes (c); variants passing (a)+(b) that are non-inferior (median Sharpe change >= -0.02 on both
                      splits); the most stable (highest median Jaccard) ships - the defect is path fragility, not return.
            Branch C: nothing qualifies; KS0 stays and #200 closes as a documented design limit.
    stagger R-STAGGER2 (todo lead 1): the SECOND look at S2 (2 tranches; S4 failed R-STAGGER), ungated. It counts in the
            deflated Sharpe's trial registry. Clauses: `rule_verdict`, the median annual cost drag rises <= 30%, and two
            measures that do not reward one lucky phase in place of R-STAGGER's max-min range: the validation interquartile
            range of phase Sharpe widens by <= 25%, and the worst phase is not worse than the base's by more than 0.10 on
            both splits. Adopted iff all pass.
    gates   R-GATE3 (only on R-CAL3 branch A), as-live: G1 rolling_ic_gate.min_rolling_mean_ic -0.01, G2 -0.02,
            G3 rolling_ic_gate.rolling_window_days 60, G4 240. Clauses: `rule_verdict` on the as-live scores; the passing
            variant with the highest backtest median ships.

    python scripts/v630_research.py --dataset ml/datasets/v610_full_dataset.csv --legacy-probability ml/datasets/legacy_probability.csv
        [--calibration ml/evaluation/v630/calibration.json] [--stages kill stagger gates] [--max-phases 10] [--workers 2]
        [--out ml/evaluation/v630/research.json] [--adopted-config-out ml/evaluation/v630/adopted_changes.json]
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import statistics
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from v610_research import SPLITS, apply_dotted, phase_summary, phases_for, rule_verdict  # noqa: E402

KILL_VARIANTS = {
    "KS1": {"risk.kill_switch.evaluation_bars": 120},
    "KS2": {"risk.kill_switch.release_rolling_sharpe": -0.5},
    "KS3": {"risk.kill_switch.evaluation_bars": 120, "risk.kill_switch.release_rolling_sharpe": -0.5},
}
GATE_VARIANTS = {
    "G1": {"rolling_ic_gate.min_rolling_mean_ic": -0.01},
    "G2": {"rolling_ic_gate.min_rolling_mean_ic": -0.02},
    "G3": {"rolling_ic_gate.rolling_window_days": 60},
    "G4": {"rolling_ic_gate.rolling_window_days": 240},
}
STAGGER_TRANCHES = 2
NOISE_STD = 0.5e-4
NOISE_SEEDS = (1, 2, 3)
STABILITY_PHASES = 5
MIN_JACCARD = 0.80
MIN_LOCK_SHARE = 0.50
NON_INFERIOR = -0.02
MAX_IQR_WIDENING = 0.25
MAX_WORST_PHASE_LOSS = 0.10
MAX_COST_RISE = 0.30


# ---------------------------------------------------------------- pure clause functions


def jaccard(first, second) -> float:
    """Overlap of two locked-date sets; two empty sets agree completely."""
    first, second = set(first), set(second)
    union = first | second
    return 1.0 if not union else len(first & second) / len(union)


def perturbation(dates, seed: int, base: dict | None = None, std: float = NOISE_STD) -> dict:
    """{date: base extra return + N(0, std)}: noise on the kill switch's input only (the book's P&L is untouched)."""
    rng = random.Random(seed)
    base = base or {}
    return {str(date): float(base.get(str(date), 0.0)) + rng.gauss(0.0, std) for date in sorted(map(str, dates))}


def interquartile_range(values) -> float:
    q1, _median, q3 = statistics.quantiles(list(values), n=4, method="inclusive")
    return q3 - q1


def kill_checks(base: dict, variant: dict, base_stability: float, variant_stability: float) -> dict:
    """R-KILL clauses (a) and (b); `base` / `variant` = {split: phase_summary with `locked_dates_by_phase`}."""
    lock_share = {
        split: statistics.median(variant[split]["locked_dates_by_phase"])
        >= MIN_LOCK_SHARE * statistics.median(base[split]["locked_dates_by_phase"])
        for split in SPLITS
    }
    return {
        "stability_jaccard_ge_0.80": variant_stability >= MIN_JACCARD,
        "stability_not_below_ks0": variant_stability >= base_stability,
        "locks_ge_half_of_ks0_on_both_splits": all(lock_share.values()),
    }


def non_inferior(verdict: dict) -> bool:
    return verdict["backtest_gain"] >= NON_INFERIOR and verdict["validation_change"] >= NON_INFERIOR


def kill_branch(variants: dict) -> tuple[str, str | None]:
    """(branch, chosen variant) from {name: {"verdict", "extra_checks", "stability"}} (rule R-KILL)."""
    safe = {name: entry for name, entry in variants.items() if all(entry["extra_checks"].values())}
    passing = [name for name, entry in safe.items() if entry["verdict"]["passes"]]
    if passing:
        return "A", max(passing, key=lambda name: variants[name]["scores"]["backtest"]["median_net_sharpe"])
    stable = [name for name, entry in safe.items() if non_inferior(entry["verdict"])]
    if stable:
        return "B", max(stable, key=lambda name: variants[name]["stability"])
    return "C", None


def stagger2_checks(base: dict, variant: dict) -> dict:
    """R-STAGGER2's clauses beyond `rule_verdict` (ungated scores)."""
    base_cost = statistics.median(base["validation"]["cost_drag_by_phase"] + base["backtest"]["cost_drag_by_phase"])
    variant_cost = statistics.median(variant["validation"]["cost_drag_by_phase"] + variant["backtest"]["cost_drag_by_phase"])
    return {
        "cost_drag_rise_le_30pct": variant_cost <= (1.0 + MAX_COST_RISE) * max(base_cost, 1e-9),
        "validation_iqr_widening_le_25pct": interquartile_range(variant["validation"]["net_sharpe_by_phase"])
        <= (1.0 + MAX_IQR_WIDENING) * interquartile_range(base["validation"]["net_sharpe_by_phase"]),
        "worst_phase_within_0.10_on_both_splits": all(
            min(variant[split]["net_sharpe_by_phase"]) >= min(base[split]["net_sharpe_by_phase"]) - MAX_WORST_PHASE_LOSS
            for split in SPLITS
        ),
    }


# ---------------------------------------------------------------- scoring


_JOB: dict = {}


def _phase_worker(task: tuple[int, int | None]) -> dict:
    from as_live_levers import summarize
    from lean_calibration import ANALYZER_INCLUDE, calibrated_overrides

    phase, seed = task
    job = _JOB
    harness = job["harness"]
    kwargs = dict(calibrated_overrides(harness, phase=phase), **job["mechanisms"], include=ANALYZER_INCLUDE)
    if job["mode"] == "ungated":
        kwargs.update(gate="off", min_rank_confidence_spread=0.0)
    if seed is not None:
        kwargs["kill_switch_extra_returns"] = perturbation(job["dates"], seed, kwargs.get("kill_switch_extra_returns"))
    result = harness.as_live(config_overrides=job["resolved"] or None, tranches=job.get("tranches", 1), **kwargs)
    summary = summarize(result)
    components = result.per_date_component_returns or {}
    summary["legacy_net_return"] = sum(components.get("legacy", {}).values())
    summary["locked_dates"] = list(result.kill_switch_locked_date_list or [])
    return summary


def map_tasks(tasks: list, workers: int) -> list[dict]:
    import multiprocessing

    if workers > 1 and len(tasks) > 1 and sys.platform.startswith("linux"):
        with multiprocessing.get_context("fork").Pool(min(workers, len(tasks))) as pool:
            return pool.map(_phase_worker, tasks)
    return [_phase_worker(task) for task in tasks]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=str(ROOT_DIR / "ml" / "datasets" / "full_dataset.csv"))
    parser.add_argument("--legacy-probability", required=True)
    parser.add_argument("--calibration", default=str(ROOT_DIR / "ml" / "evaluation" / "v630" / "calibration.json"))
    parser.add_argument("--stages", nargs="*", default=["kill", "stagger", "gates"])
    parser.add_argument("--max-phases", type=int, default=10)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--gate-warmup-days", type=int, default=400)
    parser.add_argument("--out", default=str(ROOT_DIR / "ml" / "evaluation" / "v630" / "research.json"))
    parser.add_argument("--adopted-config-out", default=str(ROOT_DIR / "ml" / "evaluation" / "v630" / "adopted_changes.json"))
    args = parser.parse_args()

    from as_live_levers import AsLiveHarness
    from lean_calibration import topology_inputs_fn_for, use_topology

    base_config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    out_path = Path(args.out)
    report = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    calibration_path = Path(args.calibration)
    calibration = json.loads(calibration_path.read_text(encoding="utf-8")) if calibration_path.exists() else {}
    branch = (calibration.get("verdict") or {}).get("branch", "B")
    report.update({"calibration_branch": branch, "max_phases": args.max_phases, "sweep_in_rule_scores": False})
    adopted = report.setdefault("adopted", {"config": {}, "tranches": 1})
    harnesses: dict = {}

    def harness_for(split: str):
        if split not in harnesses:
            harness = AsLiveHarness(split, dataset_path=args.dataset, config=copy.deepcopy(base_config),
                                    legacy_probability_path=args.legacy_probability, gate_warmup_days=args.gate_warmup_days)
            harnesses[split] = (harness, topology_inputs_fn_for(harness, base_config))
        return harnesses[split]

    def score(changes: dict, *, tranches: int = 1, mode: str = "ungated", stability: bool = False) -> dict:
        out: dict = {}
        for split in SPLITS:
            harness, topology_fn = harness_for(split)
            merged = apply_dotted(base_config, changes)
            use_topology(harness, topology_fn)
            cadence = int(merged["phase_v2"]["portfolio_book"].get("rebalance_every_bars", 20))
            phases = phases_for(cadence, args.max_phases)
            _JOB.update(harness=harness, mechanisms=harness.v610_mechanisms(merged), resolved=dict(changes), mode=mode,
                        tranches=tranches, dates=sorted(map(str, harness.frame["date"].unique())))
            per_phase = map_tasks([(phase, None) for phase in phases], args.workers)
            summary = phase_summary(per_phase)
            summary["cost_drag_by_phase"] = [row["cost_drag_annual_bps"] for row in per_phase]
            summary["locked_dates_by_phase"] = [len(row["locked_dates"]) for row in per_phase]
            if stability and split == "backtest":
                picked = phases[:: max(1, len(phases) // STABILITY_PHASES)][:STABILITY_PHASES]
                locked = {phase: row["locked_dates"] for phase, row in zip(phases, per_phase)}
                tasks = [(phase, seed) for phase in picked for seed in NOISE_SEEDS]
                perturbed = map_tasks(tasks, args.workers)
                overlaps = [jaccard(locked[phase], row["locked_dates"]) for (phase, _seed), row in zip(tasks, perturbed)]
                summary["stability_jaccard_median"] = statistics.median(overlaps)
                summary["stability_jaccards"] = overlaps
            out[split] = summary
        return out

    def save():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=1, default=float), encoding="utf-8")

    if "kill" in args.stages:
        print("=== stage kill (R-KILL, ungated)", flush=True)
        base = score(adopted["config"], stability=True)
        base_stability = base["backtest"]["stability_jaccard_median"]
        stage = {"base": base, "variants": {}}
        for name, changes in KILL_VARIANTS.items():
            result = score({**adopted["config"], **changes}, stability=True)
            verdict = rule_verdict(base, result)
            stability = result["backtest"]["stability_jaccard_median"]
            extra = kill_checks(base, result, base_stability, stability)
            stage["variants"][name] = {"changes": changes, "scores": result, "verdict": verdict, "extra_checks": extra,
                                       "stability": stability}
            print(f"  {name}: passes={verdict['passes']} gain {verdict['backtest_gain']:+.3f} val {verdict['validation_change']:+.3f} "
                  f"stability {stability:.3f} (KS0 {base_stability:.3f}) extra {extra}", flush=True)
            save()
        stage["branch"], stage["adopted"] = kill_branch(stage["variants"])
        if stage["adopted"]:
            adopted["config"].update(KILL_VARIANTS[stage["adopted"]])
        report["kill"] = stage
        print(f"  R-KILL branch {stage['branch']}, adopted {stage['adopted']}", flush=True)
        save()

    if "stagger" in args.stages:
        print("=== stage stagger (R-STAGGER2, ungated)", flush=True)
        base = score(adopted["config"])
        result = score(adopted["config"], tranches=STAGGER_TRANCHES)
        verdict = rule_verdict(base, result)
        extra = stagger2_checks(base, result)
        chosen = verdict["passes"] and all(extra.values())
        report["stagger"] = {"base": base, "variant": result, "verdict": verdict, "extra_checks": extra, "adopted": chosen}
        if chosen:
            adopted["tranches"] = STAGGER_TRANCHES
        print(f"  S2: adopted={chosen} gain {verdict['backtest_gain']:+.3f} val {verdict['validation_change']:+.3f} extra {extra}", flush=True)
        save()

    if "gates" in args.stages:
        if branch != "A":
            report["gates"] = {"skipped": f"R-CAL3 branch {branch}: the gates stay frozen as safety controls"}
            print(f"=== stage gates skipped (R-CAL3 branch {branch})", flush=True)
        else:
            print("=== stage gates (R-GATE3, as-live)", flush=True)
            base = score(adopted["config"], tranches=adopted["tranches"], mode="as_live")
            stage = {"base": base, "variants": {}}
            for name, changes in GATE_VARIANTS.items():
                result = score({**adopted["config"], **changes}, tranches=adopted["tranches"], mode="as_live")
                verdict = rule_verdict(base, result)
                stage["variants"][name] = {"changes": changes, "scores": result, "verdict": verdict}
                print(f"  {name}: passes={verdict['passes']} gain {verdict['backtest_gain']:+.3f}", flush=True)
                save()
            winners = [name for name, entry in stage["variants"].items() if entry["verdict"]["passes"]]
            stage["adopted"] = max(winners, key=lambda n: stage["variants"][n]["scores"]["backtest"]["median_net_sharpe"]) if winners else None
            if stage["adopted"]:
                adopted["config"].update(GATE_VARIANTS[stage["adopted"]])
            report["gates"] = stage
        save()

    Path(args.adopted_config_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.adopted_config_out).write_text(json.dumps(adopted, indent=1), encoding="utf-8")
    print("adopted:", json.dumps(adopted))
    print(f"written {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
