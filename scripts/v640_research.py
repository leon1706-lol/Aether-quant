"""V6.4.0 research chain (pre-registered rules for todo leads L1-L10 and R-DEDUPE2; plan V6.4.0). Written before any score.

Scoring is V6.2/V6.3's (scripts/v620_research.py, v630_research.py): the modelled portfolio (main book + legacy signal) on the
calibrated simulator, every rebalance phase (up to --max-phases evenly spaced ones) of both splits, the T-bill sweep off,
statistics = the median across phases (plus p10 / p25 / interquartile range). Two modes: AS-LIVE (rolling-IC gate on, the shipped
mechanisms) and UNGATED (gate and spread veto off; the gate is a safety control the offline simulator does not calibrate, R-CAL3
branch B). `verdict_ungated` = `rule_verdict` (backtest median gain >= +0.10, validation not worse than -0.02, >= 60% of phases
beating the base median on both splits, positive median on both splits, median drawdown within 1 pp). `verdict_as_live` = the
same without the positive-median clause (the gated book's median is near zero). Each stage scores on top of what the earlier
ones adopted. The holdout is never used to choose between variants; every read of it is logged in `report["holdout_reads"]`.

  dedupe  R-DEDUPE2 (Problems #201's second look, on the longer span): `rolling_ic_gate.late_bar_event_count` "once" against
          "per_tick", AS-LIVE, with validation and the pooled post-validation span (backtest + holdout) as the two splits.
          Adopted iff `verdict_as_live` passes. Either way #201 closes.
  l1      Engaged-day skill (a report and a precondition, no config change). On validation and backtest (holdout report only)
          the gate's per-date verdict splits the dates; rank IC (daily mean, non-overlapping, HAC t), the top-6/bottom-6 spread
          and the as-live Sharpe over the days whose latest rebalance was engaged are compared with all days. Bar (owner): on
          BOTH splits engaged - all >= +0.02 IC and >= +0.15 Sharpe (median over phases) -> "the gate protects capital";
          otherwise "the gate hides weakness" and L6 / L7 cannot ship.
  l8      Expert contribution to the legacy signal. contribution(e) = IC(legacy score) - IC(legacy score without expert e) on
          the engaged equity dates, both splits. Experts with contribution <= 0 on BOTH splits are disabled together
          (`gating_network.disabled_experts`) iff the book with them disabled is non-inferior as-live (median Sharpe change
          >= -0.02 on both splits).
  l2      Direction calibration. Heads: multitask / sequence direction_20d; temperature or isotonic fitted on VALIDATION only
          (cross-fitted for the honest validation loss), the method with the lower cross-fitted log-loss and the head with the
          lower raw log-loss are used. Overlays on the percentile ranks (portfolio.direction_overlay): C1 blend w=0.25,
          C2 blend w=0.5, C3 agree_filter margin 0.05. Adopted (best backtest median) iff `verdict_as_live` passes AND the
          median annualised turnover rises <= 20%. Otherwise "direction = diagnostic only".
  l3      Legacy vs the main book. (a) budgets, AS-LIVE: LG-off (legacy sleeve disabled), LG-half (0.025 gross / 0.01 per name),
          LG-double (0.10 / 0.04, with `legacy_clause`: the legacy component earns a positive median on both splits);
          adopted iff `verdict_as_live` passes AND the validation change is > 0. (b) the multitask model retrained with the
          previous day's legacy probability as an input (candidate v640_leg): adopted iff R-MODEL10's IC clauses pass with the
          yardstick fixed at the owner's 0.034, `verdict_as_live` passes, validation improves and latency <= 1.5x. (c) report:
          the legacy score's IC against rank_20d's by class and regime bucket.
  l4      Within-class equity ranking. W1: crypto leaves the main rank group (`separate_rank_groups.crypto`); W2:
          `rank_signal.normalization` "sector_relative"; W3: both. Adopted (best backtest median) iff the whole-book
          `verdict_as_live` is non-inferior (>= -0.02 on both splits), the engaged equity IC rises on both splits, the equity
          sleeve's gross Sharpe (from the logged weights) rises on both splits, and the holdout Sharpe falls by <= 0.10.
  l5      Turnover vs IC: rebalance_every_bars {10, 20, 40} x exits.max_holding_bars {20, 40, 60} against 20/40, AS-LIVE.
          Adopted (best backtest median) iff `verdict_as_live` passes and the median AND p25 phase Sharpe are >= the base's on
          both splits.
  l6      (skipped, closed by its precondition, unless L1 passed or --score-blocked-stages) Staggered book: T2 (2 tranches), T2h (2, half-way adjustment), T3, T3h, UNGATED (and AS-LIVE reported). Adopted iff
          the median >= base on both splits, the validation IQR <= base, p10 >= base on both splits, the cost drag rises <= 30%,
          and the L1 precondition holds.
  l7      (same precondition as L6) Kill-switch design: KD1 trip_confirm_bars 3, KD2 120 bars + confirm 3, KD3 release band -0.5 + confirm 3, KD4 floor
          -1.5, AS-LIVE. Adopted (lowest false-lock share) iff false-lock share < KS0's on both splits, the p95 phase max
          drawdown <= KS0's + 0.5 pp, the lock-path stability (Jaccard under N(0, 0.5 bp) noise) >= KS0's, the median Sharpe
          change >= -0.02 on both splits, and the L1 precondition holds. A false lock = a locked date after which the UNLOCKED
          book's next-20-day return is in its split's top third.
  l9      Crypto core vs graduates: bootstrap by trade on BT4's closed trades, leave-one-name-out (as-live), crypto-only IC.
          G0 (graduates ineligible) against graduates on: kept iff graduates beat G0 on the median Sharpe of BOTH splits.
  l10     Residual head: R1 (0.4 / 0.4 / 0.2), R2 (0.35 / 0.35 / 0.3), R3 (0.5 / 0 / 0.5) over rank_20d / rank_5d /
          residual_rank_20d, AS-LIVE. Adopted (best backtest median) iff `verdict_as_live` passes and |change in the market loading|
          and |change in the momentum loading| (evaluation.factor_neutralization_check) are both <= 0.10.

    python scripts/v640_research.py --dataset ml/datasets/v640_full_dataset.csv --legacy-probability ml/datasets/legacy_probability.csv
        --legacy-components ml/datasets/legacy_components.csv [--candidates ml/evaluation/v640/candidates.json]
        [--model-ic ml/evaluation/v640/model_ic.json] [--lean-run backtests/2026-10-18_12-55-00]
        [--stages dedupe l1 l8 l2 l3 l4 l5 l6 l7 l9 l10] [--max-phases 10] [--workers 2]
        [--out ml/evaluation/v640/research.json] [--adopted-config-out ml/evaluation/v640/adopted_changes.json]
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import statistics
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from v610_research import MAX_LATENCY_RATIO, SPLITS, apply_dotted, legacy_clause, phases_for, rule_verdict  # noqa: E402
from v620_research import model10_checks  # noqa: E402
from v630_research import interquartile_range, jaccard, perturbation  # noqa: E402

# ---------------------------------------------------------------- pre-registered variants and margins

DEDUPE_VARIANT = {"rolling_ic_gate.late_bar_event_count": "once"}
DEDUPE_SPECS = {"validation": "validation", "backtest": ("backtest", "holdout")}
L2_VARIANTS = {
    "C1": {"mode": "blend", "weight": 0.25},
    "C2": {"mode": "blend", "weight": 0.5},
    "C3": {"mode": "agree_filter", "margin": 0.05},
}
MAX_TURNOVER_RISE = 0.20
LEGACY_VARIANTS = {
    "LG-off": {"legacy_sleeve.enabled": False},
    "LG-half": {"legacy_sleeve.max_gross_exposure": 0.025, "legacy_sleeve.max_weight_per_name": 0.01},
    "LG-double": {"legacy_sleeve.max_gross_exposure": 0.10, "legacy_sleeve.max_weight_per_name": 0.04},
}
MODEL_YARDSTICK = 0.034
SEPARATE_GROUPS_WITH_CRYPTO = {"forex": ["forex"], "bond": ["bond"], "crypto": ["crypto"]}
L4_VARIANTS = {
    "W1": {"patch": {"phase1.target.ranking.separate_rank_groups": SEPARATE_GROUPS_WITH_CRYPTO}, "changes": {}},
    "W2": {"patch": {}, "changes": {"rank_signal.normalization": "sector_relative"}},
    "W3": {"patch": {"phase1.target.ranking.separate_rank_groups": SEPARATE_GROUPS_WITH_CRYPTO},
           "changes": {"rank_signal.normalization": "sector_relative"}},
}
L4_HOLDOUT_MAX_LOSS = 0.10
L4_NON_INFERIOR = -0.02
L5_VARIANTS = {
    f"R{rebalance}/H{hold}": {"portfolio_book.rebalance_every_bars": rebalance, "exits.max_holding_bars": hold}
    for rebalance in (10, 20, 40) for hold in (20, 40, 60) if (rebalance, hold) != (20, 40)
}
L6_VARIANTS = {
    "T2": {"tranches": 2, "adjust": 1.0}, "T2h": {"tranches": 2, "adjust": 0.5},
    "T3": {"tranches": 3, "adjust": 1.0}, "T3h": {"tranches": 3, "adjust": 0.5},
}
MAX_COST_RISE = 0.30
L7_VARIANTS = {
    "KD1": {"risk.kill_switch.trip_confirm_bars": 3},
    "KD2": {"risk.kill_switch.evaluation_bars": 120, "risk.kill_switch.trip_confirm_bars": 3},
    "KD3": {"risk.kill_switch.release_rolling_sharpe": -0.5, "risk.kill_switch.trip_confirm_bars": 3},
    "KD4": {"risk.kill_switch.min_rolling_sharpe": -1.5},
}
L7_DRAWDOWN_CAP = 0.005
L7_NON_INFERIOR = -0.02
NOISE_SEEDS = (1, 2, 3)
STABILITY_PHASES = 5
L10_VARIANTS = {
    "R1": {"rank_20d": 0.4, "rank_5d": 0.4, "residual_rank_20d": 0.2},
    "R2": {"rank_20d": 0.35, "rank_5d": 0.35, "residual_rank_20d": 0.3},
    "R3": {"rank_20d": 0.5, "rank_5d": 0.0, "residual_rank_20d": 0.5},
}
L10_MAX_FACTOR_SHIFT = 0.10
EXPERTS = ("bullish", "bearish", "sideways", "volatility")
LOO_PHASES = 5


# ---------------------------------------------------------------- pure clause functions (unit-tested)


def quantile(values, q: float) -> float:
    ordered = sorted(float(value) for value in values)
    position = q * (len(ordered) - 1)
    low, high = int(position // 1), min(int(-(-position // 1)), len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def extended_summary(per_phase: list[dict]) -> dict:
    """`v610_research.phase_summary` plus the figures this chain's clauses read (all lists are by phase)."""
    from v610_research import phase_summary

    summary = phase_summary(per_phase)
    sharpes = summary["net_sharpe_by_phase"]
    summary.update(
        p10_net_sharpe=quantile(sharpes, 0.10), p25_net_sharpe=quantile(sharpes, 0.25), iqr_net_sharpe=interquartile_range(sharpes),
        net_max_drawdown_by_phase=[row["net_max_drawdown"] for row in per_phase],
        p05_net_max_drawdown=quantile([row["net_max_drawdown"] for row in per_phase], 0.05),
        cost_drag_by_phase=[row["cost_drag_annual_bps"] for row in per_phase],
        median_turnover=statistics.median(row["annualized_turnover"] for row in per_phase),
        locked_dates_by_phase=[len(row.get("locked_dates", [])) for row in per_phase],
        legacy_net_return_median=statistics.median(row.get("legacy_net_return", 0.0) for row in per_phase),
    )
    for name in ("engaged_sharpe", "all_sharpe", "equity_sharpe", "false_lock_share"):
        values = [row[name] for row in per_phase if row.get(name) is not None]
        if values:
            summary[f"{name}_by_phase"] = values
            summary[f"{name}_median"] = statistics.median(values)
    return summary


