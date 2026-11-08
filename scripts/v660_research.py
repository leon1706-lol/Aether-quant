"""V6.6.0 selection, run on one of the free cells only (`evaluation/research_cells.py` refuses the rest).

    python scripts/v660_research.py score [--only w01 w02 ...]
    python scripts/v660_research.py placebo --draws 100 [--only ...] [--suffix _a]
    python scripts/v660_research.py gate
    python scripts/v660_research.py pbo
    python scripts/v660_research.py combine
    python scripts/v660_research.py blend      # m5, from m2, m3 and m4
    python scripts/v660_research.py vel        # R-VEL1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from v660_trials import ALL_SPECS, COMBINATION_IDS, CRYPTO_CORE, MIN_IC_NAMES, NO_IC_CLAUSE, PBO_COLUMNS, cell_of, min_live_names  # noqa: E402

from evaluation.premia_research import (  # noqa: E402
    annual_sharpe,
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
from evaluation.research_cells import CELLS, FREE_CELLS  # noqa: E402
from evaluation.trial_ledger import append_trial  # noqa: E402
from evaluation.wide_context import crypto_cell, equity_cell, signal_ic_t  # noqa: E402
from portfolio.premia_signals import combine_sleeves, sleeve_signal  # noqa: E402
from portfolio.wide_signals import live_names_per_rebalance  # noqa: E402

OUT = ROOT / "ml" / "evaluation" / "v660"
RULES = OUT / "rules.json"
RULES_SHA = OUT / "rules.sha256"
SCORES = OUT / "selection_scores.json"
DAILY = OUT / "selection_daily.parquet"
GATE = OUT / "selection_gate.json"
LEDGER = OUT / "trial_ledger.jsonl"
ML_SCORES = OUT / "scores"
WINDOW_LABEL = "v660_selection"


def check_rules() -> dict:
    """Every stage starts here: a changed rule file stops the phase."""
    payload = RULES.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    expected = RULES_SHA.read_text(encoding="utf-8").strip()
    if digest != expected:
        raise SystemExit(f"rules.json {digest} is not the recorded {expected}")
    return json.loads(payload)


def assert_selection_only(end: str) -> None:
    if end > max(CELLS[name].end for name in FREE_CELLS):
        raise SystemExit(f"{end} is past every selection cell")


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8", newline="\n")


def base_config() -> dict:
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def score_table(trial: str, index, columns) -> pd.DataFrame | None:
    """A model trial's score file, as of each session. Scores are on equities only, so no late-bar shift is needed here."""
    path = ML_SCORES / f"{trial}.csv"
    if not path.exists():
        return None
    table = pd.read_csv(path, dtype={"date": str, "ticker": str})
    return table.pivot_table(index="date", columns="ticker", values="score", aggfunc="last").reindex(index=index, columns=columns)


def load_cells(specs) -> dict[str, object]:
    """The cells these specs need, each once: building one takes minutes."""
    base = base_config()
    cells = {}
    for name in sorted({cell_of(spec) for spec in specs}):
        cells[name] = crypto_cell(ROOT, base, name) if CELLS[name].universe == "crypto" else equity_cell(ROOT, base, name)
        cell = cells[name]
        if cell.cell.universe == "equity":
            known = cell.context.panel.known
            # e3: a single asset on a volatility target. scale_and_cap sets the size.
            spy = pd.DataFrame(np.nan, index=known.index, columns=known.columns)
            spy["SPY"] = 1.0
            cell.context.panel.extras["e3"] = spy.where(known.notna())
            for trial in ("m1", "m2", "m3", "m4", "m5"):
                table = score_table(trial, known.index, known.columns)
                if table is not None:
                    cell.context.panel.extras[trial] = table.where(cell.member)
                    cell.tables[trial] = cell.context.panel.extras[trial]
        else:
            cell.context.panel.extras["c5"] = core_trend_table(cell.context.panel.known)
            cell.tables["c5"] = cell.context.panel.extras["c5"]
    return cells


def core_trend_table(known: pd.DataFrame) -> pd.DataFrame:
    """c5: the installed sleeve's votes, on BTC and ETH alone. Long while the trailing return is positive, over each lookback."""
    votes = [(known / known.shift(lookback) - 1.0 > 0.0).astype(float).where(known.shift(lookback).notna()) for lookback in (20, 60, 120)]
    table = sum(votes) / len(votes)
    table.loc[:, ~table.columns.isin(CRYPTO_CORE)] = np.nan
    return table


