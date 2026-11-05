"""V6.5.0 from selection to verdict: weight files and run configs of a frozen candidate, and the R-EDGE1 / R-LEAN19 judgements.

    python scripts/v650_lean.py g2                    # the R-LEAN20 run over the selection window
    python scripts/v650_lean.py freeze                # hashes the candidate and records it, before any later row exists
    python scripts/v650_lean.py verify                # E1 (5 phases), E2, E4 (40 placebos per null), E5 (+ 20 placebos)
    python scripts/v650_lean.py pool                  # R-LEAN19: every survivor alone and the combination, 5 phases + the long window
    python scripts/v650_lean.py judge --status status.txt

`freeze` must run before `verify` and `pool`: they generate rows after 2023-06-30, and refuse without a matching freeze.
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

from build_pre2013_root import universe_for_root  # noqa: E402
from v650_instrument import RUN_CONFIGS, WEIGHTS, target_path_config  # noqa: E402
from v650_research import GATE, OUT, check_rules, load_context, read_json, write_json  # noqa: E402
from v650_trials import ALL_SPECS  # noqa: E402

from evaluation.premia_research import build_context, nulls_for, phase_offsets, weights_for  # noqa: E402
from evaluation.trial_ledger import append_trial, deflation_inputs, read_ledger  # noqa: E402
from portfolio.premia_signals import ResearchPanel, combine_sleeves, null_signal, sleeve_signal  # noqa: E402
from portfolio.target_weights import write_weight_file  # noqa: E402

FREEZE = OUT / "freeze.json"
LEDGER = OUT / "trial_ledger.jsonl"
SPECS = {spec.id: spec for spec in ALL_SPECS}
PHASES = 5
E4_DRAWS = 40
E5_DRAWS = 20
ANNUALIZATION = 365.0


def candidate_definition() -> dict:
    """The survivors and the combination method chosen on the selection window (rule T6)."""
    gate = read_json(GATE, {})
    survivors = gate.get("survivors") or []
    if not survivors:
        raise SystemExit("no survivor: nothing to verify; R-LEAN19 runs on the ablations")
    if len(survivors) == 1:
        return {"survivors": survivors, "method": None}
    combination = read_json(OUT / "selection_combination.json", {})
    results = combination.get("results") or {}
    if not results:
        raise SystemExit("run `v650_research.py combine` first")
    best = max(results, key=lambda name: results[name]["sharpe"] if results[name]["sharpe"] is not None else -math.inf)
    return {"survivors": survivors, "method": {"t6_inverse_vol": "inverse_vol", "t6_hrp": "hrp"}[best], "chosen": best}


def candidate_rows(definition: dict, context, *, start: str, end: str, phase_index: int, null_mode: str | None = None, seed: int = 0) -> dict:
    """Target weights of the candidate on [start, end]. `null_mode` removes the skill from every sleeve's signal with the
    same pipeline after it, which is what makes a placebo comparable."""
    sleeves = {}
    for name in definition["survivors"]:
        spec = SPECS[name]
        signal = sleeve_signal(spec, context.panel)
        if null_mode:
            mode = null_mode if null_mode in nulls_for(spec) else "sign_block"
            signal = null_signal(signal, mode, seed=seed, asset_class=context.panel.asset_class)
        offsets = phase_offsets(spec.rebalance_every, PHASES)
        offset = offsets[phase_index % len(offsets)]
        sleeves[name] = weights_for(spec, context, signal, start=start, end=end, phase_offset=offset)
    if definition["method"] is None:
        return sleeves[definition["survivors"][0]]
    return combine_sleeves(sleeves, context.panel, method=definition["method"], settings=context.settings, start=start, end=end)


def make_run(name: str, rows: dict, window: tuple[str, str], base: dict, *, data_root: str | None = None, sweep: bool = True) -> dict:
    """Writes the run's weight file and frozen config (and which data root it reads)."""
    WEIGHTS.mkdir(parents=True, exist_ok=True)
    sha = write_weight_file(rows, WEIGHTS / f"{name}.csv")
    config = target_path_config(base, weights_path=f"ml/evaluation/v650/weights/{name}.csv", weights_sha256=sha, window=window)
    if not sweep:
        config["phase_v2"]["cash_sweep"]["enabled"] = False
    text = json.dumps(config, indent=4)
    (RUN_CONFIGS / f"{name}.json").write_text(text, encoding="utf-8", newline="\n")
    if data_root:
        (RUN_CONFIGS / f"{name}.dataroot").write_text(data_root + "\n", encoding="utf-8", newline="\n")
    return {"name": name, "weights_sha": sha, "config_sha": hashlib.sha256(text.encode("utf-8")).hexdigest(), "rows": len(rows)}


