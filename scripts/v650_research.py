"""V6.5.0 selection on the offline engine: scores, placebos, the gate (rule R-SLEEVE2), the combination (T6).

    python scripts/v650_research.py score --tracks T3 T4
    python scripts/v650_research.py placebo --draws 200
    python scripts/v650_research.py gate

Every stage refuses to run when rules.json no longer matches its hash, and nothing here reads past the selection window
(`assert_selection_only`). Scores go to selection_scores.json (never `research.json`: the trial registry globs that name).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from evaluation.premia_research import (  # noqa: E402
    annual_sharpe,
    build_context,
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
from evaluation.trial_ledger import append_trial  # noqa: E402
from portfolio.premia_signals import ResearchPanel, combine_sleeves, sleeve_signal  # noqa: E402
from v650_trials import ALL_SPECS, COMBINATION_IDS  # noqa: E402

OUT = ROOT / "ml" / "evaluation" / "v650"
SCORES = OUT / "selection_scores.json"
DAILY = OUT / "selection_daily.parquet"
PLACEBOS = OUT / "selection_placebos.json"
GATE = OUT / "selection_gate.json"
LEDGER = OUT / "trial_ledger.jsonl"
ML_SCORES = OUT / "scores"
SELECTION_END = "2023-06-30"


def check_rules() -> dict:
    text = (OUT / "rules.json").read_text(encoding="utf-8")
    expected = (OUT / "rules.sha256").read_text(encoding="utf-8").strip()
    actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if actual != expected:
        raise SystemExit(f"rules.json changed: {actual} is not the recorded {expected}")
    return json.loads(text)


def assert_selection_only(end: str) -> None:
    if end > SELECTION_END:
        raise SystemExit(f"{end} is past the selection window ({SELECTION_END})")


def window_of(spec, rules: dict) -> tuple[str, str, str]:
    key = "ml_sleeves" if spec.track in ("T2", "T5") else "rule_sleeves"
    start, split, end = rules["selection_windows"][key]
    assert_selection_only(end)
    return start, split, end


def load_context():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    context = build_context(ROOT, config)
    extras = dict(context.panel.extras)
    sessions = context.panel.known.index
    if ML_SCORES.exists():
        for path in sorted(ML_SCORES.glob("*.csv")):
            table = pd.read_csv(path, dtype={"date": str, "ticker": str})
            table = table[table["date"] <= SELECTION_END]
            extras[path.stem] = table.pivot_table(index="date", columns="ticker", values="score", aggfunc="last").reindex(sessions)
    context.panel = ResearchPanel(context.panel.known, context.panel.asset_class, context.panel.fred, extras)
    return context


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8", newline="\n")


def stage_score(args) -> int:
    rules = check_rules()
    context = load_context()
    scores = read_json(SCORES, {})
    frames = {}
    if DAILY.exists():
        stored = pd.read_parquet(DAILY)
        frames = {column: stored[column].dropna() for column in stored.columns}
    for spec in ALL_SPECS:
        if spec.track not in args.tracks or spec.id in scores and not args.force:
            continue
        table = spec.params.get("table")
        if table is not None and table not in context.panel.extras:
            print(f"{spec.id}: no table {table} yet", flush=True)
            continue
        start, split, end = window_of(spec, rules)
        score = score_sleeve(spec, context, start=start, split=split, end=end)
        daily = score.pop("daily")
        frames[spec.id] = daily[min(daily)]
        scores[spec.id] = score
        append_trial(LEDGER, trial_id=spec.id, track=spec.track, window="selection", role="candidate", annualised_sharpe=score["sharpe"],
                     n_obs=len(frames[spec.id]), engine="offline")
        print(f"{spec.id:28s} sharpe {_show(score['sharpe'])}  h1 {_show(score['sharpe_first_half'])}  h2 {_show(score['sharpe_second_half'])}  "
              f"dd {score['max_drawdown']:.3f}  turn {score['turnover']:.1f}  gross {score['mean_gross']:.2f}", flush=True)
    write_json(SCORES, scores)
    pd.DataFrame(frames).sort_index().to_parquet(DAILY)
    return 0


def _show(value) -> str:
    return "  n/a" if value is None else f"{value:5.2f}"


def stage_placebo(args) -> int:
    rules = check_rules()
    context = load_context()
    scores = read_json(SCORES, {})
    placebos_path = PLACEBOS.with_name(f"selection_placebos{args.suffix}.json")
    ledger_path = LEDGER.with_name(f"trial_ledger{args.suffix}.jsonl")
    done = read_json(placebos_path, {})
    for spec in ALL_SPECS:
        score = scores.get(spec.id)
        if score is None or not passes_sharpe_clauses(score) or (spec.id in done and not args.force):
            continue
        if args.only and spec.id not in args.only:
            continue
        start, _, end = window_of(spec, rules)
        out = {}
        for mode in nulls_for(spec):
            sharpes = placebo_sharpes(spec, context, mode, start=start, end=end, draws=args.draws)
            out[mode] = {"p": placebo_p_value(score["sharpe"], sharpes), "draws": len(sharpes),
                         "median": float(pd.Series(sharpes).median()) if sharpes else None,
                         "q95": float(pd.Series(sharpes).quantile(0.95)) if sharpes else None}
            print(f"{spec.id:28s} {mode:12s} p {out[mode]['p']:.3f}  placebo median {_show(out[mode]['median'])} q95 {_show(out[mode]['q95'])}", flush=True)
            for sharpe in sharpes:
                append_trial(ledger_path, trial_id=f"{spec.id}:{mode}", track=spec.track, window="selection", role="placebo",
                             annualised_sharpe=sharpe, n_obs=0, engine="offline")
        done[spec.id] = out
        write_json(placebos_path, done)
    return 0


def stage_gate(args) -> int:
    check_rules()
    scores = read_json(SCORES, {})
    placebos = {}
    for path in sorted(OUT.glob("selection_placebos*.json")):
        placebos.update(read_json(path, {}))
    daily = pd.read_parquet(DAILY)
    rows = [{**score, "daily": {0: daily[name].dropna()}} for name, score in scores.items() if name in daily]
    p_values = {name: {mode: entry["p"] for mode, entry in tests.items()} for name, tests in placebos.items()}
    gate = selection_gate(rows, p_values)
    unscored = [spec.id for spec in ALL_SPECS if spec.id not in scores]
    gate["unscored"] = unscored
    write_json(GATE, gate)
    print(json.dumps(gate, indent=1))
    return 0


def stage_combine(args) -> int:
    """T6 over the survivors, on the selection window. A single survivor is its own combination."""
    rules = check_rules()
    gate = read_json(GATE, {})
    survivors = gate.get("survivors") or []
    if not survivors:
        print("no survivor: R-LEAN19 directly")
        return 0
    context = load_context()
    specs = {spec.id: spec for spec in ALL_SPECS}
    start, split, end = rules["selection_windows"]["rule_sleeves"]
    assert_selection_only(end)
    sleeves = {}
    for name in survivors:
        spec = specs[name]
        signal = sleeve_signal(spec, context.panel)
        sleeves[name] = weights_for(spec, context, signal, start=start, end=end, phase_offset=phase_offsets(spec.rebalance_every)[0])
    results = {}
    for name, method in zip(COMBINATION_IDS, ("inverse_vol", "hrp")):
        rows = combine_sleeves(sleeves, context.panel, method=method, settings=context.settings, start=start, end=end)
        strategy = context.simulate(rows, start, end)["strategy"]
        results[name] = {"sharpe": annual_sharpe(strategy), "first_half": annual_sharpe(strategy[strategy.index < split]),
                         "second_half": annual_sharpe(strategy[strategy.index >= split]), "max_drawdown": max_drawdown(strategy)}
        append_trial(LEDGER, trial_id=name, track="T6", window="selection", role="candidate", annualised_sharpe=results[name]["sharpe"],
                     n_obs=len(strategy), engine="offline")
        print(name, results[name], flush=True)
    write_json(OUT / "selection_combination.json", {"survivors": survivors, "results": results})
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    score = commands.add_parser("score")
    score.add_argument("--tracks", nargs="+", default=["T3", "T4"])
    score.add_argument("--force", action="store_true")
    placebo = commands.add_parser("placebo")
    placebo.add_argument("--draws", type=int, default=200)
    placebo.add_argument("--force", action="store_true")
    placebo.add_argument("--only", nargs="*", default=None, help="sleeve ids, to split the work across hosts")
    placebo.add_argument("--suffix", default="", help="output file suffix of this host's part; `gate` merges every part")
    commands.add_parser("gate")
    commands.add_parser("combine")
    args = parser.parse_args()
    return {"score": stage_score, "placebo": stage_placebo, "gate": stage_gate, "combine": stage_combine}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