def _signal_for(spec, cell) -> pd.DataFrame | None:
    panel = cell.context.panel
    if spec.family == "external_score" and spec.params["table"] not in panel.extras:
        return None
    return sleeve_signal(spec, panel)


def _ic_clause(spec, cell, signal: pd.DataFrame) -> dict | None:
    if spec.id in NO_IC_CLAUSE or cell.cell.universe == "crypto":
        return None
    if cell.label is None:
        return None
    return signal_ic_t(signal, cell.label, start=cell.cell.start, end=cell.cell.end, min_names=MIN_IC_NAMES[spec.track])


def crypto_ic(spec, cell, signal: pd.DataFrame) -> dict | None:
    """c1-c4's rank IC with the next 28 days' return, on the same coins."""
    if spec.id in NO_IC_CLAUSE:
        return None
    from evaluation.wide_context import crypto_ic as shared_crypto_ic

    return shared_crypto_ic(signal, cell.context.panel.known, start=cell.cell.start, end=cell.cell.end, min_names=MIN_IC_NAMES["C"])


def stage_score(args) -> int:
    check_rules()
    specs = [spec for spec in ALL_SPECS if not args.only or spec.id in args.only]
    cells = load_cells(specs)
    scores = read_json(SCORES, {})
    frames = pd.read_parquet(DAILY).to_dict("series") if DAILY.exists() else {}
    for spec in specs:
        if spec.id in scores and not args.force:
            continue
        cell = cells[cell_of(spec)]
        signal = _signal_for(spec, cell)
        if signal is None:
            print(f"{spec.id:6s} has no table yet", flush=True)
            continue
        assert_selection_only(cell.cell.end)
        live = live_names_per_rebalance(signal.loc[signal.index >= cell.cell.start], spec.rebalance_every)
        if live["median"] < min_live_names(spec.id, spec.track):
            print(f"{spec.id:6s} ranks only {live['median']:.0f} names; minimum {min_live_names(spec.id, spec.track)}", flush=True)
        score = score_sleeve(spec, cell.context, start=cell.cell.start, split=cell.cell.split, end=cell.cell.end, signal=signal)
        daily = score.pop("daily")
        # one real path, as V6.5.0 kept: a median across phases per date isn't a return anyone could earn
        middle = daily[min(daily)]
        frames[spec.id] = middle
        ic = crypto_ic(spec, cell, signal) if cell.cell.universe == "crypto" else _ic_clause(spec, cell, signal)
        scores[spec.id] = {**score, "cell": cell.cell.name, "live_names": live, "ic": ic}
        append_trial(LEDGER, trial_id=spec.id, track=spec.track, window=WINDOW_LABEL, role="candidate", annualised_sharpe=score["sharpe"],
                     n_obs=len(middle), engine="offline", detail={"cell": cell.cell.name})
        write_json(SCORES, scores)
        pd.DataFrame(frames).sort_index().to_parquet(DAILY)
        print(f"{spec.id:6s} Sharpe {_show(score['sharpe'])} ({_show(score['sharpe_first_half'])}, {_show(score['sharpe_second_half'])}) IC t {_show((ic or {}).get('nonoverlap_t'))} live {live['median']:.0f}", flush=True)
    return 0


def _show(value) -> str:
    return "  n/a" if value is None else f"{value:5.2f}"


def passes_earlier_clauses(spec_id: str, track: str, score: dict) -> bool:
    if not passes_sharpe_clauses(score):
        return False
    if (score.get("live_names") or {}).get("median", 0.0) < min_live_names(spec_id, track):
        return False
    if spec_id in NO_IC_CLAUSE:
        return True
    t = (score.get("ic") or {}).get("nonoverlap_t")
    return t is not None and t >= 2.0


def stage_placebo(args) -> int:
    check_rules()
    scores = read_json(SCORES, {})
    specs = [spec for spec in ALL_SPECS if spec.id in scores and passes_earlier_clauses(spec.id, spec.track, scores[spec.id])]
    if args.only:
        specs = [spec for spec in specs if spec.id in args.only]
    if not specs:
        print("no trial reached the placebo clause")
        return 0
    cells = load_cells(specs)
    path = OUT / f"selection_placebos{args.suffix}.json"
    ledger = OUT / f"trial_ledger{args.suffix}_placebos.jsonl"
    done = read_json(path, {})
    for spec in specs:
        if spec.id in done and not args.force:
            continue
        cell = cells[cell_of(spec)]
        out = {}
        for mode in nulls_for(spec):
            sharpes = placebo_sharpes(spec, cell.context, mode, start=cell.cell.start, end=cell.cell.end, draws=args.draws)
            out[mode] = {"p": placebo_p_value(scores[spec.id]["sharpe"], sharpes), "draws": len(sharpes), "median": float(pd.Series(sharpes).median()) if sharpes else None,
                         "q95": float(pd.Series(sharpes).quantile(0.95)) if sharpes else None}
            print(f"{spec.id:6s} {mode:12s} p {out[mode]['p']:.3f} placebo median {_show(out[mode]['median'])} q95 {_show(out[mode]['q95'])}", flush=True)
            for sharpe in sharpes:
                append_trial(ledger, trial_id=f"{spec.id}:{mode}", track=spec.track, window=WINDOW_LABEL, role="placebo", annualised_sharpe=sharpe, n_obs=0, engine="offline")
        done[spec.id] = out
        write_json(path, done)
    return 0


