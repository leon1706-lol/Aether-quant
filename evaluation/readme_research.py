"""README builders for the as-live book and the V5.8.0 research / audit results.

`generate_evaluation_report.update_readme_evaluation_sections()` calls these; each takes the directory the JSON reports
live in and returns markdown, degrading to a "not run yet" line when its inputs are missing, so the README never shows a
half-built table. Pure: reads JSON, no model, no network.

Sources (all written by `aq evaluate ...` or the research scripts):
    rank_book_simulation_as_live_<split>.json   aq evaluate --rank-book --as-live --split <split>
    class_sleeve_research_{forex,bond}.json     scripts/class_sleeve_research.py
    crypto_graduation_research.json             scripts/crypto_graduation_research.py
    rl_sizing_research.json                     scripts/rl_sizing_research.py
    class_ic_audit_<split>.json                 aq evaluate --ic-by-class
    gate_audit_<split>.json                     aq evaluate --audit-gates
    head_audit.json                             aq evaluate --audit-heads
    holdout_report.json                         scripts/holdout_report.py
    lean_decision_overrides.json                a Lean run that overruled an offline branch (label -> branch, shipped, reason)
    v600/forex_research.json, v600/crypto_research.json   the V6.0.0 rule decisions (R-FX6, R-CRYPTO); the shipped setting
                                                is read from config.json, never typed here
    v610/calibration.json, v610/research.json   V6.1.0: R-CAL2 and the rule chain (model, head, book, legacy, gate)
    v630/calibration.json, v630/research.json   V6.3.0: R-CAL3 (replaces R-CAL2's table) and R-KILL / R-STAGGER2 / R-GATE3
    v640/research.json                          V6.4.0: R-DEDUPE2 and leads L1-L10
"""

from __future__ import annotations

import json
from pathlib import Path

SPLITS = ("validation", "backtest")
AS_LIVE_MARKER_START = "<!-- AQ:ASLIVE_START -->"
AS_LIVE_MARKER_END = "<!-- AQ:ASLIVE_END -->"
RESEARCH_MARKER_START = "<!-- AQ:RESEARCH_START -->"
RESEARCH_MARKER_END = "<!-- AQ:RESEARCH_END -->"
LEAN_COMPARE_MARKER_START = "<!-- AQ:LEANCMP_START -->"
LEAN_COMPARE_MARKER_END = "<!-- AQ:LEANCMP_END -->"


def load_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _num(value: object, spec: str = "+.3f") -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return "n/a"
    return format(value, spec)


def _pct(value: object, spec: str = "+.2f") -> str:
    return "n/a" if _num(value) == "n/a" else f"{format(float(value) * 100.0, spec)}%"  # type: ignore[arg-type]


def _per_split(evaluation_dir: Path, stem: str) -> dict[str, dict | None]:
    """`<stem>_<split>.json` per split; the legacy un-suffixed file stands in for the split it names (its `split` key)."""
    reports: dict[str, dict | None] = {split: load_json(evaluation_dir / f"{stem}_{split}.json") for split in SPLITS}
    legacy = load_json(evaluation_dir / f"{stem}.json")
    if isinstance(legacy, dict):
        named = legacy.get("split")
        if named in reports and reports[named] is None:
            reports[named] = legacy
    return {split: report if isinstance(report, dict) else None for split, report in reports.items()}


def build_as_live_markdown(evaluation_dir: Path) -> str:
    reports = _per_split(evaluation_dir, "rank_book_simulation_as_live")
    legacy = load_json(evaluation_dir / "rank_book_simulation_as_live.json")
    if not any(reports.values()) and isinstance(legacy, dict):
        reports = {"older run, split not recorded": legacy}
    if not any(reports.values()):
        return "_Not run yet: `aq evaluate --rank-book --as-live --split validation` and `--split backtest`._"
    rows = [
        "| Split | Idealized Sharpe | **As-live Sharpe** | As-live net return | Max drawdown | Rebalances (vetoed) | With impact model |",
        "|---|---|---|---|---|---|---|",
    ]
    for split, report in reports.items():
        if not report:
            rows.append(f"| {split} | not run | | | | | |")
            continue
        live = report.get("as_live") or {}
        impact = report.get("as_live_with_impact_model") or {}
        rows.append(
            f"| {split} | {_num(report.get('idealized_net_sharpe'))} | **{_num(live.get('net_sharpe'))}** | "
            f"{_pct(live.get('net_total_return'))} | {_pct(live.get('net_max_drawdown'), '.2f')} | "
            f"{live.get('num_rebalances', 'n/a')} ({live.get('num_vetoed_rebalances', 'n/a')}) | {_num(impact.get('net_sharpe'))} |"
        )
    return (
        "The offline book run through the same decision functions as `main.py` (blended head, rank groups, spread / rolling-IC "
        "gates, kill switch, hysteresis, class sleeves and caps, one-bar lag). Sharpe subtracts no risk-free rate, and a "
        "split with few engaged rebalances is a thin estimate.\n\n" + "\n".join(rows)
    )


