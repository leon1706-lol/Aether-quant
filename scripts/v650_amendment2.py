"""V6.5.0 amendments 2 and 3 (ml/evaluation/v650/rules_amendment_{2,3}.json): the corrected earnings trials and the pre-2013 read.

    python scripts/v650_amendment2.py eps-score      # R-SLEEVE2's Sharpe clauses and, for a pass, its placebos
    python scripts/v650_amendment2.py pbo            # over all 42 selection trials, on the common window
    python scripts/v650_amendment2.py eps-pool       # a survivor's R-LEAN19 runs, frozen first
    python scripts/v650_amendment2.py eps-judge --status <status file>
    python scripts/v650_amendment2.py pre2013-make   # the frozen candidate on the pre-2013 root, and 20 placebos
    python scripts/v650_amendment2.py pre2013-judge --status <status file>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from v650_lean import (  # noqa: E402
    E5_DRAWS,
    PHASES,
    SPECS,
    _base,
    candidate_rows,
    check_freeze,
    lean_statistics,
    make_run,
    pre2013_context,
)
from v650_research import DAILY, LEDGER, OUT, check_rules, load_context, read_json, write_json  # noqa: E402

from data_pipeline.edgar_facts import read_eps, read_splits, split_adjusted_eps, surprise_table  # noqa: E402
from evaluation.premia_research import (  # noqa: E402
    annual_sharpe,
    nulls_for,
    passes_sharpe_clauses,
    placebo_p_value,
    placebo_sharpes,
    score_sleeve,
)
from evaluation.trial_ledger import append_trial  # noqa: E402
from portfolio.premia_signals import XS, ResearchPanel, SleeveSpec  # noqa: E402

EPS_PATH = ROOT / "data" / "reference" / "edgar_eps.csv"
EPS_SPECS = [
    SleeveSpec("t4_eps_sue_20", "T4", XS, "external_score", ("equity",), 5, {"table": "eps_20"}),
    SleeveSpec("t4_eps_sue_60", "T4", XS, "external_score", ("equity",), 5, {"table": "eps_60"}),
]
RESULT = OUT / "amendment3_eps.json"  # amendment2_eps.json keeps the closed, defective variants' scores


def eps_context():
    context = load_context()
    eps = split_adjusted_eps(read_eps(EPS_PATH), read_splits())
    sessions = [str(day) for day in context.panel.known.index]
    columns = list(context.panel.known.columns)
    extras = dict(context.panel.extras)
    extras["eps_20"] = surprise_table(eps, sessions, columns, hold_sessions=20)
    extras["eps_60"] = surprise_table(eps, sessions, columns, hold_sessions=60)
    context.panel = ResearchPanel(context.panel.known, context.panel.asset_class, context.panel.fred, extras)
    return context, eps


def stage_eps_score(args) -> int:
    rules = check_rules()
    context, eps = eps_context()
    start, split, end = rules["selection_windows"]["rule_sleeves"]
    out = {"tickers": int(eps["ticker"].nunique()), "quarters": int(len(eps)), "first_filed": str(eps["filed"].min()), "scores": {}, "placebos": {}}
    frames = pd.read_parquet(DAILY)
    for spec in EPS_SPECS:
        score = score_sleeve(spec, context, start=start, split=split, end=end)
        daily = score.pop("daily")
        series = daily[min(daily)]
        frames[spec.id] = series.reindex(frames.index)
        out["scores"][spec.id] = score
        append_trial(LEDGER, trial_id=spec.id, track="T4", window="selection", role="candidate", annualised_sharpe=score["sharpe"], n_obs=len(series), engine="offline")
        print(f"{spec.id}: sharpe {score['sharpe']} h1 {score['sharpe_first_half']} h2 {score['sharpe_second_half']} dd {score['max_drawdown']} gross {score['mean_gross']}", flush=True)
        if passes_sharpe_clauses(score):
            tests = {}
            for mode in nulls_for(spec):
                sharpes = placebo_sharpes(spec, context, mode, start=start, end=end, draws=args.draws)
                tests[mode] = {"p": placebo_p_value(score["sharpe"], sharpes), "draws": len(sharpes), "median": float(np.median(sharpes)) if sharpes else None}
                print(f"  {mode}: p {tests[mode]['p']:.4f} median {tests[mode]['median']}", flush=True)
            out["placebos"][spec.id] = tests
    frames.to_parquet(DAILY)
    out["survivors"] = [
        spec.id for spec in EPS_SPECS
        if spec.id in out["placebos"] and all(test["p"] < 0.05 for test in out["placebos"][spec.id].values())
    ]
    write_json(RESULT, out)
    print("survivors:", out["survivors"], flush=True)
    return 0


def stage_pbo(args) -> int:
    from evaluation.pbo import probability_of_backtest_overfitting

    daily = pd.read_parquet(DAILY).sort_index()
    common = daily[(daily.index >= "2019-01-01") & (daily.index <= "2023-06-30")].fillna(0.0)
    report = probability_of_backtest_overfitting(common.to_numpy(), blocks=16, periods_per_year=365)
    result = {key: report.get(key) for key in ("pbo", "num_trials", "num_combinations", "prob_oos_loss")}
    result["window"] = "2019-01-01..2023-06-30, the basis fixed in pbo_verdict.json"
    write_json(OUT / "amendment3_pbo.json", result)
    print(json.dumps(result, indent=1))
    return 0


def stage_pre2013_make(args) -> int:
    rules = check_rules()
    definition = check_freeze()
    base = _base()
    context, config = pre2013_context(base)
    window = tuple(rules["windows"]["pre2013"])
    available = [name for name in definition["survivors"] if SPECS[name].universe != ("crypto",)]
    early = {"survivors": available, "method": None if len(available) == 1 else definition["method"]}
    runs = {"v650_e5": make_run("v650_e5", candidate_rows(early, context, start=window[0], end=window[1], phase_index=0), window, config, data_root="data_pre2013", sweep=False)}
    rng = np.random.default_rng(2013)
    for draw in range(E5_DRAWS):
        name = f"v650_e5_null_{draw:02d}"
        rows = candidate_rows(early, context, start=window[0], end=window[1], phase_index=int(rng.integers(PHASES)), null_mode="time_shift", seed=2_000 + draw)
        runs[name] = make_run(name, rows, window, config, data_root="data_pre2013", sweep=False)
    write_json(OUT / "pre2013_runs.json", {"definition": early, "runs": runs})
    (OUT / "pre2013_run_list.txt").write_text(" ".join(f"ml/evaluation/run_configs/{name}.json" for name in runs) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(runs)} runs; sleeves {available}")
    return 0


def _nav_returns(run_dir: Path) -> pd.Series:
    from evaluation.backtest_audit import daily_equity_from_chart, load_backtest_run

    points = daily_equity_from_chart(load_backtest_run(run_dir)["result"])
    return pd.Series(dict(points), dtype=float).sort_index().pct_change().dropna()


def per_year(series: pd.Series) -> float:
    """Observations per year: this root has no crypto, so a run may sample weekdays only, and a fixed 365 would inflate its Sharpe."""
    days = (pd.Timestamp(series.index.max()) - pd.Timestamp(series.index.min())).days
    return len(series) / max(days / 365.25, 1e-9)


def sharpe_on_observations(series: pd.Series) -> float | None:
    values = series.to_numpy(dtype=float)
    if len(values) < 20 or values.std(ddof=1) <= 0.0:
        return None
    return float(values.mean() / values.std(ddof=1) * np.sqrt(per_year(series)))


def stage_pre2013_judge(args) -> int:
    from evaluation.alpha_proof import alpha_regression, benchmark_daily_returns, to_sessions
    from evaluation.lean_attribution import fills_from_order_events
    from evaluation.backtest_audit import load_backtest_run

    done = {}
    for line in Path(args.status).read_text(encoding="utf-8-sig").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "LEAN_DONE":
            done[parts[1]] = ROOT / parts[2]
    main_dir = done["v650_e5"]
    series = _nav_returns(main_dir)
    manifest_config = json.loads((ROOT / "ml" / "evaluation" / "run_configs" / "v650_e5.json").read_text(encoding="utf-8"))
    benchmarks = benchmark_daily_returns(ROOT, manifest_config, tickers=("SPY", "AGG"), start=str(series.index.min()), end=str(series.index.max()), data_dir="data_pre2013")
    alpha = alpha_regression(to_sessions(series, benchmarks.index), benchmarks)
    placebos = [value for name, path in done.items() if name.startswith("v650_e5_null_") and (value := sharpe_on_observations(_nav_returns(path))) is not None]
    fills = fills_from_order_events(load_backtest_run(main_dir).get("order_events", []))
    observed = sharpe_on_observations(series)
    result = {
        "run": main_dir.name, "n": int(len(series)), "observations_per_year": per_year(series),
        "sharpe": observed, "sharpe_at_fixed_365": annual_sharpe(series), "lean": lean_statistics(main_dir),
        "alpha_annual": alpha.get("alpha_annual"), "alpha_t": alpha.get("t_hac"), "betas": alpha.get("betas"),
        "first_fill": fills[0].date if fills else None, "last_fill": fills[-1].date if fills else None, "fills": len(fills),
        "placebo_sharpes": sorted(placebos), "placebos_at_or_above": sum(value >= observed for value in placebos) if observed is not None else None,
        "placebo_median": float(np.median(placebos)) if placebos else None,
    }
    write_json(OUT / "pre2013_result.json", result)
    append_trial(LEDGER, trial_id="t3_trend_blend", track="pre2013", window="pre2013", role="verification", annualised_sharpe=observed, n_obs=len(series), engine="lean", detail={"run": main_dir.name})
    print(json.dumps({key: value for key, value in result.items() if key != "placebo_sharpes"}, indent=1, default=str))
    return 0


def eps_rows(spec: SleeveSpec, context, *, start: str, end: str, phase_index: int, null_mode: str | None = None, seed: int = 0) -> dict:
    from evaluation.premia_research import phase_offsets, weights_for
    from portfolio.premia_signals import null_signal, sleeve_signal

    signal = sleeve_signal(spec, context.panel)
    if null_mode:
        signal = null_signal(signal, null_mode, seed=seed, asset_class=context.panel.asset_class)
    offsets = phase_offsets(spec.rebalance_every, PHASES)
    return weights_for(spec, context, signal, start=start, end=end, phase_offset=offsets[phase_index % len(offsets)])


def apply_correlation_clause(survivors: list[str], scores: dict, daily: pd.DataFrame, max_correlation: float = 0.7) -> list[str]:
    """R-SLEEVE2: among survivors, a daily correlation above the limit drops the lower Sharpe."""
    kept: list[str] = []
    for name in sorted(survivors, key=lambda item: scores[item]["sharpe"], reverse=True):
        if all(daily[[name, other]].dropna().corr().iloc[0, 1] <= max_correlation for other in kept):
            kept.append(name)
    return kept


def stage_eps_pool(args) -> int:
    """R-LEAN19's runs for the surviving earnings sleeves. Recorded in the vault before any row after the selection window exists."""
    import hashlib

    from vault_record import record

    rules = check_rules()
    result = read_json(RESULT, {})
    survivors = apply_correlation_clause(result.get("survivors") or [], result.get("scores") or {}, pd.read_parquet(DAILY))
    result["survivors_after_correlation"] = survivors
    write_json(RESULT, result)
    if not survivors:
        print("no earnings sleeve survived: nothing changes")
        return 0
    code = ["scripts/v650_amendment2.py", "data_pipeline/edgar_facts.py", "portfolio/premia_signals.py", "portfolio/target_weights.py", "main.py"]
    write_json(OUT / "amendment2_freeze.json", {"survivors": survivors, "code": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in code}})
    recorded = record("amendment2_freeze", ["ml/evaluation/v650/amendment2_freeze.json", "ml/evaluation/v650/amendment2_eps.json"], {"survivors": float(len(survivors))})
    if not recorded["ok"]:
        raise SystemExit(f"could not record the freeze: {recorded}")
    context, _ = eps_context()
    specs = {spec.id: spec for spec in EPS_SPECS}
    base = _base()
    window, long_window = tuple(rules["windows"]["verification"]), tuple(rules["windows"]["long"])
    runs = {}
    for name in survivors:
        for phase in range(PHASES):
            run = f"v650_pool_{name}_p{phase}"
            runs[run] = make_run(run, eps_rows(specs[name], context, start=window[0], end=window[1], phase_index=phase), window, base)
        run = f"v650_pool_{name}_long"
        runs[run] = make_run(run, eps_rows(specs[name], context, start=long_window[0], end=long_window[1], phase_index=0), long_window, base)
    write_json(OUT / "eps_pool_runs.json", runs)
    (OUT / "eps_pool_run_list.txt").write_text(" ".join(f"ml/evaluation/run_configs/{name}.json" for name in runs) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(runs)} runs; frozen in vault commit {recorded['commit']}")
    return 0