def verdict_as_live(base: dict, variant: dict) -> dict:
    """`rule_verdict` on AS-LIVE scores: the gated book's median Sharpe sits near zero, so the positive-median clause goes."""
    verdict = rule_verdict(base, variant)
    verdict["checks"].pop("positive_median_on_both_splits", None)
    verdict["passes"] = all(verdict["checks"].values())
    return verdict


def best_by_backtest(names, scores: dict) -> str | None:
    names = list(names)
    return max(names, key=lambda name: scores[name]["backtest"]["median_net_sharpe"]) if names else None


def l1_margins(skill: dict, base_summary: dict) -> dict:
    """{"ic_margin", "sharpe_margin"} of one split: engaged - all IC, and the median over phases of (engaged - all) Sharpe."""
    engaged = base_summary.get("engaged_sharpe_by_phase") or []
    everything = base_summary.get("all_sharpe_by_phase") or []
    margins = [a - b for a, b in zip(engaged, everything)]
    return {"ic_margin": skill.get("ic_margin"), "sharpe_margin": statistics.median(margins) if margins else None}


def l2_checks(base: dict, variant: dict) -> dict:
    base_turnover = statistics.median([base[s]["median_turnover"] for s in SPLITS])
    variant_turnover = statistics.median([variant[s]["median_turnover"] for s in SPLITS])
    return {"turnover_rise_le_20pct": variant_turnover <= (1.0 + MAX_TURNOVER_RISE) * max(base_turnover, 1e-9)}


def l3_budget_checks(verdict: dict, scores: dict, variant_name: str) -> dict:
    checks = {"validation_improves": verdict["validation_change"] > 0.0}
    if variant_name == "LG-double":
        checks.update(legacy_clause({"ungated": scores}))
    return checks


def l3_model_checks(model_ic_checks: dict, verdict: dict, latency_ratio: float | None) -> dict:
    return {
        "validation_beats_installed_by_0.034": model_ic_checks["validation_beats_installed_by_yardstick"],
        "backtest_ic_not_below_installed_minus_0.034": model_ic_checks["backtest_ic_not_below_installed_minus_yardstick"],
        "backtest_hac_t_ge_2": model_ic_checks["backtest_hac_t_ge_2"],
        "book_verdict_as_live_passes": verdict["passes"],
        "validation_book_improves": verdict["validation_change"] > 0.0,
        "latency_le_1.5x": latency_ratio is not None and latency_ratio <= MAX_LATENCY_RATIO,
    }


def l4_checks(base: dict, variant: dict, verdict: dict, ic_by_split: dict, holdout_loss: float | None) -> dict:
    """`ic_by_split` = {split: {"base": engaged equity IC, "variant": ...}}; `holdout_loss` = base - variant holdout Sharpe."""
    return {
        "whole_book_non_inferior": verdict["backtest_gain"] >= L4_NON_INFERIOR and verdict["validation_change"] >= L4_NON_INFERIOR,
        "engaged_equity_ic_up_on_both_splits": all(
            ic_by_split[s]["variant"] is not None and ic_by_split[s]["base"] is not None and ic_by_split[s]["variant"] > ic_by_split[s]["base"]
            for s in SPLITS
        ),
        "equity_sharpe_up_on_both_splits": all(
            variant[s].get("equity_sharpe_median") is not None and base[s].get("equity_sharpe_median") is not None
            and variant[s]["equity_sharpe_median"] > base[s]["equity_sharpe_median"] for s in SPLITS
        ),
        "holdout_loss_le_0.10": holdout_loss is not None and holdout_loss <= L4_HOLDOUT_MAX_LOSS,
    }