def _sleeve_row(label: str, research: dict | None, minimum_setting: str, override: dict | None = None) -> str | None:
    if not research:
        return None
    decision = research.get("decision") or {}
    variant = decision.get("variant")
    entry = (research.get("grid") or {}).get(variant) if variant else None
    branch = decision.get("branch", "n/a")
    shipped = variant if branch == "edge_pass" else f"{minimum_setting} (minimum cap; best effort: {variant})"
    if isinstance(override, dict) and override.get("branch") and override.get("shipped"):
        branch = f"{override['branch']} (offline: {branch})"
        shipped = str(override["shipped"])
    return (
        f"| {label} | {branch} | {shipped} | {_num(((entry or {}).get('validation') or {}).get('net_sharpe'))} | "
        f"{_num(((entry or {}).get('backtest') or {}).get('net_sharpe'))} | {_num((entry or {}).get('combined_backtest_drop'))} |"
    )


def _config_for(evaluation_dir: Path) -> dict:
    config = load_json(evaluation_dir.parent.parent / "config.json")
    return config if isinstance(config, dict) else {}


def _forex_row_v6(evaluation_dir: Path, config: dict) -> str | None:
    """R-FX6 (V6.0.0): the forex sleeve is dropped when none of the grid is positive on the backtest split."""
    research = load_json(evaluation_dir / "v600" / "forex_research.json")
    if not isinstance(research, dict) or not config:
        return None
    decision = research.get("decision") or {}
    best = (research.get("grid") or {}).get(decision.get("best_validation_variant")) or {}
    enabled = bool((config.get("phase_v2", {}).get("forex_risk") or {}).get("enabled", False))
    shipped = "sleeve on (see config.json `forex_sleeve`)" if enabled else "off (`forex_risk.enabled` false; forex stays a feature class)"
    return (
        f"| Forex sleeve | R-FX6: {decision.get('branch', 'n/a')} | {shipped} | {_num((best.get('validation') or {}).get('net_sharpe'))} | "
        f"{_num((best.get('backtest') or {}).get('net_sharpe'))} | n/a |"
    )


def _crypto_row_v6(evaluation_dir: Path, config: dict) -> str | None:
    """R-CRYPTO (V6.0.0): limit exits, a route-aware fee and smaller graduates; the caps shown are the shipped ones."""
    research = load_json(evaluation_dir / "v600" / "crypto_research.json")
    if not isinstance(research, dict) or not config:
        return None
    decision = research.get("decision") or {}
    winner = (research.get("results") or {}).get(decision.get("winner")) or {}
    caps = ((config.get("phase_v2", {}).get("class_weight_caps") or {}).get("crypto")) or {}
    limits = config.get("phase_v2", {}).get("limit_orders", {})
    exits = ", ".join(limits.get("exit_asset_classes") or []) or "none"
    shipped = f"per-name {caps.get('per_name_cap', 'n/a')}, class gross {caps.get('class_gross_cap', 'n/a')}; limit exits for {exits}"
    return (
        f"| Crypto graduates and fees | R-CRYPTO: {decision.get('winner', 'n/a')} | {shipped} | "
        f"{_num((winner.get('validation') or {}).get('total_sharpe'))} | {_num((winner.get('backtest') or {}).get('total_sharpe'))} | n/a |"
    )


def _calibration_line(evaluation_dir: Path) -> str:
    # V6.3.0: R-CAL3 (R-CAL2's clauses on V6.2.0's BT2) supersedes R-CAL2 once it exists.
    rule, report = "R-CAL3", load_json(evaluation_dir / "v630" / "calibration.json")
    if not isinstance(report, dict) or not isinstance(report.get("verdict"), dict):
        rule, report = "R-CAL2", load_json(evaluation_dir / "v610" / "calibration.json")
    verdict = (report or {}).get("verdict") if isinstance(report, dict) else None
    if not isinstance(verdict, dict):
        return "_Not run yet: `python scripts/lean_calibration.py --rcal2` (rule R-CAL2)._"
    variant = verdict.get("variant", "v610")
    cells = []
    for name, window in ((report or {}).get("windows") or {}).items():
        row = (window.get("variants") or {}).get(variant) or {}
        cells.append(
            f"| {name} | {_num(row.get('daily_correlation'), '.2f')} | {_pct(row.get('annual_return_gap'), '+.1f')} | "
            f"{_pct(row.get('decision_agreement'), '.0f')} | {'pass' if (verdict.get('per_window') or {}).get(name) else 'fail'} |"
        )
    thresholds = verdict.get("thresholds") or {}
    return (
        f"Rule {rule} (daily correlation >= {_num(thresholds.get('min_correlation'), '.2f')}, annual return gap <= "
        f"{_pct(thresholds.get('max_annual_gap'), '.0f')}, rebalance-decision agreement >= "
        f"{_pct(thresholds.get('min_decision_agreement'), '.0f')} on every window): **branch {verdict.get('branch', '?')}** "
        f"({'calibrated' if verdict.get('calibrated') else 'not calibrated'}).\n\n"
        "| Window | Daily correlation | Return gap (annual) | Decision agreement | Verdict |\n|---|---|---|---|---|\n"
        + "\n".join(cells)
    )


