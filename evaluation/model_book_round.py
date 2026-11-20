"""The V6.6.9 model-book round, stage by stage (rules R-BOOK1, R-MIX1, R-INSTALL2, R-LEAN23).

`scripts/v669_book.py` only parses arguments and calls these. Each stage reads what the stage before wrote under `out`, refuses to
run when `rules.json` no longer matches its recorded hash, and nothing here reads a row past the selection window until the candidate
is frozen (`freeze_stage`). The numbers come from the same offline engine the V6.5.0 and V6.6.0 rounds used.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from evaluation import model_book_research as research
from evaluation.premia_research import (
    ResearchContext,
    annual_sharpe,
    annual_volatility,
    class_breadth,
    max_drawdown,
    nulls_for,
    passes_sharpe_clauses,
    phase_offsets,
    placebo_p_value,
    placebo_sharpes,
    score_sleeve,
    selection_gate,
    weights_for,
)
from evaluation.trial_ledger import append_trial
from portfolio.premia_signals import ResearchPanel, SleeveSpec, WeightSettings, sleeve_signal

TRIAL_WINDOW = "v669_selection"
VERIFICATION_SPLIT = "2025-03-01"
PBO_PRIOR = "ml/evaluation/v650/selection_daily.parquet"
PBO_PRIOR_COLUMNS = ("t2_a1_20_top6", "t2_a1_20_full", "t5_st_a", "t5_gbm_a")

RULES_TEXT = {
    "R-BOOK1": (
        "Twelve optimizer trials b02-b13 on one fixed signal (ml_a1 through load_score_table, universe the config's four classes). "
        "Controls b01 (V6.5.0's top-6 book, aligned) and core (the model-free risk-parity core) are scored and never selected, and count in no N."
    ),
    "R-MIX1": "Six signal trials m01-m06 on one fixed optimizer (pooled ranks, every 20 sessions).",
    "D1": "Eight counted looks: the rank IC of ml_a1 by class (4) and horizon (5 and 20 sessions) on the selection window. They select nothing.",
    "R-SLEEVE2": (
        "Net of costs and financing, the median over 5 rebalance phases: Sharpe >= 0.40 in both halves and >= 0.50 pooled, and p < 0.05 against the "
        "asset_block and time_shift nulls (100 draws each, only for trials that pass the Sharpe clauses). Survivors correlated above 0.7 drop the "
        "lower Sharpe; at most 5 remain. PBO by CSCV over 16 blocks, with V6.5.0's T2 and T5 columns on the shared window: PBO >= 0.5 and no survivor counts."
    ),
    "R-INSTALL2": (
        "Pool: the 18 model-driven trials. Eligible on the selection window (median of 5 phases): max drawdown <= 15%, annual volatility <= 10%, mean gross <= 2.0, "
        "a non-zero weight in at least 3 of the 4 classes on at least 80% of rebalance rows. The candidate is the eligible trial with the highest pooled Sharpe "
        "(tie: lower turnover); with none eligible, the model-free core. Frozen before any later row exists. It installs iff on the verification window, with the "
        "installed models' scores: volatility <= 10%, drawdown <= 15%, gross <= 2.0, the Lean run completes with a clean engine log, and Lean against the engine "
        "keeps daily correlation >= 0.90 and an annual return gap <= 100 bps. Sharpe is reported, not required. Share: a gate survivor blends with the crypto "
        "sleeve by inverse volatility; a non-survivor gets a fixed 30% and the crypto sleeve 70%. Label: reinstated, not verified."
    ),
    "R-LEAN23": (
        "The in-Lean mode is documented as verified iff its parity run completes with a clean engine log, its daily returns correlate >= 0.95 with the "
        "engine-backed run of the same rows, and the mean absolute weight difference between its logged rows and the file's rows on shared dates is <= 0.01. "
        "Otherwise it is documented as built, parity not reached, with the numbers and the first diverging date; the default source stays the file."
    ),
}


def rules_payload(*, written: str) -> dict[str, Any]:
    """Everything the round fixes before a score exists: windows, sizing, the trial lists and the rule texts."""
    return {
        "written": written,
        "disclosure": [
            "The installed models were trained on 2014-2021 and validated on 2022-2023; the walk-forward score tables of the selection window come from V6.5.0's walk-forward refits.",
            "Score tables of V6.5.0 were read without the next-bar shift for crypto and forex (Problems #390); every score here passes through load_score_table.",
            "Holdouts V1, V2, V3, P and CV stay unread. The verification window was read by earlier runs of other books, never for this one.",
            "The universe was chosen with hindsight and has no delisted names; the null time_shift partly catches it.",
            "The forex name cap is 6% because forex_min_trade_usd is $5,000 of a $100,000 book: a 3% name could never open (audit item 4).",
            "The class loss guard holds a guarded class out until it has 60 sessions of paper record, so forex joins about three months after a window starts.",
        ],
        "windows": {"selection": list(research.SELECTION), "verification": list(research.VERIFICATION)},
        "weight_settings": research.MODEL_SETTINGS,
        "guard": research.GUARD,
        "eligibility": research.ELIGIBLE,
        "lean_vs_engine": research.LEAN_VS_ENGINE,
        "non_survivor_share": research.NON_SURVIVOR_SHARE,
        "trials": {
            spec.id: {"table": spec.params["table"], "every": spec.rebalance_every, **{k: v for k, v in spec.params.items() if k not in research.GUARD and k != "table"}}
            for spec in [*research.book_trials(), *research.mix_trials(), *research.control_trials()]
        },
        "counted_trials": 12 + 6 + 8,
        "rules": RULES_TEXT,
    }


def read_json(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True, default=float), encoding="utf-8", newline="\n")


def write_rules(out: Path, payload: Mapping[str, Any]) -> str:
    """Writes `rules.json` and its sha256 once; a second write is refused, because a rule is never edited after a score exists."""
    rules, sha = out / "rules.json", out / "rules.sha256"
    if rules.exists() or sha.exists():
        raise FileExistsError(f"{rules} already exists: a rule is never rewritten (re-register a defective trial instead)")
    out.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=1, sort_keys=True)
    rules.write_text(text, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    sha.write_text(digest + "\n", encoding="utf-8", newline="\n")
    return digest


def check_rules(out: Path) -> dict[str, Any]:
    """The rules, after proving they are the ones that were recorded."""
    text = (out / "rules.json").read_text(encoding="utf-8")
    expected = (out / "rules.sha256").read_text(encoding="utf-8").strip()
    actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if actual != expected:
        raise SystemExit(f"rules.json changed: {actual} is not the recorded {expected}")
    return json.loads(text)


def with_tables(context: ResearchContext, tables: Mapping[str, pd.DataFrame], *, settings: WeightSettings | None = None) -> ResearchContext:
    """The context with its signal tables replaced by `tables` (kept: the panel's other extras) and, when given, other sizing settings."""
    extras = {**context.panel.extras, **tables}
    panel = ResearchPanel(context.panel.known, context.panel.asset_class, context.panel.fred, extras)
    return dataclasses.replace(context, panel=panel, **({"settings": settings} if settings is not None else {}))


def settings_for(spec: SleeveSpec) -> WeightSettings:
    """The control b01 is V6.5.0's book and keeps V6.5.0's sizing; everything else uses the round's."""
    return WeightSettings() if spec.id == "b01" else research.model_settings()


def _selection_specs(ids: Sequence[str] | None = None, specs: Sequence[SleeveSpec] | None = None) -> list[SleeveSpec]:
    specs = [*research.candidate_pool(), *research.control_trials()] if specs is None else list(specs)
    return [spec for spec in specs if ids is None or spec.id in ids]


def _pool(pool: Sequence[SleeveSpec] | None) -> list[SleeveSpec]:
    """The round's selectable trials: R-BOOK1 and R-MIX1's by default, or another round's own list (V6.6.10, R-BOOK2)."""
    return research.candidate_pool() if pool is None else list(pool)


def score_stage(
    context: ResearchContext, out: Path, *, window: tuple[str, str, str] = research.SELECTION, ids: Sequence[str] | None = None,
    force: bool = False, log: Callable[[str], None] = print, specs: Sequence[SleeveSpec] | None = None,
    control_ids: Sequence[str] = research.CONTROL_IDS,
) -> dict[str, Any]:
    """Scores every trial (controls too) on the selection window and appends the candidates to the ledger. `specs` and `control_ids`
    name another round's trials and controls (V6.6.10)."""
    check_rules(out)
    start, split, end = window
    if end > research.SELECTION[2]:
        raise SystemExit(f"{end} is past the selection window ({research.SELECTION[2]})")
    scores = read_json(out / "selection_scores.json", {})
    daily_path = out / "selection_daily.parquet"
    frames: dict[str, pd.Series] = {}
    if daily_path.exists():
        stored = pd.read_parquet(daily_path)
        frames = {column: stored[column].dropna() for column in stored.columns}
    for spec in _selection_specs(ids, specs):
        if spec.id in scores and not force:
            continue
        score = score_sleeve(spec, dataclasses.replace(context, settings=settings_for(spec)), start=start, split=split, end=end)
        daily = score.pop("daily")
        frames[spec.id] = daily[min(daily)]
        scores[spec.id] = score
        role = "plumbing" if spec.id in control_ids else "candidate"
        append_trial(out / "trial_ledger.jsonl", trial_id=spec.id, track=spec.track, window=TRIAL_WINDOW, role=role,
                     annualised_sharpe=score["sharpe"], n_obs=len(frames[spec.id]), engine="offline")
        log(f"{spec.id:6s} sharpe {_show(score['sharpe'])} h1 {_show(score['sharpe_first_half'])} h2 {_show(score['sharpe_second_half'])} "
            f"dd {score['max_drawdown']:.3f} vol {_show(score['volatility'])} gross {score['mean_gross']:.2f} breadth {score['class_breadth']:.2f}")
    write_json(out / "selection_scores.json", scores)
    pd.DataFrame(frames).sort_index().to_parquet(daily_path)
    return scores


def _show(value: float | None) -> str:
    return "  n/a" if value is None else f"{value:5.2f}"


def placebo_stage(
    context: ResearchContext, out: Path, *, draws: int = 100, only: Sequence[str] | None = None, force: bool = False,
    window: tuple[str, str, str] = research.SELECTION, log: Callable[[str], None] = print, suffix: str = "", modes: Sequence[str] | None = None,
    pool: Sequence[SleeveSpec] | None = None,
) -> dict[str, Any]:
    """Placebo p-values for the trials that pass R-SLEEVE2's Sharpe clauses (and only those: the clause is the gate to the expensive test)."""
    check_rules(out)
    scores = read_json(out / "selection_scores.json", {})
    path = out / f"selection_placebos{suffix}.json"
    done = read_json(path, {})
    start, _, end = window
    for spec in _pool(pool):
        score = scores.get(spec.id)
        if score is None or not passes_sharpe_clauses(score) or (spec.id in done and not force) or (only and spec.id not in only):
            continue
        sized = dataclasses.replace(context, settings=settings_for(spec))
        result = {}
        for mode in nulls_for(spec):
            if modes is not None and mode not in modes:
                continue
            sharpes = placebo_sharpes(spec, sized, mode, start=start, end=end, draws=draws)
            result[mode] = {"p": placebo_p_value(score["sharpe"], sharpes), "draws": len(sharpes),
                            "median": float(np.median(sharpes)) if sharpes else None,
                            "q95": float(np.quantile(sharpes, 0.95)) if sharpes else None}
            log(f"{spec.id} {mode} p {result[mode]['p']:.3f}")
            for value in sharpes:
                append_trial(out / f"trial_ledger{suffix}.jsonl", trial_id=f"{spec.id}:{mode}", track=spec.track, window=TRIAL_WINDOW, role="placebo",
                             annualised_sharpe=value, n_obs=0, engine="offline")
        done[spec.id] = result
        write_json(path, done)
    return done


def gate_stage(out: Path, *, pool: Sequence[SleeveSpec] | None = None) -> dict[str, Any]:
    """R-SLEEVE2 over the pool: survivors, the clause each other trial failed, and the trials with no placebo run."""
    check_rules(out)
    scores = read_json(out / "selection_scores.json", {})
    placebos: dict[str, Any] = {}
    for part in sorted(out.glob("selection_placebos*.json")):
        for name, tests in read_json(part, {}).items():
            placebos.setdefault(name, {}).update(tests)
    daily = pd.read_parquet(out / "selection_daily.parquet")
    ids = {spec.id for spec in _pool(pool)}
    rows = [{**score, "id": name, "daily": {0: daily[name].dropna()}} for name, score in scores.items() if name in ids and name in daily]
    p_values = {name: {mode: entry["p"] for mode, entry in tests.items()} for name, tests in placebos.items()}
    gate = selection_gate(rows, p_values)
    gate["unscored"] = sorted(ids - set(scores))
    write_json(out / "selection_gate.json", gate)
    return gate


def pbo_stage(out: Path, *, root: Path, blocks: int = 16, pool: Sequence[SleeveSpec] | None = None) -> dict[str, Any]:
    """The probability of backtest overfitting over this round's daily columns plus V6.5.0's model sleeves on the shared window."""
    from evaluation.research_round import pbo_report

    check_rules(out)
    frames = [pd.read_parquet(out / "selection_daily.parquet")]
    prior = Path(root) / PBO_PRIOR
    if prior.exists():
        frames.append(pd.read_parquet(prior))
    columns = [spec.id for spec in _pool(pool)] + list(PBO_PRIOR_COLUMNS)
    report = pbo_report(frames, columns, window=(research.SELECTION[0], research.SELECTION[2]), blocks=blocks)
    write_json(out / "selection_pbo.json", report)
    return report


def diagnostics_stage(context: ResearchContext, out: Path, *, table: str = "ml_a1", log: Callable[[str], None] = print) -> dict[str, Any]:
    """D1: eight counted looks at where the score has rank IC. Each is a ledger candidate without a Sharpe (it counts in N, selects nothing)."""
    check_rules(out)
    path = out / "diagnostics_d1.json"
    if path.exists():
        return read_json(path)
    looks = research.rank_ic_diagnostics(
        context.panel.extras[table], context.panel.known, context.panel.asset_class, start=research.SELECTION[0], end=research.SELECTION[2],
    )
    for name, entry in looks.items():
        append_trial(out / "trial_ledger.jsonl", trial_id=f"d1_{name}", track="D1", window=TRIAL_WINDOW, role="candidate", annualised_sharpe=None,
                     n_obs=entry["n_dates"], engine="offline", detail=entry)
        log(f"d1 {name}: ic {entry['mean_ic']} t {entry['t_hac']}")
    write_json(path, looks)
    return looks


def report_stage(out: Path, *, name: str = "r_book1.json", survivors_only: bool = False) -> dict[str, Any]:
    """One file with every trial's numbers, the gate, the PBO, the diagnostics and the candidate R-INSTALL2 names. `survivors_only`
    (V6.6.10, R-BOOK2): only a gate survivor can be the candidate, and with none there is no candidate."""
    check_rules(out)
    scores = read_json(out / "selection_scores.json", {})
    gate = read_json(out / "selection_gate.json", {})
    pbo = read_json(out / "selection_pbo.json", {})
    survivors = [] if (pbo.get("pbo") is None or pbo["pbo"] >= 0.5) else gate.get("survivors", [])
    pool = [{"id": key, **score} for key, score in scores.items() if not survivors_only or key in survivors]
    pick = research.pick_candidate(pool) if pool or not survivors_only else {"candidate": None, "reason": "no trial survived the gate and the PBO"}
    report = {"trials": scores, "gate": gate, "pbo": pbo, "survivors": survivors, "diagnostics": read_json(out / "diagnostics_d1.json", {}), "install": pick}
    write_json(out / name, report)
    return report


def freeze_stage(
    out: Path, *, root: Path, code_files: Sequence[str], report_name: str = "r_book1.json", specs: Sequence[SleeveSpec] | None = None,
) -> tuple[Path, str]:
    """Freezes the candidate's definition and the code that produces its rows, once. Nothing after the selection window is read before this."""
    check_rules(out)
    path = out / "freeze.json"
    if path.exists():
        raise FileExistsError(f"{path} exists: a candidate is frozen once")
    report = read_json(out / report_name)
    if report is None:
        raise SystemExit("run `report` first: there is no candidate to freeze")
    name = report["install"]["candidate"]
    if name is None:
        raise SystemExit(f"nothing to freeze: {report['install']['reason']}")
    spec = next(item for item in _selection_specs(None, specs) if item.id == name)
    payload = {
        "candidate": name, "survivor": name in report["survivors"], "kind": "model_book",
        "definition": {"id": spec.id, "table": spec.params["table"], "every": spec.rebalance_every, "params": dict(spec.params), "universe": list(spec.universe)},
        "settings": research.MODEL_SETTINGS, "reason": report["install"]["reason"],
        "code_sha256": {file: hashlib.sha256((Path(root) / file).read_bytes()).hexdigest() for file in code_files if (Path(root) / file).exists()},
    }
    text = json.dumps(payload, indent=1, sort_keys=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    (out / "freeze.sha256").write_text(digest + "\n", encoding="utf-8", newline="\n")
    return path, digest


def check_freeze(out: Path) -> dict[str, Any]:
    """The frozen candidate, after proving its file is the one that was recorded. Verification rows exist only behind this."""
    text = (out / "freeze.json").read_text(encoding="utf-8")
    expected = (out / "freeze.sha256").read_text(encoding="utf-8").strip()
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != expected:
        raise SystemExit("freeze.json changed since it was recorded")
    return json.loads(text)


def candidate_spec(frozen: Mapping[str, Any]) -> SleeveSpec:
    """The frozen candidate as a spec, from its definition."""
    definition = frozen["definition"]
    from portfolio.premia_signals import XS

    return SleeveSpec(definition["id"], "FROZEN", XS, "external_score", tuple(definition["universe"]), int(definition["every"]), dict(definition["params"]))


def combine_score_files(selection: Path, verification: Path, destination: Path, *, last_selection: str) -> Path:
    """One score file over both windows: the selection tables up to `last_selection`, then the installed models' rows. The seam is the model change."""
    first = pd.read_csv(selection, dtype={"date": str, "ticker": str})
    second = pd.read_csv(verification, dtype={"date": str, "ticker": str})
    merged = pd.concat([first[first["date"] <= last_selection], second[second["date"] > last_selection]], ignore_index=True)
    merged.sort_values(["date", "ticker"]).to_csv(destination, index=False, lineterminator="\n", float_format="%.6f")
    return destination


def phase_rows(spec: SleeveSpec, context: ResearchContext, *, start: str, end: str) -> dict[int, dict[str, dict[str, float]]]:
    """The spec's weight rows over [start, end] for every rebalance phase."""
    signal = sleeve_signal(spec, context.panel)
    return {offset: weights_for(spec, context, signal, start=start, end=end, phase_offset=offset) for offset in phase_offsets(spec.rebalance_every)}


def verify_stage(
    context: ResearchContext, out: Path, *, window: tuple[str, str] = research.VERIFICATION, log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """The frozen candidate on the verification window, for every phase, scored on the offline engine. Returns the median-phase summary
    and writes the median phase's rows (`weights/model_book.csv`) for the Lean run."""
    from portfolio.target_weights import write_weight_file

    check_rules(out)
    frozen = check_freeze(out)
    spec = candidate_spec(frozen)
    sized = dataclasses.replace(context, settings=research.model_settings())
    rows = phase_rows(spec, sized, start=window[0], end=window[1])
    sessions = sized.sessions_for(spec)
    summaries = {}
    for offset, weights in rows.items():
        result = sized.simulate(weights, window[0], window[1])
        strategy = result["strategy_excess"]
        summaries[offset] = {
            "sharpe": annual_sharpe(strategy, sessions=sessions), "volatility": annual_volatility(strategy, sessions=sessions),
            "max_drawdown": max_drawdown(strategy), "mean_gross": float(result["gross"].mean()) if not result["gross"].empty else 0.0,
            "turnover": result["turnover"], "class_breadth": class_breadth(weights, sized.panel.asset_class), "rows": len(weights),
        }
        log(f"phase {offset}: {summaries[offset]}")
    ordered = sorted(summaries, key=lambda offset: (summaries[offset]["sharpe"] if summaries[offset]["sharpe"] is not None else -math.inf))
    middle = ordered[len(ordered) // 2]

    def median(key: str) -> float | None:
        values = [item[key] for item in summaries.values() if item[key] is not None]
        return float(np.median(values)) if values else None

    summary = {key: median(key) for key in ("sharpe", "volatility", "max_drawdown", "mean_gross", "turnover", "class_breadth")}
    summary.update(median_phase=middle, phases=summaries, window=list(window), candidate=frozen["candidate"])
    (out / "weights").mkdir(parents=True, exist_ok=True)
    write_weight_file(rows[middle], out / "weights" / "model_book.csv")
    write_json(out / "verification.json", summary)
    return summary


def selection_rows_for(
    spec: SleeveSpec, context: ResearchContext, *, start: str, end: str, phase_index: int,
) -> dict[str, dict[str, float]]:
    """The spec's rows from one phase (by index into its offsets), as the Lean runs read them."""
    offsets = phase_offsets(spec.rebalance_every)
    signal = sleeve_signal(spec, context.panel)
    return weights_for(spec, dataclasses.replace(context, settings=research.model_settings()), signal, start=start, end=end, phase_offset=offsets[phase_index % len(offsets)])


CRYPTO_SPEC = SleeveSpec(
    "t3_crypto_trend_blend", "T3", "time_series", "crypto_trend", ("crypto",), 5, {"lookback_a": 20, "lookback_b": 60, "lookback_c": 120},
)
CRYPTO_PHASE = 4  # the phase the installed crypto sleeve's pinned run used


def load_round_context(root: Path, sources: Mapping[str, Path], *, end: str | None = None) -> ResearchContext:
    """The research context for this round: the config with forex enabled (the engine then holds forex as the installed config will),
    the model-book sizing, and every signal table built from `sources` (table name -> score file), each through `load_score_table`."""
    from evaluation.premia_research import build_context

    root = Path(root)
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    config["phase_v2"]["forex_risk"]["enabled"] = True
    context = build_context(root, config, respect_disabled_classes=True)
    sessions = list(context.panel.known.index)
    universe = research.universe_tickers(config)
    scores = {name: research.load_score_table(path, sessions, context.panel.asset_class, universe=universe, end=end) for name, path in sources.items()}
    return with_tables(context, research.signal_tables(context.panel, scores), settings=research.model_settings())


def crypto_rows(context: ResearchContext, *, start: str, end: str) -> dict[str, dict[str, float]]:
    """The installed crypto sleeve's rows over [start, end] on the pinned phase, sized by the default settings it was frozen with."""
    sized = dataclasses.replace(context, settings=WeightSettings())
    offsets = phase_offsets(CRYPTO_SPEC.rebalance_every)
    return weights_for(CRYPTO_SPEC, sized, sleeve_signal(CRYPTO_SPEC, sized.panel), start=start, end=end, phase_offset=offsets[CRYPTO_PHASE % len(offsets)])


def inverse_vol_share(model_volatility: float, crypto_volatility: float) -> float:
    """The model book's share when the candidate is a gate survivor: weights proportional to 1 / volatility."""
    return (1.0 / model_volatility) / (1.0 / model_volatility + 1.0 / crypto_volatility)


def blend_stage(
    context: ResearchContext, out: Path, *, name: str, start: str, end: str, share: float, phase_index: int,
) -> dict[str, Any]:
    """`weights/<name>.csv`: the frozen candidate's rows blended with the crypto sleeve's by `share`, and the same sleeves' offline numbers."""
    from portfolio.target_weights import write_weight_file

    check_rules(out)
    frozen = check_freeze(out)
    spec = candidate_spec(frozen)
    model = selection_rows_for(spec, context, start=start, end=end, phase_index=phase_index)
    crypto = crypto_rows(context, start=start, end=end)
    rows = research.blend_rows({"model": model, "crypto": crypto}, {"model": share, "crypto": 1.0 - share})
    destination = out / "weights" / f"{name}.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_weight_file(rows, destination)
    result = context.simulate(rows, start, end)
    sessions = None
    summary = {
        "name": name, "window": [start, end], "model_share": share, "rows": len(rows), "model_rows": len(model), "crypto_rows": len(crypto),
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "sharpe": annual_sharpe(result["strategy_excess"], sessions=sessions),
        "volatility": annual_volatility(result["strategy_excess"], sessions=sessions), "max_drawdown": max_drawdown(result["strategy_excess"]),
        "mean_gross": float(result["gross"].mean()), "turnover": result["turnover"],
    }
    write_json(out / f"blend_{name}.json", summary)
    return summary


def lean_summary(report: Mapping[str, Any], *, completed: bool, engine_log_clean: bool) -> dict[str, Any]:
    """What R-INSTALL2 reads of one Lean run: the engine-vs-Lean comparison of `scripts/v650_instrument.py compare` plus the two facts a log shows."""
    gap = report.get("annual_gap_bps")
    return {
        "completed": bool(completed), "engine_log_clean": bool(engine_log_clean), "correlation": report.get("corr_lag0"),
        "annual_return_gap": None if gap is None else float(gap) / 1e4, "run": report.get("run"), "name": report.get("name"),
    }


def judge_stage(out: Path, *, lean: Mapping[str, Any] | None) -> dict[str, Any]:
    """R-INSTALL2's verdict from the frozen candidate's verification numbers and the Lean run, every clause with its number."""
    check_rules(out)
    frozen = check_freeze(out)
    verification = read_json(out / "verification.json")
    verdict = research.install_verdict(verification, lean, survivor=bool(frozen["survivor"]))
    verdict.update(candidate=frozen["candidate"], verification_window=verification["window"])
    write_json(out / "r_install2.json", verdict)
    return verdict


_TARGET_BLOCK = re.compile(r'("target_weights": \{\s*"enabled": true,\s*"weights_path": "[^"]+",\s*"weights_sha256": ")[0-9a-f]{64}(",)(?!\s*"uses_model")(\s*)')
_FOREX_BLOCK = re.compile(r'("forex_risk": \{\s*"enabled": )false')


def install_config_text(text: str, *, weights_sha256: str) -> str:
    """`config.json` with the three installed values changed and nothing else: the weight file's hash, `uses_model: true` (the file now
    comes from models, so the kill switch's model-age check applies) and `forex_risk.enabled: true` (a forex name is held, not swept)."""
    changed, count = _TARGET_BLOCK.subn(lambda m: f'{m.group(1)}{weights_sha256}{m.group(2)}{m.group(3)}"uses_model": true,{m.group(3)}', text, count=1)
    if count != 1:
        raise ValueError("the target_weights block is not in the shape the install expects (uses_model may already be set)")
    changed, forex = _FOREX_BLOCK.subn(r"\g<1>true", changed, count=1)
    if forex != 1:
        raise ValueError("phase_v2.forex_risk.enabled is not false")
    return changed


MAX_SCORE_LAG_DAYS = 5


def blend_row(raw: Mapping[str, Any], context: ResearchContext, session: str) -> dict[str, float] | None:
    """The row an installed blend (`ml/target_weights_candidate.json`, `kind: blend`) decides at `session`, or None when no part decides then. Computed from
    the closes and scores the context holds up to the session, counting rebalances from the file's `history_start`, so it equals the file's own row."""
    from portfolio.model_book import parse_definition, row_for_session, weight_settings

    definition = parse_definition(raw)
    book, sleeve = weight_settings(definition)
    return row_for_session(definition, context.panel, context.panel.extras, session, settings=book, sleeve_settings=sleeve, listed=context.listed, sleeve_signal=sleeve_signal)
GENERATION_ID = "g0006"


def register_generation(
    registry_path: Path, lifecycle_path: Path, *, frozen: Mapping[str, Any], freeze_sha256: str, installed: bool, procedure_sha256: str, born: str, created_at: str,
) -> dict[str, Any]:
    """Adds the model book to the generations' registry once (Problems #388): the installed book (`tier: installed`, `stage: active`) when R-INSTALL2 says
    install, else a shadow observer holding nothing (`tier: none`). It `needs: model`, so a host that has the models decides it
    (`scripts/model_book_decide.py`); the runner never fakes a row for it. A refit adds a vintage to this entry (`register_vintage`)."""
    from evaluation.generation_registry import Generation, append_lifecycle, load_registry, save_registry

    registry = load_registry(Path(registry_path))
    if GENERATION_ID in registry:
        return {"added": False, "reason": f"{GENERATION_ID} is already registered"}
    definition = {
        **dict(frozen["definition"]), "family": "model_book", "kind": "cross_sectional", "installed": bool(installed), "freeze_sha256": freeze_sha256, "settings": research.MODEL_SETTINGS,
    }
    note = (
        "the multi-asset model book (R-INSTALL2, V6.6.9): reinstated, not verified. No trial survived R-SLEEVE2, so it holds a fixed 30% beside the crypto sleeve by the owner's rule, on paper."
        if installed else
        "the multi-asset model book (V6.6.9) as a shadow observer: R-INSTALL2 did not install it, so it holds nothing; not verified."
    )
    registry[GENERATION_ID] = Generation(
        GENERATION_ID, "model", "installed" if installed else "none", "active" if installed else "shadow", born, procedure_sha256, definition,
        "ml/evaluation/v669/freeze.json", "model", (), 0.0, note, {},
    )
    save_registry(Path(registry_path), registry)
    append_lifecycle(Path(lifecycle_path), event="generation_added", created_at=created_at, payload={"generation": GENERATION_ID, "tier": registry[GENERATION_ID].tier, "stage": registry[GENERATION_ID].stage})
    return {"added": True, "generation": GENERATION_ID, "tier": registry[GENERATION_ID].tier, "stage": registry[GENERATION_ID].stage}


def set_installed_shares(policy_path: Path, shares: Mapping[str, float]) -> dict[str, float]:
    """Records an installed blend's fixed shares in `ml/generations/policy.json`, where `aq cycle status` reads them (the glide stays off)."""
    policy = read_json(Path(policy_path), {})
    policy["installed_shares"] = {name: float(share) for name, share in shares.items()}
    write_json(Path(policy_path), policy)
    return policy["installed_shares"]


def book_definition(frozen: Mapping[str, Any], verification: Mapping[str, Any] | None = None) -> Any:
    """The frozen candidate as a one-part definition (share 1): the model book alone, as its own generation decides it. Its rebalances count
    from the first day of the verification window, on the phase of the verification's median run, the same count the verification rows used."""
    from portfolio.model_book import BlendDefinition, BookPart

    definition = frozen["definition"]
    spec = {"id": definition["id"], "track": "BOOK", "kind": "cross_sectional", "family": "external_score", "universe": list(definition["universe"]),
            "rebalance_every": int(definition["every"]), "params": dict(definition["params"])}
    return BlendDefinition((BookPart("model", 1.0, "book", spec, phase_index_of(frozen, verification)),), research.VERIFICATION[0], None, {"model": 1.0})


def phase_index_of(frozen: Mapping[str, Any], verification: Mapping[str, Any] | None = None) -> int:
    """The phase of the median verification run, as an index into the candidate's offsets (0 before a verification exists)."""
    if not verification or "median_phase" not in verification:
        return 0
    from portfolio.model_book import phase_offsets as offsets_for

    return offsets_for(int(frozen["definition"]["every"])).index(int(verification["median_phase"]))


def score_problem(context: ResearchContext, session: str, *, table: str = "ml_a1") -> str | None:
    """Why `session` can't be decided from the scores: the newest score the table holds is more than `MAX_SCORE_LAG_DAYS` older than it, so a
    decision would rank on stale models' output or none. None when the scores are current."""
    scored = context.panel.extras[table].dropna(how="all")
    if scored.empty:
        return f"the {table} table holds no score"
    lag = (pd.Timestamp(session) - pd.Timestamp(scored.index[-1])).days
    return None if lag <= MAX_SCORE_LAG_DAYS else f"the newest {table} score is {lag} days older than {session} (limit {MAX_SCORE_LAG_DAYS})"


def decide_row(context: ResearchContext, frozen: Mapping[str, Any], session: str, verification: Mapping[str, Any] | None = None) -> dict[str, float] | None:
    """The model book's holding after `session`, from the frozen candidate and the context's closes and scores."""
    from portfolio.model_book import holding_for_session

    return holding_for_session(
        book_definition(frozen, verification), context.panel, context.panel.extras, session, settings=research.model_settings(), sleeve_settings=WeightSettings(),
        listed=context.listed, sleeve_signal=sleeve_signal,
    )


def candidate_file(frozen: Mapping[str, Any], verification: Mapping[str, Any], *, share: float, pinned_run: str | None) -> dict[str, Any]:
    """The installed book as `ml/target_weights_candidate.json`: the crypto sleeve (generation g0001) and the model book (g0006), each with the spec that
    rebuilds its rows, the model book's sizing, and the phase the pinned run used. `scripts/model_book_decide.py` and the in-Lean mode read it."""
    from portfolio.model_book import phase_offsets as offsets_for

    definition = frozen["definition"]
    book = {"id": definition["id"], "track": "BOOK", "kind": "cross_sectional", "family": "external_score", "universe": list(definition["universe"]),
            "every": int(definition["every"]), "params": dict(definition["params"])}
    sleeve = {"id": CRYPTO_SPEC.id, "track": CRYPTO_SPEC.track, "kind": CRYPTO_SPEC.kind, "family": CRYPTO_SPEC.family, "universe": list(CRYPTO_SPEC.universe),
              "rebalance_every": CRYPTO_SPEC.rebalance_every, "params": dict(CRYPTO_SPEC.params)}
    book_phase = offsets_for(int(definition["every"])).index(int(verification["median_phase"]))
    return {
        "kind": "blend", "history_start": research.VERIFICATION[0], "pinned_run": pinned_run, "settings": research.MODEL_SETTINGS,
        "parts": [
            {"generation": "g0001", "share": round(1.0 - float(share), 10), "sleeve": sleeve, "phase_index": CRYPTO_PHASE},
            {"generation": "g0006", "share": float(share), "book": book, "phase_index": book_phase},
        ],
    }