def _base() -> dict:
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def freeze_digest(definition: dict) -> dict:
    code = ["portfolio/premia_signals.py", "portfolio/target_weights.py", "portfolio/financing.py", "evaluation/target_weights_engine.py",
            "evaluation/premia_research.py", "scripts/v650_trials.py", "scripts/v650_lean.py", "main.py"]
    return {"candidate": definition, "code": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in code}}


def stage_g2(args) -> int:
    rules = check_rules()
    definition = candidate_definition()
    context = load_context()
    start, end = rules["windows"]["selection_lean"]
    rows = candidate_rows(definition, context, start=start, end=end, phase_index=0)
    print(json.dumps(make_run("v650_g2", rows, (start, end), _base()), indent=1))
    return 0


def stage_freeze(args) -> int:
    check_rules()
    definition = candidate_definition()
    digest = freeze_digest(definition)
    write_json(FREEZE, digest)
    from vault_record import record

    recorded = record("freeze", ["ml/evaluation/v650/freeze.json", "ml/evaluation/v650/selection_gate.json"], {"survivors": float(len(definition["survivors"]))})
    print(json.dumps({**digest, "vault": recorded}, indent=1))
    return 0 if recorded["ok"] else 1


def check_freeze() -> dict:
    frozen = read_json(FREEZE, None)
    if frozen is None:
        raise SystemExit("no freeze.json: run `v650_lean.py freeze` before any row after the selection window")
    now = freeze_digest(frozen["candidate"])
    if now["code"] != frozen["code"]:
        changed = [path for path in now["code"] if now["code"][path] != frozen["code"][path]]
        raise SystemExit(f"code changed since the freeze: {changed}")
    return frozen["candidate"]


def pre2013_context(base: dict):
    manifest = json.loads((ROOT / "data_pre2013" / "pre2013_manifest.json").read_text(encoding="utf-8"))
    config = universe_for_root(base, manifest)
    return build_context(ROOT, config, data_dir="data_pre2013"), config