def _rule_chain_lines(evaluation_dir: Path) -> list[str]:
    report = load_json(evaluation_dir / "v610" / "research.json")
    if not isinstance(report, dict):
        return ["_Not run yet: `python scripts/v610_research.py` (rules R-MODEL9, R-HEAD2, R-BOOK2, R-LEGACY, R-GATE)._"]
    rows = []
    for stage in ("model", "head", "book", "costs", "legacy", "gate"):
        entry = report.get(stage)
        if not isinstance(entry, dict):
            continue
        if "skipped" in entry:
            rows.append(f"| {stage} | skipped | {entry['skipped']} |")
            continue
        variants = entry.get("variants") or {}
        adopted = entry.get("adopted")
        detail = []
        for name, value in variants.items():
            if "skipped" in value:
                detail.append(f"{name} skipped ({value['skipped']})")
                continue
            verdict = (value.get("verdict") or {}).get("ungated") or {}
            detail.append(f"{name} {_num(verdict.get('backtest_gain'), '+.3f')}")
        rows.append(f"| {stage} | {adopted or 'none (incumbent stays)'} | {', '.join(detail) or 'n/a'} |")
    if not rows:
        return ["_Rule chain has no stage results yet._"]
    return ["| Stage | Adopted | Backtest-Sharpe gain per variant (median over rebalance phases) |", "|---|---|---|", *rows]


def _rule_chain_v620_lines(evaluation_dir: Path) -> list[str]:
    """V6.2.0's chain (v620/research.json): R-DEDUPE on the gated book, R-STAGGER and R-MODEL10 on the ungated one."""
    report = load_json(evaluation_dir / "v620" / "research.json")
    if not isinstance(report, dict):
        return ["_Not run yet: `python scripts/v620_research.py` (rules R-DEDUPE, R-STAGGER, R-MODEL10)._"]
    rows = []
    dedupe = report.get("dedupe")
    if isinstance(dedupe, dict):
        verdict = dedupe.get("verdict") or {}
        rows.append(f"| R-DEDUPE (crypto counted once in the gate) | {'adopted' if dedupe.get('adopted') else 'none (double count stays)'} "
                    f"| once: backtest {_num(verdict.get('backtest_gain'))}, validation {_num(verdict.get('validation_change'))} (gated) |")
    stagger = report.get("stagger")
    if isinstance(stagger, dict):
        detail = []
        for name, value in (stagger.get("variants") or {}).items():
            verdict = value.get("verdict") or {}
            failed = [key for key, ok in {**verdict.get("checks", {}), **verdict.get("extra_checks", {})}.items() if not ok]
            detail.append(f"{name}: backtest {_num(verdict.get('backtest_gain'))}, validation {_num(verdict.get('validation_change'))}"
                          + (f" (fails {', '.join(failed)})" if failed else ""))
        rows.append(f"| R-STAGGER (tranche book) | {stagger.get('adopted') or 'none (one book stays)'} | {'; '.join(detail) or 'n/a'} |")
    model = report.get("model")
    if isinstance(model, dict):
        skipped = [name for name, value in (model.get("variants") or {}).items() if "skipped" in value]
        rows.append(f"| R-MODEL10 (regularised ensembles) | {model.get('adopted') or 'none (installed models stay)'} "
                    f"| {len(skipped)} candidates fail the IC clauses (yardstick: resampled control ensembles) |")
    if not rows:
        return ["_V6.2.0 rule chain has no stage results yet._"]
    return ["| Rule | Adopted | Median-Sharpe change per variant (every rebalance phase) |", "|---|---|---|", *rows]


def _failed(verdict: dict, extra: dict | None = None) -> list[str]:
    return [key for key, ok in {**(verdict.get("checks") or {}), **(extra or {})}.items() if not ok]