def stage_gate(args) -> int:
    check_rules()
    scores = read_json(SCORES, {})
    placebos = {}
    for path in sorted(OUT.glob("selection_placebos*.json")):
        placebos.update(read_json(path, {}))
    daily = pd.read_parquet(DAILY)
    track = {spec.id: spec.track for spec in ALL_SPECS}
    eligible = {name: score for name, score in scores.items() if passes_earlier_clauses(name, track[name], score)}
    rows = [{**score, "id": name, "daily": {0: daily[name].dropna()}} for name, score in eligible.items() if name in daily]
    p_values = {name: {mode: entry["p"] for mode, entry in tests.items()} for name, tests in placebos.items()}
    gate = selection_gate(rows, p_values)
    gate["failed_earlier_clauses"] = {
        name: _why_failed(name, track[name], scores[name]) for name in scores if name not in eligible
    }
    gate["unscored"] = [spec.id for spec in ALL_SPECS if spec.id not in scores]
    write_json(GATE, gate)
    print(json.dumps({key: gate[key] for key in ("survivors", "failed", "unscored")}, indent=1))
    return 0


def _why_failed(name: str, track: str, score: dict) -> str:
    if (score.get("live_names") or {}).get("median", 0.0) < min_live_names(name, track):
        return "live_names"
    if not passes_sharpe_clauses(score):
        return "sharpe"
    return "ic"


def stage_pbo(args) -> int:
    from evaluation.pbo import probability_of_backtest_overfitting

    check_rules()
    daily = pd.read_parquet(DAILY)
    columns = [name for name in PBO_COLUMNS if name in daily.columns]
    window = CELLS["S"]
    matrix = daily[columns]
    matrix = matrix[(matrix.index >= window.start) & (matrix.index <= window.end)].dropna(how="all").fillna(0.0)
    result = probability_of_backtest_overfitting(matrix.to_numpy(dtype=float), blocks=16, periods_per_year=252)
    report = {"pbo": result.get("pbo"), "num_trials": len(columns), "missing": [name for name in PBO_COLUMNS if name not in daily.columns], "window": f"{window.start}..{window.end}", **{k: v for k, v in result.items() if k != "pbo"}}
    write_json(OUT / "selection_pbo.json", report)
    print(json.dumps(report, indent=1, default=str))
    return 0


def stage_combine(args) -> int:
    """t1 and t2 over the survivors plus the installed sleeve, on cell S. Weights are never fitted to returns."""
    check_rules()
    gate = read_json(GATE, {})
    survivors = gate.get("survivors") or []
    if not survivors:
        print("no survivor: the verdict follows at once")
        return 0
    specs = {spec.id: spec for spec in ALL_SPECS}
    equity = [name for name in survivors if cell_of(specs[name]) == "S"]
    if not equity:
        print("no equity survivor: the candidate is crypto only, combination is the survivor(s) alone")
        return 0
    cells = load_cells([specs[name] for name in equity])
    cell = cells["S"]
    window = cell.cell
    sleeves = {}
    for name in equity:
        spec = specs[name]
        sleeves[name] = weights_for(spec, cell.context, sleeve_signal(spec, cell.context.panel), start=window.start, end=window.end, phase_offset=phase_offsets(spec.rebalance_every)[0])
    results = {}
    sessions = cell.context.market.sessions
    for name, method in zip(COMBINATION_IDS, ("inverse_vol", "hrp")):
        rows = combine_sleeves(sleeves, cell.context.panel, method=method, settings=cell.context.settings, start=window.start, end=window.end)
        strategy = cell.context.simulate(rows, window.start, window.end)["strategy_excess"]
        results[name] = {
            "sharpe": annual_sharpe(strategy, sessions=sessions), "first_half": annual_sharpe(strategy[strategy.index < window.split], sessions=sessions),
            "second_half": annual_sharpe(strategy[strategy.index >= window.split], sessions=sessions), "max_drawdown": max_drawdown(strategy),
        }
        append_trial(LEDGER, trial_id=name, track="T", window=WINDOW_LABEL, role="candidate", annualised_sharpe=results[name]["sharpe"], n_obs=len(strategy), engine="offline", detail={"cell": "S", "survivors": equity})
        print(name, results[name], flush=True)
    write_json(OUT / "selection_combination.json", {"survivors": survivors, "equity_survivors": equity, "results": results})
    return 0