def stage_verify(args) -> int:
    rules = check_rules()
    definition = check_freeze()
    base = _base()
    runs: dict[str, dict] = {}
    context = load_context()
    window = tuple(rules["windows"]["verification"])
    for phase in range(PHASES):
        runs[f"v650_e1_p{phase}"] = make_run(f"v650_e1_p{phase}", candidate_rows(definition, context, start=window[0], end=window[1], phase_index=phase), window, base)
    long_window = tuple(rules["windows"]["long"])
    runs["v650_e2"] = make_run("v650_e2", candidate_rows(definition, context, start=long_window[0], end=long_window[1], phase_index=0), long_window, base)
    rng = np.random.default_rng(650)
    for mode in ("null_a", "null_b"):
        for draw in range(E4_DRAWS):
            name = f"v650_e4_{mode}_{draw:02d}"
            null_mode = "time_shift" if mode == "null_b" else "asset_block"
            rows = candidate_rows(definition, context, start=window[0], end=window[1], phase_index=int(rng.integers(PHASES)), null_mode=null_mode, seed=1_000 + draw)
            runs[name] = make_run(name, rows, window, base)
    early, config = pre2013_context(base)
    early_window = tuple(rules["windows"]["pre2013"])
    available = [name for name in definition["survivors"] if SPECS[name].universe != ("crypto",)]
    early_definition = {**definition, "survivors": available}
    if available:
        # a crypto sleeve has no bars before 2014 and an ML sleeve no scores: their weight goes to what can run (disclosed in rules.json)
        if len(available) == 1:
            early_definition["method"] = None
        runs["v650_e5"] = make_run("v650_e5", candidate_rows(early_definition, early, start=early_window[0], end=early_window[1], phase_index=0),
                                   early_window, config, data_root="data_pre2013", sweep=False)
        for draw in range(E5_DRAWS):
            name = f"v650_e5_null_{draw:02d}"
            rows = candidate_rows(early_definition, early, start=early_window[0], end=early_window[1], phase_index=int(rng.integers(PHASES)),
                                  null_mode="time_shift", seed=2_000 + draw)
            runs[name] = make_run(name, rows, early_window, config, data_root="data_pre2013", sweep=False)
    write_json(OUT / "verify_runs.json", runs)
    print(f"{len(runs)} runs written; E5 sleeves: {available}")
    (OUT / "verify_run_list.txt").write_text(" ".join(f"ml/evaluation/run_configs/{name}.json" for name in runs) + "\n", encoding="utf-8", newline="\n")
    return 0


def stage_pool(args) -> int:
    rules = check_rules()
    check_freeze()
    survivors = (read_json(GATE, {}).get("survivors") or [])
    base = _base()
    context = load_context()
    window = tuple(rules["windows"]["verification"])
    long_window = tuple(rules["windows"]["long"])
    runs = {}
    members = {name: {"survivors": [name], "method": None} for name in survivors}
    combination = candidate_definition()
    if combination["method"] is not None:
        members[combination["chosen"]] = combination
    for name, definition in members.items():
        for phase in range(PHASES):
            run = f"v650_pool_{name}_p{phase}"
            runs[run] = make_run(run, candidate_rows(definition, context, start=window[0], end=window[1], phase_index=phase), window, base)
        run = f"v650_pool_{name}_long"
        runs[run] = make_run(run, candidate_rows(definition, context, start=long_window[0], end=long_window[1], phase_index=0), long_window, base)
    write_json(OUT / "pool_runs.json", runs)
    (OUT / "pool_run_list.txt").write_text(" ".join(f"ml/evaluation/run_configs/{name}.json" for name in runs) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(runs)} pool runs written")
    return 0


def lean_statistics(run_dir: Path) -> dict:
    from evaluation.backtest_audit import load_backtest_run

    run = load_backtest_run(run_dir)
    stats = run["result"].get("statistics") or run["result"].get("Statistics") or {}
    def number(key: str) -> float | None:
        text = str(stats.get(key, "")).replace("%", "").replace("$", "").replace(",", "")
        try:
            return float(text)
        except ValueError:
            return None
    return {"lean_sharpe": number("Sharpe Ratio"), "annual_std": number("Annual Standard Deviation"), "drawdown_pct": number("Drawdown"),
            "net_profit_pct": number("Net Profit"), "orders": number("Total Orders"), "fees": number("Total Fees")}


def strategy_series(run_dir: Path, config: dict, *, data_dir: str = "data") -> pd.Series:
    """The ex-T-bill daily return of a run; with no sweep (the pre-2013 run) it is the NAV's daily return."""
    from evaluation.alpha_proof import strategy_daily_returns
    from evaluation.backtest_audit import daily_equity_from_chart, load_backtest_run

    run = load_backtest_run(run_dir)
    if data_dir != "data" or not config["phase_v2"]["cash_sweep"]["enabled"]:
        points = daily_equity_from_chart(run["result"])
        return pd.Series(dict(points), dtype=float).sort_index().pct_change().dropna()
    return strategy_daily_returns(run, config, ROOT)