def _rule_chain_v630_lines(evaluation_dir: Path) -> list[str]:
    """V6.3.0's chain (v630/research.json): R-KILL and R-STAGGER2 ungated, R-GATE3 as-live only on R-CAL3 branch A."""
    report = load_json(evaluation_dir / "v630" / "research.json")
    if not isinstance(report, dict):
        return ["_Not run yet: `python scripts/v630_research.py` (rules R-KILL, R-STAGGER2, R-GATE3)._"]
    rows = []
    kill = report.get("kill")
    if isinstance(kill, dict):
        detail = []
        for name, value in (kill.get("variants") or {}).items():
            verdict = value.get("verdict") or {}
            failed = _failed(verdict, value.get("extra_checks"))
            detail.append(f"{name}: backtest {_num(verdict.get('backtest_gain'))}, validation {_num(verdict.get('validation_change'))}, "
                          f"lock stability {_num(value.get('stability'), '.2f')}" + (f" (fails {', '.join(failed)})" if failed else ""))
        base = ((kill.get("base") or {}).get("backtest") or {}).get("stability_jaccard_median")
        rows.append(f"| R-KILL (kill-switch window / release band; KS0 lock stability {_num(base, '.2f')}) | branch {kill.get('branch', '?')}: "
                    f"{kill.get('adopted') or 'none (KS0 stays)'} | {'; '.join(detail) or 'n/a'} |")
    stagger = report.get("stagger")
    if isinstance(stagger, dict):
        verdict = stagger.get("verdict") or {}
        failed = _failed(verdict, stagger.get("extra_checks"))
        rows.append(f"| R-STAGGER2 (S2, second look) | {'S2' if stagger.get('adopted') else 'none (one book stays)'} | backtest "
                    f"{_num(verdict.get('backtest_gain'))}, validation {_num(verdict.get('validation_change'))}"
                    + (f" (fails {', '.join(failed)})" if failed else "") + " |")
    gates = report.get("gates")
    if isinstance(gates, dict):
        if "skipped" in gates:
            rows.append(f"| R-GATE3 (rolling-IC floor / window) | skipped | {gates['skipped']} |")
        else:
            detail = [f"{name} {_num((value.get('verdict') or {}).get('backtest_gain'))}" for name, value in (gates.get("variants") or {}).items()]
            rows.append(f"| R-GATE3 (rolling-IC floor / window) | {gates.get('adopted') or 'none (gate stays)'} | {', '.join(detail)} |")
    if not rows:
        return ["_V6.3.0 rule chain has no stage results yet._"]
    return ["| Rule | Adopted | Median-Sharpe change per variant (every rebalance phase) |", "|---|---|---|", *rows]


def _rule_chain_v640_lines(evaluation_dir: Path) -> list[str]:
    """V6.4.0's chain (v640/research.json): one row per lead (R-DEDUPE2, L2-L10); L1 has its own table below."""
    report = load_json(evaluation_dir / "v640" / "research.json")
    if not isinstance(report, dict):
        return ["_Not run yet: `python scripts/v640_research.py` (leads L1-L10, R-DEDUPE2)._"]
    rows = []

    def verdict_text(entry: dict) -> str:
        verdict = entry.get("verdict") or {}
        failed = _failed(verdict, entry.get("extra_checks") or entry.get("checks"))
        gain = f"backtest {_num(verdict.get('backtest_gain'))}, validation {_num(verdict.get('validation_change'))}" if verdict else "n/a"
        return gain + (f" (fails {', '.join(failed)})" if failed else "")

    def add(label: str, stage, variants_key: str = "variants", adopted_key: str = "adopted", none_text: str = "none (unchanged)"):
        if not isinstance(stage, dict) or variants_key not in stage:
            return
        detail = [f"{name}: {verdict_text(value)}" for name, value in (stage.get(variants_key) or {}).items()]
        rows.append(f"| {label} | {stage.get(adopted_key) or none_text} | {'; '.join(detail) or 'n/a'} |")

    dedupe = report.get("dedupe")
    if isinstance(dedupe, dict):
        rows.append(f"| R-DEDUPE2 (crypto counted once in the gate; validation + backtest + holdout span) | "
                    f"{'once' if dedupe.get('adopted') else 'none (twice stays)'} | {verdict_text({'verdict': dedupe.get('verdict')})} |")
    add("L2 direction overlay (calibrated on validation)", report.get("l2"), none_text="none (direction = diagnostic only)")
    l3 = report.get("l3")
    if isinstance(l3, dict):
        add("L3a legacy budget", l3, "budgets", "budget_adopted", "none (0.05 / 0.02 stays)")
        model = l3.get("model") or {}
        if isinstance(model, dict) and ("checks" in model or "reason" in model or "skipped" in model):
            failed = [key for key, ok in (model.get("checks") or {}).items() if not ok]
            rows.append(f"| L3b legacy as a model input (yardstick 0.034) | {'v640_leg' if model.get('adopted') else 'none (models unchanged)'} | "
                        f"{model.get('reason') or model.get('skipped') or ('fails ' + ', '.join(failed) if failed else 'all clauses pass')} |")
    add("L4 within-class ranks", report.get("l4"), none_text="none (pooled equity + crypto ranks stay)")
    add("L5 rebalance / hold grid", report.get("l5"), none_text="none (20 / 40 stays)")
    add("L6 staggered book (phase spread)", report.get("l6"), none_text="none (one book stays)")
    add("L7 kill-switch confirmation", report.get("l7"), none_text="none (KS0 stays)")
    l8 = report.get("l8")
    if isinstance(l8, dict):
        decision = l8.get("decision") or {}
        rows.append(f"| L8 expert ablation (legacy signal) | {', '.join(decision.get('disable') or []) or 'none disabled'} | "
                    f"no contribution on both splits: {', '.join(decision.get('candidates_with_no_contribution') or []) or 'none'}; "
                    f"non-inferior: {decision.get('non_inferior')} |")
    l9 = report.get("l9")
    if isinstance(l9, dict) and "decision" in l9:
        rows.append(f"| L9 crypto graduates against core only | {'graduates kept' if l9['decision'].get('keep_graduates') else 'core only'} | "
                    f"graduates beat core-only: {l9['decision'].get('graduates_beat_core_only_on')} |")
    add("L10 residual head blend", report.get("l10"), none_text="none (rank_20d / rank_5d stay)")
    lean = load_json(evaluation_dir / "v640" / "r_lean13.json")
    if isinstance(lean, dict) and isinstance(lean.get("values"), dict):
        values = lean["values"]
        failed = [name for name, ok in (lean.get("checks") or {}).items() if not ok]
        rows.append(
            f"| R-LEAN13 (Lean confirm of the adopted L5 + L9 changes, run {lean.get('candidate')} against {lean.get('baseline')}) | "
            f"{'kept' if lean.get('keep') else 'reverted'} | strategy Sharpe {_num(values.get('candidate_strategy_sharpe'), '.2f')} against "
            f"{_num(values.get('baseline_strategy_sharpe'), '.2f')}, max drawdown {_pct(values.get('candidate_max_drawdown'), '.2f')} "
            f"against {_pct(values.get('baseline_max_drawdown'), '.2f')}"
            + (f" (fails {', '.join(failed)})" if failed else "") + " |"
        )
    if not rows:
        return ["_V6.4.0 rule chain has no stage results yet._"]
    return ["| Lead | Adopted | Median-Sharpe change per variant (every rebalance phase) |", "|---|---|---|", *rows]