def stage_blend(args) -> int:
    """m5: the equal rank mean of m2, m3 and m4, or of m2 and m4 if rules.json's compute bound closed m3. Never fitted."""
    check_rules()
    parts = [name for name in ("m2", "m3", "m4") if (ML_SCORES / f"{name}.csv").exists()]
    if len(parts) < 2:
        print(f"m5 needs two parts, has {parts}")
        return 1
    ranked = []
    for name in parts:
        table = pd.read_csv(ML_SCORES / f"{name}.csv", dtype={"date": str, "ticker": str})
        table["rank"] = table.groupby("date")["score"].rank(pct=True)
        ranked.append(table.set_index(["date", "ticker"])["rank"])
    mean = pd.concat(ranked, axis=1).mean(axis=1, skipna=False).dropna().rename("score").reset_index()
    mean.to_csv(ML_SCORES / "m5.csv", index=False, lineterminator="\n", float_format="%.6f")
    print(f"m5 from {parts}: {len(mean)} rows")
    return 0


def stage_vel(args) -> int:
    """R-VEL1, on the installed sleeve's own panel and weight file."""
    from evaluation.premia_research import build_context
    from portfolio.target_weights import load_weight_file

    check_rules()
    base = base_config()
    context = build_context(ROOT, base)
    # the installed rule over the 12 years V6.5.0 ran it: the installed file itself starts in 2023-07
    weights = load_weight_file(ROOT / "ml" / "evaluation" / "v650" / "weights" / "v650_pool_t3_crypto_trend_blend_long.csv")
    start, end = "2014-12-01", "2026-11-02"
    target_vol = 0.07

    def run(velocity):
        result = context.simulate(weights, start, end, max_drawdown_velocity=velocity, max_total_drawdown=0.15)
        strategy = result["strategy"]
        five_day = (1.0 + strategy).rolling(5).apply(np.prod, raw=True) - 1.0
        locked = result.get("locked_on")
        rows = [date for date in strategy.index]
        trading_share = (sum(1 for date in rows if locked is None or date <= locked) / len(rows)) if rows else 0.0
        return {"velocity": velocity, "locked_on": locked, "sharpe": annual_sharpe(strategy), "worst_5_day": float(five_day.min()), "share_of_sessions_trading": trading_share, "max_drawdown": max_drawdown(strategy)}

    off = run(None)
    report = {"off": off, "options": {}}
    adopted = None
    for k in (5, 8):
        velocity = k * target_vol / math.sqrt(252.0)
        row = run(velocity)
        row["cuts_worst_5_day_by"] = 1.0 - row["worst_5_day"] / off["worst_5_day"] if off["worst_5_day"] else 0.0
        row["passes"] = row["share_of_sessions_trading"] >= 0.95 and row["cuts_worst_5_day_by"] >= 0.20
        report["options"][str(k)] = row
        if row["passes"] and adopted is None:
            adopted = k
    report["adopted_k"] = adopted
    report["decision"] = f"velocity lock at k={adopted}" if adopted else "velocity stays off, by rule"
    write_json(OUT / "r_vel1.json", report)
    print(json.dumps(report, indent=1, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="stage", required=True)
    score = commands.add_parser("score")
    score.add_argument("--only", nargs="*", default=None)
    score.add_argument("--force", action="store_true")
    placebo = commands.add_parser("placebo")
    placebo.add_argument("--draws", type=int, default=100)
    placebo.add_argument("--only", nargs="*", default=None)
    placebo.add_argument("--suffix", default="")
    placebo.add_argument("--force", action="store_true")
    for name in ("gate", "pbo", "combine", "vel", "blend"):
        commands.add_parser(name)
    args = parser.parse_args()
    return {"score": stage_score, "placebo": stage_placebo, "gate": stage_gate, "pbo": stage_pbo, "combine": stage_combine, "vel": stage_vel, "blend": stage_blend}[args.stage](args)


if __name__ == "__main__":
    raise SystemExit(main())
