"""V6.1.0 research chain (pre-registered rules R-MODEL9 -> R-HEAD2 -> R-BOOK2 -> R-LEGACY -> R-GATE; plan V6.1.0).

Every score is the modelled portfolio (main book + the legacy signal) on the V6.1.0 simulator - the R-CAL2 `v610` rung of
`scripts/lean_calibration.py`: live's daily member pass, weekend accrual, the position cap, the live analyzer, the legacy
probability signal, next-open fills, the broker floor, the resize / cooldown / trailing-stop gates and the learned
topology sizing. Each variant runs on EVERY rebalance phase (`rebalance_counter_start` 0..N-1; live picks one, and one
Lean path cannot rank configs - Problems.md #186), and a statistic is the median across phases plus the share of phases
that beat the comparator's median. Branch B (R-CAL2 not calibrated) scores the UNGATED book only; branch A also scores
the as-live (gated) book. The holdout is reported for the final configuration, never used.

Stages (each applies the previous stages' adoptions first; one change per variant):
    model   R-MODEL9: candidates from --candidates (model IC from --model-ic, R-HEAD from the candidate's training metrics)
    head    R-HEAD2: H1 = the R-HEAD-passing heads weighted by validation IC, each head from its better model
    book    R-BOOK2: K1 10/20, K2 15/30, K3 30/60 against K0 = current 20/40; the cap report (gross 1.0 / 0.75 / 0.5)
            is informational
    costs   the net-edge gate's holding period: N1 = the book cadence, N2 = 40 bars (the age exit)
    legacy  R-LEGACY: L1 gross 0.10, L2 gross 0.15 + per name 0.03, L3 trade while the book is vetoed
    gate    R-GATE (branch A only): rolling-IC window / floor, spread floor, kill-switch floor

    python scripts/v610_research.py --dataset ml/datasets/full_dataset.csv --legacy-probability ml/datasets/legacy_probability.csv \\
        [--candidates ml/evaluation/v610/candidates.json] [--model-ic ml/evaluation/v610/model_ic.json] [--branch B]
        [--stages model head book costs legacy gate] [--max-phases 20] [--out ml/evaluation/v610/research.json]
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

MIN_GAIN = 0.10
MAX_VALIDATION_LOSS = 0.02
MAX_DRAWDOWN_WORSENING = 0.01
MIN_PHASE_SHARE = 0.60
MAX_LATENCY_RATIO = 1.5
SPLITS = ("validation", "backtest")

BOOK_VARIANTS = {
    "K1": {"portfolio_book.rebalance_every_bars": 10, "exits.max_holding_bars": 20},
    "K2": {"portfolio_book.rebalance_every_bars": 15, "exits.max_holding_bars": 30},
    "K3": {"portfolio_book.rebalance_every_bars": 30, "exits.max_holding_bars": 60},
}
# The net-edge gate prices the expected edge for `costs.holding_bars` (10) while the book holds up to 40 bars; it diverted
# 306 member decisions in V6 BT2. Independent of the cadence, so its own stage (after the book is settled).
COST_VARIANTS = {
    "N1": {"costs.holding_bars": "@cadence"},
    "N2": {"costs.holding_bars": 40},
}
LEGACY_VARIANTS = {
    "L1": {"legacy_sleeve.max_gross_exposure": 0.10},
    "L2": {"legacy_sleeve.max_gross_exposure": 0.15, "legacy_sleeve.max_weight_per_name": 0.03},
    "L3": {"legacy_sleeve.trade_when_book_vetoed": True},
}
GATE_VARIANTS = {
    "G1": {"rolling_ic_gate.min_rolling_mean_ic": -0.02},
    "G2": {"rolling_ic_gate.rolling_window_days": 60},
    "G3": {"rolling_ic_gate.enabled": False},
    "G4": {"portfolio_book.min_rank_confidence_spread": 0.05},
    "G5": {"risk.kill_switch.min_rolling_sharpe": -2.0},
}
CAP_REPORT = (1.0, 0.75, 0.5)


def apply_dotted(config: dict, changes: dict) -> dict:
    """A deep copy of `config` with `{dotted.phase_v2.key: value}` set; "@cadence" resolves to the book's cadence."""
    result = copy.deepcopy(config)
    cadence = int(result["phase_v2"]["portfolio_book"].get("rebalance_every_bars", 20))
    for dotted, value in (changes or {}).items():
        node = result["phase_v2"]
        *parents, leaf = dotted.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        if leaf == "rebalance_every_bars":
            cadence = int(value)
        node[leaf] = value
    for dotted, value in (changes or {}).items():
        if value == "@cadence":
            node = result["phase_v2"]
            *parents, leaf = dotted.split(".")
            for part in parents:
                node = node[part]
            node[leaf] = cadence
    return result