def _l1_lines(evaluation_dir: Path) -> list[str]:
    report = load_json(evaluation_dir / "v640" / "research.json")
    stage = report.get("l1") if isinstance(report, dict) else None
    if not isinstance(stage, dict):
        return ["_Not run yet: stage `l1` of `scripts/v640_research.py`._"]
    rows = ["| Split | Dates engaged / vetoed | IC all | IC engaged | IC margin | Sharpe margin (median over phases) |", "|---|---|---|---|---|---|"]
    for split, skill in (stage.get("skill") or {}).items():
        margins = (stage.get("margins") or {}).get(split) or {}
        rows.append(f"| {split}{' (report only)' if split == 'holdout' else ''} | {skill.get('engaged_dates')} / {skill.get('vetoed_dates')} | "
                    f"{_num((skill.get('all') or {}).get('daily_mean_ic'))} | {_num((skill.get('engaged') or {}).get('daily_mean_ic'))} | "
                    f"{_num(margins.get('ic_margin'))} | {_num(margins.get('sharpe_margin'))} |")
    verdict = stage.get("verdict") or {}
    rows.append("")
    rows.append(f"Bar (+0.02 IC and +0.15 Sharpe on both splits): **{verdict.get('reading', 'n/a')}**.")
    return rows


def _l2_lines(evaluation_dir: Path) -> list[str]:
    report = load_json(evaluation_dir / "v640" / "research.json")
    stage = report.get("l2") if isinstance(report, dict) else None
    if not isinstance(stage, dict) or not stage.get("heads"):
        return ["_Not run yet: stage `l2` of `scripts/v640_research.py`._"]
    rows = ["| Head (direction_20d) | Validation ECE | Log-loss raw -> cross-fitted best | Backtest log-loss raw -> calibrated | Backtest balanced accuracy |",
            "|---|---|---|---|---|"]
    for kind, entry in stage["heads"].items():
        validation = entry.get("validation") or {}
        cross = {k: v for k, v in (validation.get("cross_fitted_log_loss") or {}).items() if v is not None}
        best = min(cross, key=cross.get) if cross else None
        rows.append(f"| {kind}{' (used)' if kind == stage.get('chosen_head') else ''} | {_num(validation.get('ece'), '.4f')} | "
                    f"{_num(validation.get('log_loss'), '.4f')} -> {_num(cross.get(best), '.4f') if best else 'n/a'} ({best or 'n/a'}) | "
                    f"{_num(entry.get('backtest_raw_log_loss'), '.4f')} -> {_num(entry.get('backtest_calibrated_log_loss'), '.4f')} | "
                    f"{_num(entry.get('backtest_balanced_accuracy'), '.3f')} |")
    return rows