def l5_checks(base: dict, variant: dict) -> dict:
    return {
        "median_not_below_base_on_both_splits": all(variant[s]["median_net_sharpe"] >= base[s]["median_net_sharpe"] for s in SPLITS),
        "p25_not_below_base_on_both_splits": all(variant[s]["p25_net_sharpe"] >= base[s]["p25_net_sharpe"] for s in SPLITS),
    }


def l6_checks(base: dict, variant: dict, l1_pass: bool) -> dict:
    base_cost = statistics.median(base["validation"]["cost_drag_by_phase"] + base["backtest"]["cost_drag_by_phase"])
    variant_cost = statistics.median(variant["validation"]["cost_drag_by_phase"] + variant["backtest"]["cost_drag_by_phase"])
    return {
        "median_not_below_base_on_both_splits": all(variant[s]["median_net_sharpe"] >= base[s]["median_net_sharpe"] for s in SPLITS),
        "validation_iqr_not_wider": variant["validation"]["iqr_net_sharpe"] <= base["validation"]["iqr_net_sharpe"],
        "p10_not_below_base_on_both_splits": all(variant[s]["p10_net_sharpe"] >= base[s]["p10_net_sharpe"] for s in SPLITS),
        "cost_drag_rise_le_30pct": variant_cost <= (1.0 + MAX_COST_RISE) * max(base_cost, 1e-9),
        "l1_precondition": bool(l1_pass),
    }


def l7_checks(base: dict, variant: dict, base_stability: float, variant_stability: float, l1_pass: bool) -> dict:
    def share(scores, split):
        values = scores[split].get("false_lock_share_by_phase") or []
        return statistics.median(values) if values else None

    lower_false_locks = all(
        share(variant, s) is not None and share(base, s) is not None and share(variant, s) < share(base, s) for s in SPLITS
    )
    return {
        "false_lock_share_below_base_on_both_splits": lower_false_locks,
        "p95_drawdown_within_0.5pp": all(
            variant[s]["p05_net_max_drawdown"] - base[s]["p05_net_max_drawdown"] >= -L7_DRAWDOWN_CAP for s in SPLITS
        ),
        "stability_not_below_base": variant_stability >= base_stability,
        "median_sharpe_non_inferior": all(
            variant[s]["median_net_sharpe"] - base[s]["median_net_sharpe"] >= L7_NON_INFERIOR for s in SPLITS
        ),
        "l1_precondition": bool(l1_pass),
    }


def l8_decision(contributions: dict[str, dict[str, float | None]], ablated_verdict: dict | None) -> dict:
    """`contributions` = {expert: {split: IC(full) - IC(without expert)}}. The experts with contribution <= 0 on both splits,
    and whether disabling them together is non-inferior."""
    useless = sorted(
        expert for expert, by_split in contributions.items()
        if all(by_split.get(s) is not None and by_split[s] <= 0.0 for s in SPLITS)
    )
    non_inferior = (
        ablated_verdict is not None and ablated_verdict["backtest_gain"] >= -0.02 and ablated_verdict["validation_change"] >= -0.02
    )
    return {"disable": useless if non_inferior else [], "candidates_with_no_contribution": useless, "non_inferior": non_inferior}


def l9_decision(graduates_on: dict, graduates_off: dict) -> dict:
    wins = {s: graduates_on[s]["median_net_sharpe"] > graduates_off[s]["median_net_sharpe"] for s in SPLITS}
    return {"graduates_beat_core_only_on": wins, "keep_graduates": all(wins.values())}


def l10_checks(verdict: dict, shift: dict) -> dict:
    """`shift` = {"market": change in the book's market loading, "momentum": change in its momentum loading}."""
    return {
        "market_loading_shift_le_0.10": abs(shift.get("market", 0.0)) <= L10_MAX_FACTOR_SHIFT,
        "momentum_loading_shift_le_0.10": abs(shift.get("momentum", 0.0)) <= L10_MAX_FACTOR_SHIFT,
        "verdict_as_live_passes": verdict["passes"],
    }


def all_pass(checks: dict) -> bool:
    return all(bool(value) for value in checks.values())


def patch_config(config: dict, patches: dict) -> dict:
    """A deep copy of `config` with `{full.dotted.path: value}` set (paths from the config root, unlike `apply_dotted`)."""
    result = copy.deepcopy(config)
    for dotted, value in (patches or {}).items():
        node = result
        *parents, leaf = dotted.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = value
    return result


# ---------------------------------------------------------------- the scoring layer (runs on the Codespace)

_JOB: dict = {}


def _phase_worker(task: tuple[int, int | None]) -> dict:
    from as_live_levers import summarize
    from lean_calibration import ANALYZER_INCLUDE, calibrated_overrides

    from evaluation.engaged_day_skill import engaged_window_returns, sharpe

    phase, seed = task
    job = _JOB
    harness = job["harness"]
    kwargs = dict(calibrated_overrides(harness, phase=phase), **job["mechanisms"], include=ANALYZER_INCLUDE)
    if job["mode"] == "ungated":
        kwargs.update(gate="off", min_rank_confidence_spread=0.0)
    if seed is not None:
        kwargs["kill_switch_extra_returns"] = perturbation(job["dates"], seed, kwargs.get("kill_switch_extra_returns"))
    if job.get("overlay_fn") is not None:
        kwargs["rank_overlay_fn"] = job["overlay_fn"]
    if job.get("candidate_metadata") is not None:
        kwargs["candidate_metadata_by_ticker"] = job["candidate_metadata"]
    if "equity" in job["extras"]:
        kwargs["log_weights"] = True
    result = harness.as_live(config_overrides=job["resolved"] or None, tranches=job.get("tranches", 1), **kwargs)
    summary = summarize(result)
    components = result.per_date_component_returns or {}
    summary["legacy_net_return"] = sum(components.get("legacy", {}).values())
    summary["locked_dates"] = list(result.kill_switch_locked_date_list or [])
    returns = dict(zip(result.per_date, result.per_date_net_return))
    if "returns" in job["extras"]:
        summary["returns"] = returns
    if "engaged" in job["extras"]:
        engaged, everything = engaged_window_returns(returns, result.rebalance_log or [])
        summary["engaged_sharpe"], summary["all_sharpe"] = sharpe(engaged), sharpe(everything)
    if "equity" in job["extras"]:
        summary["equity_sharpe"] = equity_gross_sharpe(result, job["frame_returns"], job["equity_tickers"])
    return summary


def equity_gross_sharpe(result, frame_returns: dict, equity_tickers: set) -> float | None:
    """Sharpe of the equity part of the book alone, from the logged held weights x the dated next-day returns (gross of costs;
    the effective-weight lag of the calibrated simulator is ignored, identically for every variant)."""
    from evaluation.engaged_day_skill import sharpe

    series = []
    for day, weights in zip(result.per_date, result.weights_log or []):
        returns = frame_returns.get(day, {})
        series.append(sum(weight * returns.get(ticker, 0.0) for ticker, weight in weights.items() if ticker in equity_tickers))
    return sharpe(series)


def map_tasks(tasks: list, workers: int) -> list[dict]:
    import multiprocessing

    if workers > 1 and len(tasks) > 1 and sys.platform.startswith("linux"):
        with multiprocessing.get_context("fork").Pool(min(workers, len(tasks))) as pool:
            return pool.map(_phase_worker, tasks)
    return [_phase_worker(task) for task in tasks]