def stage_judge(args) -> int:
    """R-LEAN19 over the pool. `--status` is the runner's status file; the gated ablations come from ablation_table.json."""
    check_rules()
    from evaluation.alpha_proof import alpha_regression, benchmark_daily_returns, sharpe, to_sessions

    done = {}
    for line in Path(args.status).read_text(encoding="utf-8-sig").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "LEAN_DONE":
            done[parts[1]] = ROOT / parts[2]
    members: dict[str, dict] = {}
    for run, run_dir in done.items():
        if not run.startswith("v650_pool_"):
            continue
        name, _, tail = run[len("v650_pool_"):].rpartition("_")
        members.setdefault(name, {"phases": {}, "long": None})
        if tail == "long":
            members[name]["long"] = run_dir
        else:
            members[name]["phases"][tail] = run_dir

    def describe(run_dir: Path) -> dict:
        config = json.loads((RUN_CONFIGS / f"{run_dir.name}.json").read_text(encoding="utf-8"))
        y = strategy_series(run_dir, config)
        stats = lean_statistics(run_dir)
        stats["strategy_sharpe"] = sharpe(y.to_numpy(dtype=float), ANNUALIZATION)
        log = (run_dir / "log.txt").read_text(encoding="utf-8", errors="replace")
        stats["complete"] = "PythonInitializer.Shutdown(): start" in log and "Runtime Error" not in log
        benchmarks = benchmark_daily_returns(ROOT, config, start=str(y.index.min()), end=str(y.index.max()))
        alpha = alpha_regression(to_sessions(y, benchmarks.index), benchmarks)
        stats["alpha_annual"], stats["alpha_t"] = alpha.get("alpha_annual"), alpha.get("t_hac")
        stats["betas"] = alpha.get("betas")
        stats["locked"] = "total_drawdown_limit_breached" in log or "kill_switch" in log
        stats["run"] = run_dir.name
        return stats

    pool: dict[str, dict] = {}
    detail: dict[str, dict] = {}
    for name, runs in sorted(members.items()):
        phases = {phase: describe(run_dir) for phase, run_dir in sorted(runs["phases"].items())}
        detail[name] = {"phases": phases}
        def median(key: str) -> float | None:
            values = [entry[key] for entry in phases.values() if entry.get(key) is not None]
            return float(np.median(values)) if values else None
        entry = {key: median(key) for key in ("lean_sharpe", "strategy_sharpe", "annual_std", "drawdown_pct", "alpha_annual", "alpha_t")}
        entry["complete"] = all(item["complete"] for item in phases.values()) and len(phases) == PHASES
        entry["worst_phase_drawdown_pct"] = max(item["drawdown_pct"] or 0.0 for item in phases.values())
        if runs["long"] is not None:
            detail[name]["long"] = describe(runs["long"])
            entry["long_strategy_sharpe"] = detail[name]["long"]["strategy_sharpe"]
        pool[name] = entry
        append_trial(LEDGER, trial_id=name, track="pool", window="verification", role="verification" if name in SPECS else "candidate",
                     annualised_sharpe=entry["strategy_sharpe"], n_obs=0, engine="lean", detail={"lean_sharpe": entry["lean_sharpe"]})
    table = read_json(OUT / "ablation_table.json", {})
    baseline_row = table["BT11 baseline"]
    baseline = {"lean_sharpe": baseline_row["lean_sharpe"], "strategy_sharpe": baseline_row["strategy_sharpe"]}
    for label, row in table.items():
        if label.startswith("BT") and label not in ("BT11 baseline", "BT12 flag off"):
            pool[label] = {"lean_sharpe": row["lean_sharpe"], "strategy_sharpe": row["strategy_sharpe"], "annual_std": row["annual_std"],
                           "drawdown_pct": row["drawdown_pct"], "complete": row["complete"], "long_strategy_sharpe": None}
    verdict = judge_fallback(pool, baseline)
    write_json(OUT / "r_lean19.json", {"baseline": baseline, "pool": pool, "verdict": verdict, "detail": detail})
    for name, entry in sorted(pool.items(), key=lambda item: -(item[1]["strategy_sharpe"] or -9)):
        print(f"{name:26s} lean {entry['lean_sharpe']:6.3f} strat {entry['strategy_sharpe']:6.3f} vol {entry['annual_std']:.3f} dd {entry['drawdown_pct']:5.1f} "
              f"alpha {entry.get('alpha_annual')} t {entry.get('alpha_t')} long {entry.get('long_strategy_sharpe')}")
    print(json.dumps(verdict, indent=1))
    return 0