def _crypto_row(research: dict | None) -> str | None:
    if not research:
        return None
    decision = research.get("decision") or {}
    config = decision.get("config") or decision.get("best_capped_config")
    results = research.get("results") or {}
    name = f"capped {decision.get('per_name_cap')}/{decision.get('class_gross_cap')}"
    entry = results.get(name) or results.get(config) or {}
    core = results.get("core_only") or {}
    drop = None
    if isinstance(entry.get("backtest"), dict) and isinstance(core.get("backtest"), dict):
        drop = core["backtest"].get("net_sharpe", 0.0) - entry["backtest"].get("net_sharpe", 0.0)
    shipped = f"per-name {decision.get('per_name_cap')}, class gross {decision.get('class_gross_cap')}"
    if decision.get("branch") != "edge_pass":
        shipped += " (minimum cap + loss guard)"
    return (
        f"| Crypto graduates | {decision.get('branch', 'n/a')} | {shipped} | "
        f"{_num((entry.get('validation') or {}).get('net_sharpe'))} | {_num((entry.get('backtest') or {}).get('net_sharpe'))} | {_num(drop)} |"
    )


def _rl_row(research: dict | None) -> str | None:
    if not research:
        return None
    decision = research.get("decision") or {}
    low, high = (decision.get("range") or [None, None])[:2]
    guarded = decision.get("shadow_guard", False)
    sharpe = {}
    for split in SPLITS:
        part = (research.get("splits") or {}).get(split) or {}
        entry = part.get("minimum_range_with_shadow_guard") if guarded else (part.get("ranges") or {}).get(f"{low}-{high}")
        sharpe[split] = (entry or {}).get("sharpe_gain")
    shipped = f"range [{low}, {high}]" + (" + shadow guard" if guarded else "")
    return (
        f"| RL sizing | {decision.get('branch', 'n/a')} | {shipped} | {_num(sharpe['validation'])} (gain) | "
        f"{_num(sharpe['backtest'])} (gain) | n/a |"
    )


def _topology_row(research: dict | None) -> str | None:
    if not research:
        return None
    decision = research.get("decision") or {}
    results = research.get("results") or {}
    mid, off = results.get("on_mid") or {}, results.get("off") or {}
    shipped = "learned topology ON (shrink-only 0.5..1.0)" if decision.get("topology_learning_enabled", True) else "learned topology OFF"
    deltas = [
        (mid.get(split) or {}).get("net_sharpe", float("nan")) - (off.get(split) or {}).get("net_sharpe", float("nan"))
        for split in SPLITS
    ]
    return (
        f"| Learned topology | {decision.get('branch', 'n/a')} | {shipped} | {_num(deltas[0])} (ON mid vs OFF) | "
        f"{_num(deltas[1])} (ON mid vs OFF) | n/a |"
    )


def _class_ic_lines(evaluation_dir: Path) -> list[str]:
    reports = _per_split(evaluation_dir, "class_ic_audit")
    lines: list[str] = []
    for split, report in reports.items():
        head = ((report or {}).get("heads") or {}).get("target_return_20d")
        if not head:
            continue
        pooled = head.get("pooled") or {}
        between = head.get("between_class") or head.get("between") or {}
        within = head.get("within") or {}
        parts = ", ".join(
            f"{name} {_num(stats.get('mean_ic'))} (t {_num(stats.get('hac_t'), '.2f')})" for name, stats in sorted(within.items())
        )
        between_ic = between.get("mean_ic") if isinstance(between, dict) else between
        lines.append(
            f"| {split} | {_num(pooled.get('mean_ic'))} (t {_num(pooled.get('hac_t'), '.2f')}) | {_num(between_ic)} | {parts or 'n/a'} |"
        )
    if not lines:
        return ["_Not run yet: `aq evaluate --ic-by-class --split validation|backtest`._"]
    return ["| Split | Pooled rank_20d IC | Between-class IC | Within-class IC (HAC t) |", "|---|---|---|---|", *lines]


def _gate_lines(evaluation_dir: Path) -> list[str]:
    reports = _per_split(evaluation_dir, "gate_audit")
    lines = [
        f"| {split} | {report.get('num_decisions', 'n/a')} | {_pct(report.get('veto_share'), '.0f')} | "
        f"{_pct(report.get('false_veto_share_of_vetoes'), '.0f')} | {_num(report.get('mean_forward_ic_vetoed'))} | {_num(report.get('mean_forward_ic_all'))} |"
        for split, report in reports.items()
        if report
    ]
    if not lines:
        return ["_Not run yet: `aq evaluate --audit-gates --split validation|backtest`._"]
    return [
        "| Split | Rebalance dates | Vetoed | False vetoes (of vetoes) | Forward IC on vetoed dates | Forward IC overall |",
        "|---|---|---|---|---|---|",
        *lines,
    ]