class Research:
    """Harness pool, memoised scoring and the report; stages talk to it through `score`, `harness`, `labels`."""

    def __init__(self, args, base_config: dict, report: dict, out_path: Path):
        self.args = args
        self.base_config = base_config
        self.report = report
        self.out_path = out_path
        self.pool: dict = {}
        self.memo_path = out_path.with_suffix(".memo.json")
        self.memo: dict = json.loads(self.memo_path.read_text(encoding="utf-8")) if self.memo_path.exists() else {}
        # a resumed run replays every stage from the memo and re-adopts in order: the previous run's adoptions must not leak
        # into the earlier stages' base config (memo keys include it), so the chain always starts from the shipped config
        self.adopted = report["adopted"] = {"config": {}, "tranches": 1, "adjust_fraction": 1.0, "patch": {}, "model": None,
                                            "direction_overlay": None, "needs_live_path": []}
        report.pop("l1_pass", None)
        self.report.setdefault("holdout_reads", [])

    # -- persistence
    def save(self) -> None:
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.out_path.write_text(json.dumps(self.report, indent=1, default=float), encoding="utf-8")
        self.memo_path.write_text(json.dumps(self.memo, default=float), encoding="utf-8")

    def log_holdout_read(self, stage: str, what: str) -> None:
        entry = {"stage": stage, "what": what}
        if entry not in self.report["holdout_reads"]:  # a resumed run replays the stage: one read, one entry
            self.report["holdout_reads"].append(entry)

    # -- harnesses
    def harness(self, split, *, patch: dict | None = None, model: str | None = None):
        from as_live_levers import AsLiveHarness
        from lean_calibration import topology_inputs_fn_for

        spec = (self.args.candidates_spec or {}).get(model, {}) if model else {}
        key = json.dumps([list(split) if isinstance(split, tuple) else split, patch or {}, model], sort_keys=True, default=str)
        if key not in self.pool:
            while len(self.pool) >= 4:
                self.pool.pop(next(iter(self.pool)))
            config = patch_config(self.base_config, patch or {})
            if spec.get("ensemble"):
                config["phase_v2"]["model_ensemble"]["enabled"] = True
            harness = AsLiveHarness(
                split, dataset_path=spec.get("dataset") or self.args.dataset, config=config,
                ml_dir=(ROOT_DIR / spec["ml_dir"]) if spec.get("ml_dir") else None,
                legacy_probability_path=spec.get("legacy_probability") or self.args.legacy_probability,
                gate_warmup_days=self.args.gate_warmup_days,
            )
            self.pool[key] = (harness, topology_inputs_fn_for(harness, config), config)
        return self.pool[key]

    @contextlib.contextmanager
    def legacy_override(self, harness, probabilities: dict):
        """Swap the legacy probability column of a harness' frames for `{(date, ticker): p}` while the block runs."""
        from as_live_levers import LEGACY_PROBABILITY_COLUMN

        saved = {name: getattr(harness, name)[LEGACY_PROBABILITY_COLUMN].copy() for name in ("frame", "lagged_frame")}
        try:
            for name in saved:
                frame = getattr(harness, name)
                keys = list(zip(frame["date"].astype(str).str[:10], frame["ticker"].astype(str)))
                frame[LEGACY_PROBABILITY_COLUMN] = [probabilities.get(key, value) for key, value in zip(keys, saved[name])]
            yield
        finally:
            for name, column in saved.items():
                getattr(harness, name)[LEGACY_PROBABILITY_COLUMN] = column

    # -- scoring
    def score(self, changes: dict, *, patch: dict | None = None, specs: dict | None = None, tranches: int = 1, mode: str = "ungated",
              model: str | None = None, overlay: dict | None = None, extras: tuple = (), stability: bool = False,
              eligible_override: set | None = None, legacy_probabilities: dict | None = None, phases: int | None = None,
              memo_tag: str = "") -> dict:
        from lean_calibration import use_topology

        specs = specs or {split: split for split in SPLITS}
        overlay_key = {k: v for k, v in (overlay or {}).items() if k != "probabilities"} or None
        key = hashlib.sha1(json.dumps([changes, patch, sorted(map(str, specs.items())), tranches, mode, model, overlay_key, list(extras),
                                        stability, sorted(eligible_override) if eligible_override is not None else None,
                                        legacy_probabilities is not None, phases, memo_tag], sort_keys=True, default=str).encode()).hexdigest()
        if key in self.memo:
            return self.memo[key]
        out: dict = {}
        for name, split in specs.items():
            harness, topology_fn, config = self.harness(split, patch=patch, model=model)
            merged = apply_dotted(config, changes)
            use_topology(harness, topology_fn)
            cadence = int(merged["phase_v2"]["portfolio_book"].get("rebalance_every_bars", 20))
            candidate_metadata = None
            if eligible_override is not None:
                candidate_metadata = {t: dict(v) for t, v in harness.metadata.items()}
                for ticker, kind in harness.asset_class_by_ticker.items():
                    if kind == "crypto":
                        candidate_metadata[ticker]["trading_eligible"] = ticker in eligible_override
            frame_returns = None
            equity_tickers = {t for t, kind in harness.asset_class_by_ticker.items() if kind == "equity"}
            if "equity" in extras:
                frame_returns = {}
                for row in harness.lagged_frame[["date", "ticker", "target_return_1d"]].itertuples(index=False):
                    frame_returns.setdefault(str(row[0])[:10], {})[str(row[1])] = float(row[2]) if row[2] == row[2] else 0.0
            overlay_fn = self.overlay_fn(harness, overlay) if overlay else None
            context = self.legacy_override(harness, legacy_probabilities) if legacy_probabilities else contextlib.nullcontext()
            with context:
                _JOB.update(harness=harness, mechanisms=harness.v610_mechanisms(merged), resolved=dict(changes), mode=mode,
                            tranches=tranches, dates=sorted(map(str, harness.frame["date"].unique())), extras=tuple(extras),
                            overlay_fn=overlay_fn, candidate_metadata=candidate_metadata, frame_returns=frame_returns,
                            equity_tickers=equity_tickers)
                phase_list = phases_for(cadence, phases or self.args.max_phases)
                per_phase = map_tasks([(phase, None) for phase in phase_list], self.args.workers)
                summary = extended_summary(per_phase)
                if "returns" in extras:
                    summary["returns_by_phase"] = [row["returns"] for row in per_phase]
                    summary["locked_dates_lists"] = [row["locked_dates"] for row in per_phase]
                if stability and name == "backtest":
                    picked = phase_list[:: max(1, len(phase_list) // STABILITY_PHASES)][:STABILITY_PHASES]
                    locked = {phase: row["locked_dates"] for phase, row in zip(phase_list, per_phase)}
                    tasks = [(phase, seed) for phase in picked for seed in NOISE_SEEDS]
                    perturbed = map_tasks(tasks, self.args.workers)
                    overlaps = [jaccard(locked[phase], row["locked_dates"]) for (phase, _seed), row in zip(tasks, perturbed)]
                    summary["stability_jaccard_median"] = statistics.median(overlaps)
            out[name] = summary
        self.memo[key] = out
        self.save()
        return out

    def overlay_fn(self, harness, overlay: dict):
        """rank_overlay_fn(date, ranks) running portfolio.direction_overlay with a calibrated head probability per row."""
        from portfolio.direction_overlay import apply_direction_overlay, resolve_direction_overlay

        params = resolve_direction_overlay({"enabled": True, **{k: v for k, v in overlay.items() if k not in ("probabilities",)}})
        probabilities = overlay["probabilities"]
        groups = harness.rank_groups

        def apply(date, ranks):
            return apply_direction_overlay(ranks, {t: probabilities.get((date, t)) for t in ranks}, params, groups)

        return apply


# ---------------------------------------------------------------- stages


def stage_dedupe(ctx: Research) -> dict:
    base = ctx.score(ctx.adopted["config"], specs=DEDUPE_SPECS, mode="as_live", memo_tag="dedupe")
    variant = ctx.score({**ctx.adopted["config"], **DEDUPE_VARIANT}, specs=DEDUPE_SPECS, mode="as_live", memo_tag="dedupe")
    verdict = verdict_as_live(base, variant)
    ctx.log_holdout_read("dedupe", "backtest+holdout pooled span, as-live, base and 'once'")
    if verdict["passes"]:
        ctx.adopted["config"].update(DEDUPE_VARIANT)
    return {"base": base, "variant": variant, "verdict": verdict, "adopted": verdict["passes"]}


def main_group_frame(harness):
    from evaluation.live_parity import main_group_tickers

    frame = harness.lagged_frame
    tickers = main_group_tickers(harness.rank_groups, frame["ticker"].unique())
    if tickers is not None:
        frame = frame[frame["ticker"].astype(str).isin(tickers)]
    return frame[frame["target_rank_20d"].notna()] if "target_rank_20d" in frame.columns else frame


def engaged_labels(ctx: Research, harness, config: dict) -> dict:
    from evaluation.engaged_day_skill import gate_labels

    cfg = config["phase_v2"].get("rolling_ic_gate", {}) or {}
    gate_fn = harness.gate_for(harness.lagged_frame, ic_floor=cfg.get("min_rolling_mean_ic"),
                               late_bar_event_count=cfg.get("late_bar_event_count"))
    return gate_labels(gate_fn, sorted(set(harness.lagged_frame["date"].astype(str).str[:10])))


def stage_l1(ctx: Research) -> dict:
    from evaluation.engaged_day_skill import engaged_vs_all, l1_verdict

    skills, margins, summaries = {}, {}, {}
    for split in (*SPLITS, "holdout"):
        harness, _topology, config = ctx.harness(split)
        merged = apply_dotted(config, ctx.adopted["config"])
        labels = engaged_labels(ctx, harness, merged)
        skills[split] = engaged_vs_all(main_group_frame(harness), labels)
        summaries[split] = ctx.score(ctx.adopted["config"], specs={split: split}, mode="as_live", extras=("engaged",),
                                     memo_tag="l1")[split]
        margins[split] = l1_margins(skills[split], summaries[split])
    ctx.log_holdout_read("l1", "holdout engaged-vs-all skill and gated Sharpe (report only)")
    verdict = l1_verdict({s: margins[s] for s in SPLITS})
    stage = {"skill": skills, "margins": margins, "verdict": verdict, "gate_protects_capital": verdict["gate_protects_capital"]}
    ctx.report["l1_pass"] = verdict["gate_protects_capital"]
    return stage


def equity_engaged_ic(ctx: Research, split, config_changes: dict, patch: dict | None, probabilities: dict | None = None) -> float | None:
    """Daily mean rank IC of the live rank score (or of `probabilities`, a legacy score) on the ENGAGED equity dates of a split."""
    from evaluation.engaged_day_skill import engaged_vs_all

    harness, _t, config = ctx.harness(split, patch=patch)
    frame = main_group_frame(harness)
    equity = {t for t, kind in harness.asset_class_by_ticker.items() if kind == "equity"}
    frame = frame[frame["ticker"].astype(str).isin(equity)]
    score_column = "live_rank_score"
    if probabilities is not None:
        frame = frame.copy()
        keys = zip(frame["date"].astype(str).str[:10], frame["ticker"].astype(str))
        frame["legacy_score"] = [probabilities.get(key) for key in keys]
        score_column = "legacy_score"
    labels = engaged_labels(ctx, harness, apply_dotted(config, config_changes))
    return (engaged_vs_all(frame, labels, score_column=score_column).get("engaged") or {}).get("daily_mean_ic")


def stage_l8(ctx: Research) -> dict:
    import pandas as pd
    from build_legacy_probability import legacy_probability_from_components

    components = pd.read_csv(ctx.args.legacy_components)
    components["date"] = components["date"].astype(str).str[:10]
    config = ctx.base_config
    metrics_path = ROOT_DIR / "ml" / "expert_training_metrics.json"
    expert_metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
    keys = list(zip(components["date"], components["ticker"].astype(str)))
    rows = components.to_dict("records")

    def probabilities(excluded=()):
        return {key: legacy_probability_from_components(row, expert_metrics, config, tuple(excluded)) for key, row in zip(keys, rows)}

    full = probabilities()
    contributions: dict = {expert: {} for expert in EXPERTS}
    ablated = {expert: probabilities((expert,)) for expert in EXPERTS}
    for split in SPLITS:
        ic_full = equity_engaged_ic(ctx, split, ctx.adopted["config"], None, full)
        for expert in EXPERTS:
            without = equity_engaged_ic(ctx, split, ctx.adopted["config"], None, ablated[expert])
            contributions[expert][split] = None if ic_full is None or without is None else ic_full - without
    base = ctx.score(ctx.adopted["config"], mode="as_live", memo_tag="l8")
    scores = {}
    for expert in EXPERTS:
        scores[expert] = ctx.score(ctx.adopted["config"], mode="as_live", legacy_probabilities=ablated[expert], memo_tag=f"l8-{expert}")
    useless = sorted(e for e, by in contributions.items() if all(by.get(s) is not None and by[s] <= 0.0 for s in SPLITS))
    combined_verdict = None
    if useless:
        combined = probabilities(useless)
        combined_scores = ctx.score(ctx.adopted["config"], mode="as_live", legacy_probabilities=combined, memo_tag="l8-" + "+".join(useless))
        combined_verdict = verdict_as_live(base, combined_scores)
    decision = l8_decision(contributions, combined_verdict)
    if decision["disable"]:
        ctx.adopted["config"]["gating_network.disabled_experts"] = decision["disable"]
        ctx.adopted["legacy_experts_disabled"] = decision["disable"]
    return {"contributions": contributions, "ablated_scores": scores, "base": base, "combined_verdict": combined_verdict,
            "decision": decision}


def calibration_for_head(frame, head_column: str):
    """Fit on the validation frame, return the report and the chosen map {"method", ...}."""
    from evaluation.probability_calibration import calibration_report

    report = calibration_report(frame[head_column].to_numpy(), frame["target_direction_20d"].to_numpy())
    cross = report["cross_fitted_log_loss"]
    methods = {m: v for m, v in cross.items() if v is not None and m != "raw"}
    if not methods:
        return report, None
    method = min(methods, key=methods.get)
    if method == "temperature" and report["temperature"]:
        return report, {"method": "temperature", "temperature": report["temperature"]}
    if method == "isotonic" and report["isotonic"]:
        return report, {"method": "isotonic", **report["isotonic"]}
    return report, None


def stage_l2(ctx: Research) -> dict:
    import numpy as np

    from evaluation.live_parity import lag_predictions_for_tickers
    from evaluation.model_predictions import predict_head

    heads = {}
    probabilities_by_head = {}
    for kind, model_file, schema_file in (("multitask", "multitask_model.json", "multitask_feature_schema.json"),
                                          ("sequence", "sequence_model.json", "sequence_feature_schema.json")):
        export = json.loads((ROOT_DIR / "ml" / model_file).read_text(encoding="utf-8"))
        schema = json.loads((ROOT_DIR / "ml" / schema_file).read_text(encoding="utf-8"))
        window = int(ctx.base_config["phase_v2"].get("sequence_model", {}).get("window_size", 30))
        per_split = {}
        for split in SPLITS:
            harness, _t, _c = ctx.harness(split)
            frame = harness.lagged_frame
            main = main_group_frame(harness)
            values = predict_head(frame, export, schema["model_input_names"], "direction_20d", model_kind=kind,
                                  sequence_feature_schema=schema if kind == "sequence" else None, configured_window_size=window)
            scored = lag_predictions_for_tickers(frame.assign(head=values), prediction_column="head", tickers=harness.late_bar_tickers)
            per_split[split] = (scored, scored[scored["ticker"].isin(set(main["ticker"]))])
        validation_frame = per_split["validation"][1].dropna(subset=["head", "target_direction_20d"])
        report, calibration = calibration_for_head(validation_frame, "head")
        backtest_frame = per_split["backtest"][1].dropna(subset=["head", "target_direction_20d"])
        from evaluation.probability_calibration import apply_isotonic, apply_temperature, balanced_accuracy, log_loss

        raw_backtest = log_loss(backtest_frame["head"], backtest_frame["target_direction_20d"])
        calibrated_backtest = None
        if calibration:
            mapped = (apply_temperature(backtest_frame["head"], calibration["temperature"]) if calibration["method"] == "temperature"
                      else np.clip(apply_isotonic(backtest_frame["head"], calibration), 1e-6, 1 - 1e-6))
            calibrated_backtest = log_loss(mapped, backtest_frame["target_direction_20d"])
        heads[kind] = {"validation": report, "calibration": calibration, "backtest_raw_log_loss": raw_backtest,
                       "backtest_calibrated_log_loss": calibrated_backtest,
                       "backtest_balanced_accuracy": balanced_accuracy(backtest_frame["head"], backtest_frame["target_direction_20d"])}
        probabilities_by_head[kind] = per_split
    chosen = min(heads, key=lambda k: heads[k]["validation"]["log_loss"] if heads[k]["validation"]["log_loss"] is not None else 9.9)
    calibration = heads[chosen]["calibration"]

    def probability_map(split_key):
        from portfolio.direction_overlay import calibrate_probability

        scored = probabilities_by_head[chosen][split_key][0]
        return {(str(d)[:10], str(t)): calibrate_probability(p, calibration) for d, t, p in zip(scored["date"], scored["ticker"], scored["head"])
                if p == p}

    base = ctx.score(ctx.adopted["config"], mode="as_live", memo_tag="l2")
    merged_map = {**probability_map("validation"), **probability_map("backtest")}
    stage = {"heads": heads, "chosen_head": chosen, "variants": {}}
    for name, params in L2_VARIANTS.items():
        # the overlay reads (date, ticker) -> calibrated probability; one map per split is merged (dates never overlap)
        overlay = {**params, "calibration": None, "probabilities": merged_map}
        result = ctx.score(ctx.adopted["config"], mode="as_live", overlay=overlay, memo_tag=f"l2-{name}-{chosen}")
        verdict = verdict_as_live(base, result)
        checks = l2_checks(base, result)
        stage["variants"][name] = {"params": params, "scores": result, "verdict": verdict, "extra_checks": checks,
                                   "passes": verdict["passes"] and all_pass(checks)}
    winners = [n for n, v in stage["variants"].items() if v["passes"]]
    stage["adopted"] = best_by_backtest(winners, {n: stage["variants"][n]["scores"] for n in winners})
    if stage["adopted"]:
        ctx.adopted["direction_overlay"] = {"head": chosen, "calibration": calibration, **L2_VARIANTS[stage["adopted"]]}
        ctx.adopted["needs_live_path"].append("direction_overlay")
    stage["base"] = base
    return stage


def stage_l3(ctx: Research) -> dict:
    base = ctx.score(ctx.adopted["config"], mode="as_live", memo_tag="l3")
    stage = {"base": base, "budgets": {}}
    for name, changes in LEGACY_VARIANTS.items():
        merged = {**ctx.adopted["config"], **changes}
        result = ctx.score(merged, mode="as_live", memo_tag="l3")
        verdict = verdict_as_live(base, result)
        extra = l3_budget_checks(verdict, result, name)
        stage["budgets"][name] = {"changes": changes, "scores": result, "verdict": verdict, "extra_checks": extra,
                                  "passes": verdict["passes"] and all_pass(extra)}
    winners = [n for n, v in stage["budgets"].items() if v["passes"]]
    stage["budget_adopted"] = best_by_backtest(winners, {n: stage["budgets"][n]["scores"] for n in winners})
    if stage["budget_adopted"]:
        ctx.adopted["config"].update(LEGACY_VARIANTS[stage["budget_adopted"]])
    stage["ic_by_class_and_regime"] = legacy_ic_report(ctx)
    stage["model"] = model_stage(ctx, base)
    return stage


def legacy_ic_report(ctx: Research) -> dict:
    """(c) IC of the legacy score against rank_20d's by asset class and by regime bucket, both splits."""
    from evaluation.gate_audit import daily_rank_ic
    from as_live_levers import LEGACY_PROBABILITY_COLUMN

    out = {}
    for split in SPLITS:
        harness, _t, _c = ctx.harness(split)
        frame = main_group_frame(harness)
        frame = frame.assign(cls=[harness.asset_class_by_ticker.get(str(t), "other") for t in frame["ticker"]])
        regime_columns = [c for c in frame.columns if c.startswith("regime_trend_")]
        if regime_columns:
            frame = frame.assign(regime=frame[regime_columns].idxmax(axis=1).str.replace("regime_trend_", "", regex=False))
        rows = {}
        for group_column in ("cls", "regime"):
            if group_column not in frame.columns:
                continue
            for name, part in frame.groupby(group_column):
                legacy = daily_rank_ic(part, score_column=LEGACY_PROBABILITY_COLUMN, target_column="target_rank_20d")
                rank = daily_rank_ic(part, score_column="live_rank_score", target_column="target_rank_20d")
                rows[f"{group_column}:{name}"] = {
                    "legacy_ic": statistics.fmean(legacy.values()) if legacy else None,
                    "rank_20d_ic": statistics.fmean(rank.values()) if rank else None, "dates": len(rank)}
        out[split] = rows
    return out


def model_stage(ctx: Research, base: dict) -> dict:
    """(b) the legacy-as-input candidate, scored against the installed models with the yardstick fixed at 0.034."""
    candidates = ctx.args.candidates_spec or {}
    name = "v640_leg"
    if name not in candidates or not ctx.args.model_ic_data:
        return {"skipped": "no candidate / model_ic supplied"}
    model_ic = copy.deepcopy(ctx.args.model_ic_data)
    model_ic["bootstrap"] = {key: {"yardstick": MODEL_YARDSTICK} for key in ("decision_rank_20d", "decision_rank_20d_swapped_priority")}
    ic_checks = model10_checks(model_ic, name)
    if not candidates[name].get("ml_dir"):
        return {"ic_checks": ic_checks, "adopted": False, "reason": "the IC clauses failed, so no candidate directory was built"}
    result = ctx.score(ctx.adopted["config"], mode="as_live", model=name, memo_tag="l3-model")
    verdict = verdict_as_live(base, result)
    checks = l3_model_checks(ic_checks, verdict, candidates[name].get("latency_ratio"))
    stage = {"ic_checks": ic_checks, "scores": result, "verdict": verdict, "checks": checks, "adopted": all_pass(checks)}
    if stage["adopted"]:
        ctx.adopted["model"] = name
        ctx.adopted["needs_live_path"].append("legacy_input")
    return stage


def stage_l4(ctx: Research) -> dict:
    base = ctx.score(ctx.adopted["config"], patch=ctx.adopted["patch"], mode="as_live", extras=("equity",), memo_tag="l4")
    stage = {"base": base, "variants": {}}
    for name, variant in L4_VARIANTS.items():
        changes = {**ctx.adopted["config"], **variant["changes"]}
        patch = {**ctx.adopted["patch"], **variant["patch"]}
        result = ctx.score(changes, patch=patch, mode="as_live", extras=("equity",), memo_tag="l4")
        verdict = verdict_as_live(base, result)
        ic = {s: {"base": equity_engaged_ic(ctx, s, ctx.adopted["config"], ctx.adopted["patch"]),
                  "variant": equity_engaged_ic(ctx, s, changes, patch)} for s in SPLITS}
        stage["variants"][name] = {"changes": variant["changes"], "patch": variant["patch"], "scores": result, "verdict": verdict,
                                   "engaged_equity_ic": ic}
    # the holdout veto is read once, for the leading candidate only
    screened = [n for n, v in stage["variants"].items()
                if v["verdict"]["backtest_gain"] >= L4_NON_INFERIOR and v["verdict"]["validation_change"] >= L4_NON_INFERIOR]
    leader = best_by_backtest(screened, {n: stage["variants"][n]["scores"] for n in screened})
    holdout_loss = None
    if leader:
        variant = L4_VARIANTS[leader]
        base_hold = ctx.score(ctx.adopted["config"], patch=ctx.adopted["patch"], specs={"holdout": "holdout"}, mode="as_live", memo_tag="l4h")
        var_hold = ctx.score({**ctx.adopted["config"], **variant["changes"]}, patch={**ctx.adopted["patch"], **variant["patch"]},
                             specs={"holdout": "holdout"}, mode="as_live", memo_tag="l4h")
        holdout_loss = base_hold["holdout"]["median_net_sharpe"] - var_hold["holdout"]["median_net_sharpe"]
        ctx.log_holdout_read("l4", f"holdout as-live Sharpe of {leader} against the base (veto clause)")
    for name, entry in stage["variants"].items():
        entry["extra_checks"] = l4_checks(base, entry["scores"], entry["verdict"], entry["engaged_equity_ic"],
                                          holdout_loss if name == leader else None)
        entry["passes"] = all_pass(entry["extra_checks"])
    winners = [n for n, v in stage["variants"].items() if v["passes"]]
    stage["adopted"] = best_by_backtest(winners, {n: stage["variants"][n]["scores"] for n in winners})
    stage["holdout_loss_of_leader"] = {"variant": leader, "loss": holdout_loss}
    if stage["adopted"]:
        chosen = L4_VARIANTS[stage["adopted"]]
        ctx.adopted["config"].update(chosen["changes"])
        ctx.adopted["patch"].update(chosen["patch"])
    return stage


def stage_l5(ctx: Research) -> dict:
    base = ctx.score(ctx.adopted["config"], patch=ctx.adopted["patch"], mode="as_live", memo_tag="l5")
    stage = {"base": base, "variants": {}}
    for name, changes in L5_VARIANTS.items():
        result = ctx.score({**ctx.adopted["config"], **changes}, patch=ctx.adopted["patch"], mode="as_live", memo_tag="l5")
        verdict = verdict_as_live(base, result)
        checks = l5_checks(base, result)
        stage["variants"][name] = {"changes": changes, "scores": result, "verdict": verdict, "extra_checks": checks,
                                   "passes": verdict["passes"] and all_pass(checks)}
    winners = [n for n, v in stage["variants"].items() if v["passes"]]
    stage["adopted"] = best_by_backtest(winners, {n: stage["variants"][n]["scores"] for n in winners})
    if stage["adopted"]:
        ctx.adopted["config"].update(L5_VARIANTS[stage["adopted"]])
    return stage


def blocked_by_l1(ctx: Research, lead: str) -> dict | None:
    """L6 / L7 ship only if L1 showed the gate protects capital (the owner: structure rules only if L1 shows enough conditional
    edge). When it did not, no variant can ship, so scoring them (hours of Codespace time) cannot change the decision: the lead
    closes by its precondition unless `--score-blocked-stages` asks for the report anyway."""
    if bool(ctx.report.get("l1_pass", False)) or getattr(getattr(ctx, "args", None), "score_blocked", False):
        return None
    return {"skipped": f"{lead} closed by its precondition: L1 found the gate hides weakness (engaged-day IC margin "
                       f"{((ctx.report.get('l1') or {}).get('margins') or {}).get('backtest', {}).get('ic_margin')}), so no variant can ship",
            "l1_precondition": False, "adopted": None}


def stage_l6(ctx: Research) -> dict:
    closed = blocked_by_l1(ctx, "L6")
    if closed is not None:
        return closed
    l1_pass = bool(ctx.report.get("l1_pass", False))
    base = ctx.score(ctx.adopted["config"], patch=ctx.adopted["patch"], mode="ungated", memo_tag="l6")
    stage = {"base": base, "l1_precondition": l1_pass, "variants": {}}
    for name, variant in L6_VARIANTS.items():
        changes = {**ctx.adopted["config"], "portfolio_book.tranche_adjust_fraction": variant["adjust"]}
        result = ctx.score(changes, patch=ctx.adopted["patch"], tranches=variant["tranches"], mode="ungated", memo_tag="l6")
        as_live = ctx.score(changes, patch=ctx.adopted["patch"], tranches=variant["tranches"], mode="as_live", memo_tag="l6")
        checks = l6_checks(base, result, l1_pass)
        stage["variants"][name] = {"params": variant, "scores": result, "as_live_scores": as_live, "extra_checks": checks,
                                   "passes": all_pass(checks)}
    winners = [n for n, v in stage["variants"].items() if v["passes"]]
    stage["adopted"] = best_by_backtest(winners, {n: stage["variants"][n]["scores"] for n in winners})
    if stage["adopted"]:
        ctx.adopted["tranches"] = L6_VARIANTS[stage["adopted"]]["tranches"]
        ctx.adopted["adjust_fraction"] = L6_VARIANTS[stage["adopted"]]["adjust"]
        ctx.adopted["needs_live_path"].append("tranches")
    return stage


def false_lock_summary(summary: dict, unlocked: dict) -> dict:
    """Attach per-phase false-lock shares to a score (needs `returns`-extras and the unlocked book's returns by split/phase)."""
    from evaluation.kill_switch_replay import false_lock_share, forward_window_returns

    for split, entry in summary.items():
        shares = []
        for locked, returns in zip(entry["locked_dates_lists"], unlocked[split]):
            share = false_lock_share(locked, forward_window_returns(returns))
            if share is not None:
                shares.append(share)
        entry["false_lock_share_by_phase"] = shares
        if shares:
            entry["false_lock_share_median"] = statistics.median(shares)
    return summary


def stage_l7(ctx: Research) -> dict:
    closed = blocked_by_l1(ctx, "L7")
    if closed is not None:
        return closed
    l1_pass = bool(ctx.report.get("l1_pass", False))
    off = {**ctx.adopted["config"], "risk.kill_switch.enabled": False}
    unlocked_scores = ctx.score(off, patch=ctx.adopted["patch"], mode="as_live", extras=("returns",), memo_tag="l7-unlocked")
    unlocked = {split: entry["returns_by_phase"] for split, entry in unlocked_scores.items()}
    base = false_lock_summary(ctx.score(ctx.adopted["config"], patch=ctx.adopted["patch"], mode="as_live", extras=("returns",),
                                        stability=True, memo_tag="l7"), unlocked)
    stage = {"base": {s: {k: v for k, v in e.items() if k not in ("returns_by_phase", "locked_dates_lists")} for s, e in base.items()},
             "l1_precondition": l1_pass, "variants": {}}
    base_stability = base["backtest"]["stability_jaccard_median"]
    for name, changes in L7_VARIANTS.items():
        result = false_lock_summary(
            ctx.score({**ctx.adopted["config"], **changes}, patch=ctx.adopted["patch"], mode="as_live", extras=("returns",),
                      stability=True, memo_tag="l7"), unlocked)
        stability = result["backtest"]["stability_jaccard_median"]
        checks = l7_checks(base, result, base_stability, stability, l1_pass)
        stage["variants"][name] = {"changes": changes, "stability": stability, "extra_checks": checks, "passes": all_pass(checks),
                                   "scores": {s: {k: v for k, v in e.items() if k not in ("returns_by_phase", "locked_dates_lists")}
                                              for s, e in result.items()}}
    winners = [n for n, v in stage["variants"].items() if v["passes"]]
    chosen = min(winners, key=lambda n: statistics.median(
        [stage["variants"][n]["scores"][s]["false_lock_share_median"] for s in SPLITS])) if winners else None
    stage["adopted"] = chosen
    if chosen:
        ctx.adopted["config"].update(L7_VARIANTS[chosen])
    stage["base_stability"] = base_stability
    return stage


def stage_l9(ctx: Research) -> dict:
    from evaluation.trade_bootstrap import (bootstrap_mean_pnl, leave_one_name_out, pnl_by_name, repeatable,
                                            round_trips_from_closed_trades, top_k_share)

    harness, _t, _c = ctx.harness("backtest", patch=ctx.adopted["patch"])
    core = {"BTCUSD", "LTCUSD"}
    crypto = sorted(t for t, kind in harness.asset_class_by_ticker.items() if kind == "crypto")
    eligible = {t for t in crypto if harness.metadata[t]["trading_eligible"]}
    graduates = sorted(eligible - core)
    stage: dict = {"graduates": graduates}
    # (1) the Lean run's own crypto round trips
    if ctx.args.lean_run:
        from evaluation.backtest_audit import load_backtest_run

        run = load_backtest_run(ROOT_DIR / ctx.args.lean_run)
        groups = {"core": round_trips_from_closed_trades(run, core), "graduates": round_trips_from_closed_trades(run, set(graduates))}
        stage["lean_trades"] = {
            name: {"bootstrap": bootstrap_mean_pnl([t["pnl"] for t in trades]), "top1_share": top_k_share([t["pnl"] for t in trades], 1),
                   "top3_share": top_k_share([t["pnl"] for t in trades], 3), "pnl_by_name": pnl_by_name(trades),
                   "leave_one_name_out": leave_one_name_out(pnl_by_name(trades)), "n": len(trades)}
            for name, trades in groups.items()
        }
        core_stats = stage["lean_trades"]["core"]
        stage["core_repeatable"] = repeatable(core_stats["bootstrap"], core_stats["leave_one_name_out"])
    # (2) graduates on vs off, as-live
    on = ctx.score(ctx.adopted["config"], patch=ctx.adopted["patch"], mode="as_live", memo_tag="l9")
    off = ctx.score(ctx.adopted["config"], patch=ctx.adopted["patch"], mode="as_live", eligible_override=core & eligible, memo_tag="l9-g0")
    stage.update(graduates_on=on, graduates_off=off, decision=l9_decision(on, off))
    # (3) leave-one-name-out over the crypto names, as-live (reduced phases)
    stage["leave_one_out"] = {}
    for ticker in sorted(eligible):
        result = ctx.score(ctx.adopted["config"], patch=ctx.adopted["patch"], mode="as_live", eligible_override=eligible - {ticker},
                           phases=LOO_PHASES, memo_tag=f"l9-loo-{ticker}")
        stage["leave_one_out"][ticker] = {s: result[s]["median_net_sharpe"] for s in SPLITS}
    if not stage["decision"]["keep_graduates"]:
        ctx.adopted["graduates_off"] = True
        ctx.adopted["config"]["class_weight_caps.crypto.core_only"] = True  # live and offline: only the core names are candidates
    return stage


def stage_l10(ctx: Research) -> dict:
    base = ctx.score(ctx.adopted["config"], patch=ctx.adopted["patch"], mode="as_live", memo_tag="l10")
    stage = {"base": base, "variants": {}}
    for name, heads in L10_VARIANTS.items():
        patch = {**ctx.adopted["patch"], "phase_v2.rank_signal.heads": heads, "phase_v2.rank_signal.demoted": [],
                 "phase_v2.rank_signal.demote_not_promotable_heads": False}
        result = ctx.score(ctx.adopted["config"], patch=patch, mode="as_live", memo_tag="l10")
        verdict = verdict_as_live(base, result)
        shift = factor_shift(ctx, patch)
        checks = l10_checks(verdict, shift)
        stage["variants"][name] = {"heads": heads, "scores": result, "verdict": verdict, "factor_shift": shift, "extra_checks": checks,
                                   "passes": all_pass(checks)}
    winners = [n for n, v in stage["variants"].items() if v["passes"]]
    stage["adopted"] = best_by_backtest(winners, {n: stage["variants"][n]["scores"] for n in winners})
    if stage["adopted"]:
        ctx.adopted["patch"]["phase_v2.rank_signal.heads"] = L10_VARIANTS[stage["adopted"]]
        ctx.adopted["patch"]["phase_v2.rank_signal.demoted"] = []
        ctx.adopted["patch"]["phase_v2.rank_signal.demote_not_promotable_heads"] = False
    return stage


def factor_shift(ctx: Research, patch: dict) -> dict:
    """Change in the book's market and momentum loadings (`compute_book_factor_exposure`: the daily net returns of one
    as-live run, phase 0, regressed on SPY and a 20-day momentum factor) when the head blend changes."""
    from lean_calibration import calibrated_overrides

    from evaluation.benchmark_comparison import close_pivot_from_frame
    from evaluation.factor_neutralization_check import compute_book_factor_exposure

    loadings = {}
    for label, patched in (("base", ctx.adopted["patch"]), ("variant", patch)):
        harness, _topology, config = ctx.harness("backtest", patch=patched)
        merged = apply_dotted(config, ctx.adopted["config"])
        result = harness.as_live(config_overrides=ctx.adopted["config"] or None,
                                 **{**calibrated_overrides(harness, phase=0), **harness.v610_mechanisms(merged)})
        report = compute_book_factor_exposure(result.per_date, result.per_date_net_return, close_pivot_from_frame(harness.frame))
        loadings[label] = (report.get("loadings") or {}) if report.get("status") == "OK" else {}
    return {name: loadings["variant"].get(name, 0.0) - loadings["base"].get(name, 0.0) for name in ("market", "momentum")}


STAGES = {
    "dedupe": stage_dedupe, "l1": stage_l1, "l8": stage_l8, "l2": stage_l2, "l3": stage_l3, "l4": stage_l4, "l5": stage_l5,
    "l6": stage_l6, "l7": stage_l7, "l9": stage_l9, "l10": stage_l10,
}


def apply_smoke() -> None:
    """--smoke: one variant per stage and two phases, so every code path runs end to end in minutes before the real chain."""
    for table in (L2_VARIANTS, LEGACY_VARIANTS, L4_VARIANTS, L5_VARIANTS, L6_VARIANTS, L7_VARIANTS, L10_VARIANTS):
        for name in list(table)[1:]:
            del table[name]
    global LOO_PHASES
    LOO_PHASES = 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=str(ROOT_DIR / "ml" / "datasets" / "full_dataset.csv"))
    parser.add_argument("--legacy-probability", required=True)
    parser.add_argument("--legacy-components", default=str(ROOT_DIR / "ml" / "datasets" / "legacy_components.csv"))
    parser.add_argument("--candidates", default=None)
    parser.add_argument("--model-ic", default=None)
    parser.add_argument("--lean-run", default=None, help="the Lean run whose closed trades L9 bootstraps (relative to the repo)")
    parser.add_argument("--stages", nargs="*", default=list(STAGES))
    parser.add_argument("--max-phases", type=int, default=10)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--gate-warmup-days", type=int, default=400)
    parser.add_argument("--score-blocked-stages", dest="score_blocked", action="store_true",
                        help="score L6 / L7 even when L1 failed (they cannot ship then; a report only)")
    parser.add_argument("--smoke", action="store_true", help="one variant per stage, 2 phases, 1 crypto leave-one-out: a code-path check")
    parser.add_argument("--out", default=str(ROOT_DIR / "ml" / "evaluation" / "v640" / "research.json"))
    parser.add_argument("--adopted-config-out", default=str(ROOT_DIR / "ml" / "evaluation" / "v640" / "adopted_changes.json"))
    args = parser.parse_args()
    if args.smoke:
        apply_smoke()
        args.max_phases = min(args.max_phases, 2)
    args.candidates_spec = json.loads(Path(args.candidates).read_text(encoding="utf-8")) if args.candidates and Path(args.candidates).exists() else {}
    args.model_ic_data = json.loads(Path(args.model_ic).read_text(encoding="utf-8")) if args.model_ic and Path(args.model_ic).exists() else None

    base_config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    out_path = Path(args.out)
    report = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    report.update({"max_phases": args.max_phases, "sweep_in_rule_scores": False})
    ctx = Research(args, base_config, report, out_path)
    for name in args.stages:
        print(f"=== stage {name}", flush=True)
        stage = STAGES[name](ctx)
        report[name] = stage
        ctx.save()
        print(f"  {name}: adopted={stage.get('adopted', stage.get('budget_adopted', stage.get('decision')))}", flush=True)
    Path(args.adopted_config_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.adopted_config_out).write_text(json.dumps(ctx.adopted, indent=1), encoding="utf-8")
    print("adopted:", json.dumps(ctx.adopted))
    print(f"written {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