def phases_for(cadence: int, max_phases: int) -> list[int]:
    """Every rebalance phase, or `max_phases` evenly spaced ones when the cadence is longer."""
    if max_phases <= 0 or cadence <= max_phases:
        return list(range(cadence))
    step = cadence / max_phases
    return sorted({int(round(index * step)) % cadence for index in range(max_phases)})


def phase_summary(per_phase: list[dict]) -> dict:
    sharpes = [row["net_sharpe"] for row in per_phase]
    drawdowns = [row["net_max_drawdown"] for row in per_phase]
    returns = [row["net_total_return"] for row in per_phase]
    return {
        "median_net_sharpe": statistics.median(sharpes), "min_net_sharpe": min(sharpes), "max_net_sharpe": max(sharpes),
        "median_net_max_drawdown": statistics.median(drawdowns), "median_net_total_return": statistics.median(returns),
        "phases": len(per_phase), "net_sharpe_by_phase": sharpes,
    }


def rule_verdict(base: dict, variant: dict) -> dict:
    """The shared R-BOOK2 / R-LEGACY / R-GATE / R-MODEL9-clause-4 margins on one scoring mode. `base` / `variant` =
    {split: phase_summary}."""
    gain = variant["backtest"]["median_net_sharpe"] - base["backtest"]["median_net_sharpe"]
    change = variant["validation"]["median_net_sharpe"] - base["validation"]["median_net_sharpe"]
    shares = {
        split: sum(1 for value in variant[split]["net_sharpe_by_phase"] if value > base[split]["median_net_sharpe"])
        / max(1, len(variant[split]["net_sharpe_by_phase"]))
        for split in SPLITS
    }
    checks = {
        "backtest_gain_ge_0.10": gain >= MIN_GAIN,
        "validation_not_worse_than_0.02": change >= -MAX_VALIDATION_LOSS,
        "beats_base_median_on_60pct_of_phases": all(share >= MIN_PHASE_SHARE for share in shares.values()),
        "positive_median_on_both_splits": all(variant[split]["median_net_sharpe"] > 0.0 for split in SPLITS),
        "drawdown_within_1pp": all(
            variant[split]["median_net_max_drawdown"] - base[split]["median_net_max_drawdown"] >= -MAX_DRAWDOWN_WORSENING
            for split in SPLITS
        ),
    }
    return {"checks": checks, "backtest_gain": gain, "validation_change": change, "phase_share": shares,
            "passes": all(checks.values())}


def legacy_clause(scores: dict) -> dict:
    """R-LEGACY's extra clause: the legacy component itself must earn a positive median return on both splits (a sleeve that
    only pays in a rising market is not a steady component). The sign of the median return is the sign of its Sharpe."""
    return {"legacy_component_positive_on_both_splits": all(
        scores["ungated"][split].get("legacy_net_return_median", 0.0) > 0.0 for split in SPLITS
    )}


def decide(base: dict, variant: dict, branch: str, extra_checks: dict | None = None) -> dict:
    verdict = {"ungated": rule_verdict(base["ungated"], variant["ungated"])}
    adopted = verdict["ungated"]["passes"]
    if branch == "A":
        verdict["as_live"] = rule_verdict(base["as_live"], variant["as_live"])
        verdict["as_live"]["checks"].pop("positive_median_on_both_splits", None)
        verdict["as_live"]["passes"] = all(verdict["as_live"]["checks"].values())
        adopted = adopted and verdict["as_live"]["passes"]
    for name, value in (extra_checks or {}).items():
        verdict.setdefault("extra_checks", {})[name] = bool(value)
        adopted = adopted and bool(value)
    verdict["adopted"] = bool(adopted)
    return verdict