def _head_line(evaluation_dir: Path) -> str:
    audit = load_json(evaluation_dir / "head_audit.json")
    if not isinstance(audit, dict):
        return "_Not run yet: `aq evaluate --audit-heads`._"
    failing = audit.get("failing_in_decision_path") or []
    return (
        f"**{audit.get('num_passed', 'n/a')}/{audit.get('num_components', 'n/a')}** components pass their own gate; "
        f"failing and read by the live path: {', '.join(f'`{name}`' for name in failing) if failing else 'none'}."
    )


def _holdout_line(evaluation_dir: Path) -> str:
    report = load_json(evaluation_dir / "holdout_report.json")
    if not isinstance(report, dict):
        return "_Not run yet: `python scripts/holdout_report.py` (one look, after the config freeze)._"
    live = report.get("as_live_book") or {}
    ideal = report.get("idealized_book") or {}
    return (
        f"Window {report.get('first_date', '?')} .. {report.get('last_date', '?')}, {report.get('tickers', '?')} tickers: "
        f"as-live Sharpe **{_num(live.get('net_sharpe'))}** ({_pct(live.get('net_total_return'))}, drawdown "
        f"{_pct(live.get('net_max_drawdown'), '.2f')}, {live.get('num_vetoed_rebalances', 'n/a')}/{live.get('num_rebalances', 'n/a')} "
        f"rebalances vetoed), idealized {_num(ideal.get('net_sharpe'))}."
    )


def build_research_markdown(evaluation_dir: Path) -> str:
    overrides = load_json(evaluation_dir / "lean_decision_overrides.json")
    overrides = overrides if isinstance(overrides, dict) else {}
    config = _config_for(evaluation_dir)
    sleeve_rows = [
        row
        for row in (
            _forex_row_v6(evaluation_dir, config) or _sleeve_row(
                "Forex sleeve", load_json(evaluation_dir / "class_sleeve_research_forex.json"), "gross 0.10",
                overrides.get("Forex sleeve"),
            ),
            _sleeve_row(
                "Bond sleeve", load_json(evaluation_dir / "class_sleeve_research_bond.json"), "gross 0.10",
                overrides.get("Bond sleeve"),
            ),
            _crypto_row_v6(evaluation_dir, config) or _crypto_row(load_json(evaluation_dir / "crypto_graduation_research.json")),
            _rl_row(load_json(evaluation_dir / "rl_sizing_research.json")),
            _topology_row(load_json(evaluation_dir / "topology_sizing_research.json")),
        )
        if row
    ]
    sleeves = (
        [
            "| Area | Rule branch | Shipped setting | Validation Sharpe | Backtest Sharpe | Book Sharpe cost |",
            "|---|---|---|---|---|---|",
            *sleeve_rows,
        ]
        if sleeve_rows
        else ["_Not run yet: `scripts/class_sleeve_research.py`, `crypto_graduation_research.py`, `rl_sizing_research.py`._"]
    )
    blocks = [
        "**Sleeves and overlays** (rule R-SLEEVE: ship at the researched budget when the variant is net-positive on both "
        "splits and costs the combined book <= 0.05 Sharpe; otherwise ship at the minimum cap with a loss guard). The Sharpe "
        "columns belong to the named variant (for a minimum-cap area the best-effort one, not the shipped cap); RL rows show "
        "the Sharpe gain over the same book without RL. A Lean run can overrule the offline branch "
        "(`lean_decision_overrides.json`); the row then names both.",
        "\n".join(sleeves),
        "**Offline simulator against Lean** — " + _calibration_line(evaluation_dir),
        "**V6.1.0 rule chain** (each variant is one change, scored on every rebalance phase of both splits; the holdout is "
        "never used to select)",
        "\n".join(_rule_chain_lines(evaluation_dir)),
        "**V6.2.0 rule chain** (pre-registered, the T-bill sweep off in every score so alpha is judged ex-carry)",
        "\n".join(_rule_chain_v620_lines(evaluation_dir)),
        "**V6.3.0 rule chain** (pre-registered; the kill switch scored on the ungated book with its lock path perturbed by "
        "0.5 bp noise; T-bill sweep off)",
        "\n".join(_rule_chain_v630_lines(evaluation_dir)),
        "**V6.4.0 rule chain** (pre-registered in `scripts/v640_research.py` before any score; as-live unless a lead says ungated; "
        "the holdout is read only where a lead's bar names it)",
        "\n".join(_rule_chain_v640_lines(evaluation_dir)),
        "**L1: does the rank skill sit on the days the gate lets the book trade?**",
        "\n".join(_l1_lines(evaluation_dir)),
        "**L2: calibration of the direction heads** (fitted on validation only)",
        "\n".join(_l2_lines(evaluation_dir)),
        "**Where the rank edge sits** (pooled vs between-class vs within-class IC against the 20-day return)",
        "\n".join(_class_ic_lines(evaluation_dir)),
        "**Rolling-IC gate audit** (a false veto is a vetoed date whose realised book return was positive)",
        "\n".join(_gate_lines(evaluation_dir)),
        "**Head promotability** — " + _head_line(evaluation_dir),
        "**Holdout (looked at once)** — " + _holdout_line(evaluation_dir),
    ]
    return "\n\n".join(blocks)