def judge_edge(e1: list[float | None], e2_t: float | None, dsr: float | None, null_a: list[float], null_b: list[float], candidate_sharpe: float | None,
               early_sharpe: float | None, early_alpha: float | None) -> dict:
    """R-EDGE1 as a pure function of the figures."""
    usable = [value for value in e1 if value is not None]
    e1_median = float(np.median(usable)) if len(usable) == len(e1) and usable else None
    beaten_a = sum(value >= candidate_sharpe for value in null_a) if candidate_sharpe is not None else None
    beaten_b = sum(value >= candidate_sharpe for value in null_b) if candidate_sharpe is not None else None
    clauses = {
        "E1": e1_median is not None and e1_median >= 1.0,
        "E2": e2_t is not None and e2_t >= 3.0,
        "E3": dsr is not None and dsr >= 0.95,
        "E4": beaten_a is not None and len(null_a) >= E4_DRAWS and len(null_b) >= E4_DRAWS and beaten_a <= 1 and beaten_b <= 1,
        "E5": early_sharpe is not None and early_alpha is not None and early_sharpe > 0.0 and early_alpha > 0.0,
    }
    return {"verified": all(clauses.values()), "clauses": clauses, "e1_median": e1_median, "beaten_by_null_a": beaten_a, "beaten_by_null_b": beaten_b}


def judge_fallback(pool: dict[str, dict], baseline: dict) -> dict:
    """R-LEAN19: the best by median ex-T-bill Sharpe installs iff it clears every clause; otherwise nothing changes."""
    def clauses(entry: dict) -> dict:
        return {
            "lean_sharpe": entry.get("lean_sharpe") is not None and entry["lean_sharpe"] >= baseline["lean_sharpe"] + 0.10,
            "strategy_sharpe": entry.get("strategy_sharpe") is not None and entry["strategy_sharpe"] >= baseline["strategy_sharpe"] + 0.10,
            "vol": entry.get("annual_std") is not None and entry["annual_std"] <= 0.10,
            "drawdown": entry.get("drawdown_pct") is not None and entry["drawdown_pct"] <= 15.0,
            "complete": bool(entry.get("complete")),
            "long_window": entry.get("long_strategy_sharpe") is None or entry["long_strategy_sharpe"] > 0.0,
        }
    ranked = sorted(pool, key=lambda name: pool[name]["strategy_sharpe"] if pool[name].get("strategy_sharpe") is not None else -math.inf, reverse=True)
    table = {name: clauses(pool[name]) for name in ranked}
    best = ranked[0] if ranked else None
    return {"best": best, "install": best if best is not None and all(table[best].values()) else None, "clauses": table}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("g2", "freeze", "verify", "pool"):
        commands.add_parser(name)
    judge = commands.add_parser("judge")
    judge.add_argument("--status", required=True)
    args = parser.parse_args()
    return {"g2": stage_g2, "freeze": stage_freeze, "verify": stage_verify, "pool": stage_pool, "judge": stage_judge}[args.command](args)


__all__ = ["ResearchPanel", "append_trial", "deflation_inputs", "judge_edge", "judge_fallback", "read_ledger"]

if __name__ == "__main__":
    raise SystemExit(main())