def describe_run(run_dir: Path) -> dict:
    from evaluation.alpha_proof import alpha_regression, benchmark_daily_returns, sharpe, to_sessions
    from evaluation.lean_attribution import fills_from_order_events
    from evaluation.backtest_audit import load_backtest_run
    from v650_instrument import RUN_CONFIGS
    from v650_lean import ANNUALIZATION, strategy_series

    config = json.loads((RUN_CONFIGS / f"{run_dir.name}.json").read_text(encoding="utf-8"))
    series = strategy_series(run_dir, config)
    stats = lean_statistics(run_dir)
    stats["strategy_sharpe"] = sharpe(series.to_numpy(dtype=float), ANNUALIZATION)
    log = (run_dir / "log.txt").read_text(encoding="utf-8", errors="replace")
    stats["complete"] = "PythonInitializer.Shutdown(): start" in log and "Runtime Error" not in log
    benchmarks = benchmark_daily_returns(ROOT, config, start=str(series.index.min()), end=str(series.index.max()))
    alpha = alpha_regression(to_sessions(series, benchmarks.index), benchmarks)
    fills = [fill for fill in fills_from_order_events(load_backtest_run(run_dir).get("order_events", [])) if fill.ticker != "BIL"]
    stats.update(alpha_annual=alpha.get("alpha_annual"), alpha_t=alpha.get("t_hac"), betas=alpha.get("betas"), run=run_dir.name,
                 last_fill=fills[-1].date if fills else None)
    return stats