def _lean_row(label: str, period: dict) -> str:
    return (
        f"| {label} | {_num(period.get('sharpe_no_risk_free'))} | {_pct(period.get('net_return'))} | "
        f"{_pct(period.get('max_drawdown'), '.2f')} |"
    )


def build_lean_vs_offline_markdown(evaluation_dir: Path) -> str:
    """The audited Lean run next to the offline books and the public benchmarks over the SAME dates, one block per
    window (backtest split, then the holdout). Lean rows come from `backtest_audit.json` `periods`
    (`aq evaluate --audit-backtest --period START..END`); offline rows from the as-live / holdout / benchmark reports."""
    audit = load_json(evaluation_dir / "backtest_audit.json")
    periods = (audit or {}).get("periods") if isinstance(audit, dict) else None
    if not periods:
        return (
            "_Not run yet: `aq evaluate --audit-backtest --backtest-dir <run> --period <backtest split> --period <holdout>`._"
        )
    run_id = (audit or {}).get("run_id", "?")
    as_live = load_json(evaluation_dir / "rank_book_simulation_as_live_backtest.json")
    as_live = (as_live or {}).get("as_live") if isinstance(as_live, dict) else None
    ideal_report = load_json(evaluation_dir / "rank_book_simulation_as_live_backtest.json")
    benchmarks = load_json(evaluation_dir / "benchmark_comparison.json")
    baselines = {
        row.get("strategy"): row for row in ((benchmarks or {}).get("baselines") or []) if isinstance(row, dict)
    } if isinstance(benchmarks, dict) else {}
    holdout = load_json(evaluation_dir / "holdout_report.json")
    holdout = holdout if isinstance(holdout, dict) else {}
    holdout_start = str(holdout.get("first_date") or "2025-07-01")

    header = ["| Book | Net Sharpe (no risk-free) | Net return | Max drawdown |", "|---|---|---|---|"]
    blocks: list[str] = []
    for period in periods:
        start, end = str(period.get("start", "?")), str(period.get("end", "?"))
        is_holdout = start >= holdout_start
        rows = [_lean_row(f"**Lean run `{run_id}`** (engine: fills, fees, slippage)", period)]
        if is_holdout:
            live = holdout.get("as_live_book") or {}
            ideal = holdout.get("idealized_book") or {}
            rows.append(
                f"| Offline as-live book | {_num(live.get('net_sharpe'))} | {_pct(live.get('net_total_return'))} | "
                f"{_pct(live.get('net_max_drawdown'), '.2f')} |"
            )
            rows.append(
                f"| Offline idealized book | {_num(ideal.get('net_sharpe'))} | {_pct(ideal.get('net_total_return'))} | "
                f"{_pct(ideal.get('net_max_drawdown'), '.2f')} |"
            )
        else:
            if as_live:
                rows.append(
                    f"| Offline as-live book | {_num(as_live.get('net_sharpe'))} | {_pct(as_live.get('net_total_return'))} | "
                    f"{_pct(as_live.get('net_max_drawdown'), '.2f')} |"
                )
            if isinstance(ideal_report, dict) and ideal_report.get("idealized_net_sharpe") is not None:
                rows.append(
                    f"| Offline idealized book | {_num(ideal_report.get('idealized_net_sharpe'))} | "
                    f"{_pct(ideal_report.get('idealized_net_total_return'))} | n/a |"
                )
            for key, label in (("sp500", "S&P 500 buy and hold"), ("60_40", "60/40 buy and hold")):
                row = baselines.get(key)
                if row:
                    rows.append(
                        f"| {label} | {_num(row.get('net_sharpe'))} | "
                        f"{_num(row.get('total_return_pct'), '+.2f')}% | n/a |"
                    )
        blocks.append(f"**{'Holdout' if is_holdout else 'Backtest split'} ({start} to {end})**\n\n" + "\n".join(header + rows))
    return (
        "\n\n".join(blocks)
        + "\n\n_Same dates and the same Sharpe formula in every row; the Lean row is the engine's equity curve, the offline "
        "rows are simulations. A Lean row far below the as-live row means the offline number did not transfer._"
    )


def refresh_readme_best_effort() -> bool:
    """Re-render every auto-generated README block from what is on disk. Never raises: a report bug must not fail the
    audit or research script that called it."""
    try:
        from generate_evaluation_report import update_readme_evaluation_sections

        return bool(update_readme_evaluation_sections())
    except Exception as exc:  # noqa: BLE001
        print(f"warning: README refresh failed: {exc}")
        return False