DECISION_KEYS = ("decision_rank_20d", "decision_rank_20d_swapped_priority")


def best_decision_key(entry: dict) -> str:
    """The decision score (live priority, or the other model served first) with the higher validation non-overlapping IC:
    chosen on validation, then judged on backtest by the same key (R-HEAD2 adopts the matching priority)."""
    validation = entry["ensemble"]["validation"]
    scored = {key: (validation.get(key) or {}).get("non_overlapping_mean_ic") for key in DECISION_KEYS}
    return max((key for key in DECISION_KEYS if scored[key] is not None), key=lambda key: scored[key], default=DECISION_KEYS[0])


def model_ic_checks(model_ic: dict, name: str, control: str = "installed", spread_from: str = "ctl") -> dict:
    """R-MODEL9 clauses 1-2 from scripts/model_candidate_research.py's output: the candidate's validation decision IC
    beats the INSTALLED models' (what it would replace) by more than the seed spread of the retrained control config
    (`spread_from`: the range of its single members' validation IC) and is > 0; its backtest IC is at least the installed
    models' with HAC t >= 2. Each candidate and the control use their own best decision key (best_decision_key)."""
    candidates = model_ic["candidates"]
    candidate_key, control_key = best_decision_key(candidates[name]), best_decision_key(candidates[control])
    decision = lambda entry, split, key: entry["ensemble"][split][key]  # noqa: E731
    member_ics = []
    spread_key = candidate_key
    for scored in (candidates[spread_from].get("members_scored") or {}).values():
        value = (scored["validation"].get(spread_key) or {}).get("non_overlapping_mean_ic")
        if value is not None:
            member_ics.append(value)
    spread = (max(member_ics) - min(member_ics)) if len(member_ics) > 1 else 0.0
    cand_val = decision(candidates[name], "validation", candidate_key)["non_overlapping_mean_ic"] or 0.0
    ctl_val = decision(candidates[control], "validation", control_key)["non_overlapping_mean_ic"] or 0.0
    cand_bt = decision(candidates[name], "backtest", candidate_key)
    ctl_bt = decision(candidates[control], "backtest", control_key)
    return {
        "validation_beats_control_by_seed_spread": cand_val - ctl_val > spread and cand_val > 0.0,
        "backtest_ic_not_below_control": (cand_bt["daily_mean_ic"] or 0.0) >= (ctl_bt["daily_mean_ic"] or 0.0),
        "backtest_hac_t_ge_2": (cand_bt["hac_t"] or 0.0) >= 2.0,
        "decision_priority": "swapped" if candidate_key.endswith("swapped_priority") else "live",
    }


def head_blend_from_ic(model_ic: dict, candidate: str, passing_heads: set[str]) -> dict | None:
    """R-HEAD2's H1: every head in `passing_heads` with a positive validation IC, weighted by that IC, served by the model
    with the higher validation IC for it. Returns {"heads": {...}, "model_priority": [...]} or None."""
    validation = model_ic["candidates"][candidate]["ensemble"]["validation"]
    weights, preferred = {}, {}
    for key, stats in validation.items():
        if "." not in key:
            continue
        model, head = key.split(".", 1)
        ic = stats.get("daily_mean_ic")
        if head not in passing_heads or ic is None or ic <= 0.0:
            continue
        if ic > weights.get(head, 0.0):
            weights[head], preferred[head] = ic, model
    if not weights:
        return None
    total = sum(weights.values())
    votes: dict[str, float] = {}
    for head, model in preferred.items():
        votes[model] = votes.get(model, 0.0) + weights[head]
    priority = sorted(votes, key=lambda model: -votes[model]) + [m for m in ("sequence", "multitask") if m not in votes]
    return {"heads": {head: round(value / total, 4) for head, value in weights.items()}, "model_priority": priority}


_JOB: dict = {}