def stage_eps_judge(args) -> int:
    from v650_lean import judge_fallback

    done = {}
    for line in Path(args.status).read_text(encoding="utf-8-sig").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "LEAN_DONE" and parts[1].startswith("v650_pool_"):
            done[parts[1]] = ROOT / parts[2]
    previous = read_json(OUT / "r_lean19.json", {})
    pool = dict(previous["pool"])
    detail: dict[str, dict] = {}
    for name in read_json(RESULT, {}).get("survivors_after_correlation") or []:
        phases = {f"p{phase}": describe_run(done[f"v650_pool_{name}_p{phase}"]) for phase in range(PHASES)}
        long_run = describe_run(done[f"v650_pool_{name}_long"])
        detail[name] = {"phases": phases, "long": long_run}

        def median(key: str) -> float | None:
            values = [entry[key] for entry in phases.values() if entry.get(key) is not None]
            return float(np.median(values)) if values else None

        pool[name] = {key: median(key) for key in ("lean_sharpe", "strategy_sharpe", "annual_std", "drawdown_pct", "alpha_annual", "alpha_t")}
        pool[name].update(complete=all(entry["complete"] for entry in phases.values()), long_strategy_sharpe=long_run["strategy_sharpe"])
        append_trial(LEDGER, trial_id=name, track="pool", window="verification", role="verification", annualised_sharpe=pool[name]["strategy_sharpe"], n_obs=0, engine="lean",
                     detail={"lean_sharpe": pool[name]["lean_sharpe"]})
    verdict = judge_fallback(pool, previous["baseline"])
    write_json(OUT / "r_lean19_amended.json", {"baseline": previous["baseline"], "pool": pool, "verdict": verdict, "detail": detail})
    print(json.dumps({"best": verdict["best"], "install": verdict["install"], "pool_top": {name: pool[name] for name in sorted(pool, key=lambda n: -(pool[n]["strategy_sharpe"] or -9))[:3]},
                      "detail": detail}, indent=1, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    score = commands.add_parser("eps-score")
    score.add_argument("--draws", type=int, default=200)
    commands.add_parser("pbo")
    commands.add_parser("eps-pool")
    eps_judge = commands.add_parser("eps-judge")
    eps_judge.add_argument("--status", required=True)
    commands.add_parser("pre2013-make")
    judge = commands.add_parser("pre2013-judge")
    judge.add_argument("--status", required=True)
    args = parser.parse_args()
    return {"eps-score": stage_eps_score, "pbo": stage_pbo, "eps-pool": stage_eps_pool, "eps-judge": stage_eps_judge,
            "pre2013-make": stage_pre2013_make, "pre2013-judge": stage_pre2013_judge}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