def _phase_worker(phase: int) -> dict:
    """One rebalance phase of the job set in `_JOB` (runs in a forked child that inherited the scored harness)."""
    from as_live_levers import summarize
    from lean_calibration import ANALYZER_INCLUDE, calibrated_overrides

    job = _JOB
    harness = job["harness"]
    kwargs = dict(calibrated_overrides(harness, phase=phase), **job["mechanisms"], include=ANALYZER_INCLUDE)
    if job["mode"] == "ungated":
        kwargs.update(gate="off", min_rank_confidence_spread=0.0)
    result = harness.as_live(config_overrides=job["resolved"] or None, **kwargs)
    summary = summarize(result)
    summary["legacy_net_return"] = sum(result.per_date_component_returns.get("legacy", {}).values())
    return summary


def map_phases(phases: list[int], workers: int) -> list[dict]:
    """The phases of the job in `_JOB`, across `workers` forked processes where fork exists (Linux: the Codespace has two
    cores), else one after another."""
    import multiprocessing
    import sys as _sys

    if workers > 1 and len(phases) > 1 and _sys.platform.startswith("linux"):
        with multiprocessing.get_context("fork").Pool(min(workers, len(phases))) as pool:
            return pool.map(_phase_worker, phases)
    return [_phase_worker(phase) for phase in phases]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=str(ROOT_DIR / "ml" / "datasets" / "full_dataset.csv"))
    parser.add_argument("--legacy-probability", required=True)
    parser.add_argument("--candidates", default=None, help="JSON {name: {ml_dir, ensemble, legacy_probability}}")
    parser.add_argument("--model-ic", default=str(ROOT_DIR / "ml" / "evaluation" / "v610" / "model_ic.json"))
    parser.add_argument("--branch", choices=("A", "B"), default=None, help="default: ml/evaluation/v610/calibration.json")
    parser.add_argument("--stages", nargs="*", default=["model", "head", "book", "costs", "legacy", "gate"])
    parser.add_argument("--max-phases", type=int, default=20)
    parser.add_argument("--workers", type=int, default=1, help="forked processes across the phases of one score (Linux)")
    parser.add_argument("--gate-warmup-days", type=int, default=400)
    parser.add_argument("--out", default=str(ROOT_DIR / "ml" / "evaluation" / "v610" / "research.json"))
    args = parser.parse_args()

    from as_live_levers import AsLiveHarness
    from lean_calibration import topology_inputs_fn_for, use_topology

    base_config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    branch = args.branch or json.loads((ROOT_DIR / "ml" / "evaluation" / "v610" / "calibration.json").read_text(encoding="utf-8"))["verdict"]["branch"]
    out_path = Path(args.out)
    report = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    report.update({"branch": branch, "max_phases": args.max_phases})
    adopted = report.setdefault("adopted", {"config": {}, "model": None, "rank_signal": None})
    candidates = json.loads(Path(args.candidates).read_text(encoding="utf-8")) if args.candidates else {}
    cache: dict = {}

    def model_spec(name: str | None) -> dict:
        return candidates.get(name, {}) if name else {}

    def harness_for(model: str | None, rank_signal: dict | None, split: str):
        spec = model_spec(model)
        key = (model, json.dumps(rank_signal, sort_keys=True), split)
        if key not in cache:
            if len(cache) >= 2:  # bounded memory: two harnesses resident at most
                cache.pop(next(iter(cache)))
            cfg = copy.deepcopy(base_config)
            if rank_signal:
                cfg["phase_v2"]["rank_signal"].update(rank_signal)
                cfg["phase_v2"]["rank_signal"]["demote_not_promotable_heads"] = False  # R-HEAD is judged by the rule itself
            if spec.get("ensemble"):
                cfg["phase_v2"]["model_ensemble"]["enabled"] = True
            harness = AsLiveHarness(
                split, dataset_path=args.dataset, config=cfg, ml_dir=(ROOT_DIR / spec["ml_dir"]) if spec.get("ml_dir") else None,
                legacy_probability_path=spec.get("legacy_probability") or args.legacy_probability,
                gate_warmup_days=args.gate_warmup_days,
            )
            cache[key] = (harness, topology_inputs_fn_for(harness, cfg), cfg)
        return cache[key]

    memo: dict = {}

    def score(changes: dict, *, model: str | None = None, rank_signal: dict | None = None,
              splits=SPLITS, modes=None) -> dict:
        modes = modes or (("ungated", "as_live") if branch == "A" else ("ungated",))
        memo_key = json.dumps([changes, model, rank_signal, list(splits), list(modes)], sort_keys=True, default=str)
        if memo_key in memo:  # a stage's base is the previous stage's adopted config: score it once
            return memo[memo_key]
        scored = score_uncached(changes, model=model, rank_signal=rank_signal, splits=splits, modes=modes)
        memo[memo_key] = scored
        return scored

    def score_uncached(changes: dict, *, model, rank_signal, splits, modes) -> dict:
        out: dict = {mode: {} for mode in modes}
        for split in splits:
            harness, topology_fn, cfg = harness_for(model, rank_signal, split)
            merged = apply_dotted(cfg, changes)
            cadence = int(merged["phase_v2"]["portfolio_book"].get("rebalance_every_bars", 20))
            resolved = {key: (cadence if value == "@cadence" else value) for key, value in (changes or {}).items()}
            use_topology(harness, topology_fn)
            mechanisms = harness.v610_mechanisms(merged)
            for mode in modes:
                _JOB.update(harness=harness, mechanisms=mechanisms, resolved=resolved, mode=mode)
                per_phase = map_phases(phases_for(cadence, args.max_phases), args.workers)
                out[mode][split] = phase_summary(per_phase)
                out[mode][split]["legacy_net_return_median"] = statistics.median(row["legacy_net_return"] for row in per_phase)
        return out

    def save():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=1, default=float), encoding="utf-8")

    def stage_header(name):
        print(f"=== stage {name}; adopted so far {json.dumps(adopted)}", flush=True)

    current = lambda: adopted["config"]  # noqa: E731

    if "model" in args.stages and candidates:
        stage_header("model")
        model_ic = json.loads(Path(args.model_ic).read_text(encoding="utf-8"))
        base = score(current())
        stage = {"base": base, "variants": {}}
        for name in candidates:
            if name == "installed":
                continue
            if not candidates[name].get("ic_pass"):
                # R-MODEL9 clauses 1-2 fail on IC alone: no book scores (a candidate without a model dir would be scored as
                # the installed models), the failing clauses are the evidence
                stage["variants"][name] = {"skipped": "IC clauses failed", "ic_checks": candidates[name].get("ic_checks")}
                print(f"  {name}: skipped, IC clauses {candidates[name].get('ic_checks')}", flush=True)
                continue
            ic = model_ic_checks(model_ic, name)
            # a candidate judged on the swapped-priority decision is scored with that priority, against the installed models
            # at the same priority, so only the model differs
            signal = {"model_priority": ["multitask", "sequence"]} if ic.get("decision_priority") == "swapped" else None
            result = score(current(), model=name, rank_signal=signal)
            base_same_priority = score(current(), rank_signal=signal)
            head_ok = bool(candidates[name].get("decision_heads_pass_r_head", False))
            latency_ok = float(candidates[name].get("latency_ratio", 1.0)) <= MAX_LATENCY_RATIO
            ic_flags = {key: value for key, value in ic.items() if key != "decision_priority"}
            verdict = decide(base_same_priority, result, branch, {**ic_flags, "decision_heads_pass_r_head": head_ok, "latency_within_1.5x": latency_ok})
            stage["variants"][name] = {"scores": result, "verdict": verdict, "rank_signal": signal, "base": base_same_priority}
            print(f"  {name}: adopted={verdict['adopted']} gain {verdict['ungated']['backtest_gain']:+.3f}", flush=True)
            save()
        winners = [name for name, entry in stage["variants"].items() if (entry.get("verdict") or {}).get("adopted")]
        if winners:
            adopted["model"] = max(winners, key=lambda name: stage["variants"][name]["scores"]["ungated"]["validation"]["median_net_sharpe"])
            adopted["rank_signal"] = stage["variants"][adopted["model"]].get("rank_signal")  # the priority it was judged under
        stage["adopted"] = adopted["model"]
        report["model"] = stage
        save()

    if "head" in args.stages:
        stage_header("head")
        model_ic = json.loads(Path(args.model_ic).read_text(encoding="utf-8"))
        source = adopted["model"] or "installed"
        passing = set(model_spec(adopted["model"]).get("passing_heads") or candidates.get("installed", {}).get("passing_heads") or [])
        blend = head_blend_from_ic(model_ic, source, passing) if source in model_ic.get("candidates", {}) else None
        current_signal = json.loads(json.dumps(base_config["phase_v2"]["rank_signal"]))
        # H2: the same heads and weights, the multitask model served first (validation IC: multitask rank heads 0.06, sequence 0.01)
        variants = {"H2": {"model_priority": ["multitask", "sequence"]}}
        if blend:
            variants["H1"] = blend
        base = score(current(), model=adopted["model"])
        stage = {"source": source, "h1": blend, "base": base, "variants": {}}
        for name, signal in variants.items():
            result = score(current(), model=adopted["model"], rank_signal=signal)
            verdict = decide(base, result, branch)
            stage["variants"][name] = {"rank_signal": signal, "scores": result, "verdict": verdict}
            print(f"  {name} {signal}: adopted={verdict['adopted']} gain {verdict['ungated']['backtest_gain']:+.3f}", flush=True)
            save()
        winners = [name for name, entry in stage["variants"].items() if entry["verdict"]["adopted"]]
        if winners:
            best = max(winners, key=lambda n: stage["variants"][n]["scores"]["ungated"]["validation"]["median_net_sharpe"])
            adopted["rank_signal"] = stage["variants"][best]["rank_signal"]
            stage["adopted"] = best
        else:
            stage["adopted"] = None
        stage["incumbent_rank_signal"] = {k: current_signal[k] for k in ("heads", "model_priority")}
        report["head"] = stage
        save()

    def single_change_stage(name: str, variants: dict, extra_report=None, extra_checks_fn=None):
        stage_header(name)
        base = score(current(), model=adopted["model"], rank_signal=adopted["rank_signal"])
        stage = {"base": base, "variants": {}}
        for variant, changes in variants.items():
            result = score({**current(), **changes}, model=adopted["model"], rank_signal=adopted["rank_signal"])
            verdict = decide(base, result, branch, extra_checks_fn(result) if extra_checks_fn else None)
            stage["variants"][variant] = {"changes": changes, "scores": result, "verdict": verdict}
            print(f"  {variant} {changes}: adopted={verdict['adopted']} gain {verdict['ungated']['backtest_gain']:+.3f} "
                  f"val {verdict['ungated']['validation_change']:+.3f} share {verdict['ungated']['phase_share']}", flush=True)
            save()
        winners = [variant for variant, entry in stage["variants"].items() if entry["verdict"]["adopted"]]
        chosen = max(winners, key=lambda v: stage["variants"][v]["scores"]["ungated"]["validation"]["median_net_sharpe"]) if winners else None
        if chosen:
            adopted["config"].update(variants[chosen])
        stage["adopted"] = chosen
        if extra_report:
            stage.update(extra_report())
        report[name] = stage
        save()

    if "book" in args.stages:
        single_change_stage("book", BOOK_VARIANTS, extra_report=lambda: {"cap_report": {
            str(cap): score({**current(), "portfolio_book.neutrality.gross_exposure_cap": cap}, model=adopted["model"],
                            rank_signal=adopted["rank_signal"], modes=("ungated",))
            for cap in CAP_REPORT
        }})
    if "costs" in args.stages:
        single_change_stage("costs", COST_VARIANTS)
    if "legacy" in args.stages:
        single_change_stage("legacy", LEGACY_VARIANTS, extra_checks_fn=legacy_clause)
    if "gate" in args.stages:
        if branch == "A":
            single_change_stage("gate", GATE_VARIANTS)
        else:
            report["gate"] = {"skipped": "R-CAL2 branch B: the gates stay frozen as safety controls"}
            save()

    report["final_holdout_seen"] = score(current(), model=adopted["model"], rank_signal=adopted["rank_signal"],
                                         splits=("holdout",), modes=("ungated", "as_live"))
    save()
    print("adopted:", json.dumps(adopted))
    print(f"written {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
