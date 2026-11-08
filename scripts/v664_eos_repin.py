"""EOS leaves the book (V6.6.4, Problems #311): the installed sleeve re-pinned without the coin Coinbase delisted.

The rule is unchanged: `t3_crypto_trend_blend`, the same code, the same windows as V6.5.0's pool (`ml/evaluation/v650/rules.json`). Only the universe loses EOSUSD, so the five rebalance phases
and the long run are rebuilt and run in Lean, and the median phase is installed by R-LEAN19's rule, exactly as `scripts/v650_install.py` did. The owner decided this on 2026-11-07, so the result is
reported beside the old pin and not judged against it.

    python scripts/v664_eos_repin.py reproduce             # with EOS, as installed: today's code must rebuild the installed weight file byte for byte
    python scripts/v664_eos_repin.py make                  # drop EOSUSD from config.json, write the five phase runs and the long run
    python scripts/v664_eos_repin.py install --status S    # S: the Lean runner's status file; installs the median phase and records the comparison
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402
from v650_install import INSTALLED_CANDIDATE, INSTALLED_WEIGHTS, median_phase  # noqa: E402
from v650_instrument import RUN_CONFIGS  # noqa: E402
from v650_lean import PHASES, candidate_rows, freeze_digest, lean_statistics, make_run, strategy_series  # noqa: E402
from v650_research import check_rules, load_context  # noqa: E402

COIN = "EOSUSD"
NAME = "t3_crypto_trend_blend"
OUT = ROOT / "ml" / "evaluation" / "v664"
ANNUALIZATION = 365.0


def drop_coin(config: dict, coin: str = COIN) -> dict:
    """The config without the coin's asset entry. Nothing else changes."""
    assets = config["phase1"]["universe"]["assets"]
    kept = [asset for asset in assets if asset.get("ticker") != coin]
    if len(kept) == len(assets):
        raise SystemExit(f"{coin} is not in config.json's universe")
    return {**config, "phase1": {**config["phase1"], "universe": {**config["phase1"]["universe"], "assets": kept}}}


def stage_reproduce(args) -> int:
    """V6.5.0's freeze guard is out of date by design: five files changed in V6.5.x and V6.6.x. What matters for the re-pin is that today's code, given the installed universe, still writes the installed
    weight file, so the only difference the new pin carries is the coin. The installed file is the median phase (index 4) over the verification window."""
    rules = check_rules()
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    if not any(asset.get("ticker") == COIN for asset in config["phase1"]["universe"]["assets"]):
        print("config.json no longer lists EOSUSD: reproduce before `make`", file=sys.stderr)
        return 1
    installed = json.loads((ROOT / INSTALLED_CANDIDATE).read_text(encoding="utf-8"))
    window = tuple(rules["windows"]["verification"])
    rows = candidate_rows({"survivors": [NAME], "method": None}, load_context(), start=window[0], end=window[1], phase_index=int(installed["phase_index"]))
    from portfolio.target_weights import write_weight_file

    scratch = OUT / "reproduce_installed.csv"
    OUT.mkdir(parents=True, exist_ok=True)
    rebuilt = write_weight_file(rows, scratch)
    expected = config["phase_v2"]["target_weights"]["weights_sha256"]
    result = {"rebuilt_sha256": rebuilt, "installed_sha256": expected, "identical": rebuilt == expected, "code_digests": freeze_digest({"survivors": [NAME], "method": None})["code"]}
    (OUT / "eos_reproduce.json").write_text(json.dumps(result, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps({key: result[key] for key in ("rebuilt_sha256", "installed_sha256", "identical")}, indent=1))
    return 0 if result["identical"] else 1


def stage_make(args) -> int:
    rules = check_rules()
    config_path = ROOT / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if any(asset.get("ticker") == COIN for asset in config["phase1"]["universe"]["assets"]):
        config_path.write_text(json.dumps(drop_coin(config), indent=4), encoding="utf-8", newline="\n")
    base = json.loads(config_path.read_text(encoding="utf-8"))
    definition = {"survivors": [NAME], "method": None}
    context = load_context()
    window, long_window = tuple(rules["windows"]["verification"]), tuple(rules["windows"]["long"])
    runs = {}
    for phase in range(PHASES):
        name = f"v664_eos_p{phase}"
        runs[name] = make_run(name, candidate_rows(definition, context, start=window[0], end=window[1], phase_index=phase), window, base)
    runs["v664_eos_long"] = make_run("v664_eos_long", candidate_rows(definition, context, start=long_window[0], end=long_window[1], phase_index=0), long_window, base)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "eos_repin_runs.json").write_text(json.dumps(runs, indent=1), encoding="utf-8", newline="\n")
    (OUT / "eos_repin_run_list.txt").write_text(" ".join(f"ml/evaluation/run_configs/{name}.json" for name in runs) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(runs)} runs written; config.json now lists {len(base['phase1']['universe']['assets'])} assets")
    return 0


def describe(run_dir: Path) -> dict:
    from evaluation.alpha_proof import alpha_regression, benchmark_daily_returns, sharpe, to_sessions

    config = json.loads((RUN_CONFIGS / f"{run_dir.name}.json").read_text(encoding="utf-8"))
    y = strategy_series(run_dir, config)
    stats = lean_statistics(run_dir)
    stats["strategy_sharpe"] = sharpe(y.to_numpy(dtype=float), ANNUALIZATION)
    log = (run_dir / "log.txt").read_text(encoding="utf-8", errors="replace")
    stats["complete"] = "PythonInitializer.Shutdown(): start" in log and "Runtime Error" not in log
    benchmarks = benchmark_daily_returns(ROOT, config, start=str(y.index.min()), end=str(y.index.max()))
    alpha = alpha_regression(to_sessions(y, benchmarks.index), benchmarks)
    stats["alpha_annual"], stats["alpha_t"] = alpha.get("alpha_annual"), alpha.get("t_hac")
    stats["locked"] = "total_drawdown_limit_breached" in log or "kill_switch" in log
    stats["run"] = run_dir.name
    return stats


def stage_install(args) -> int:
    done = {}
    for line in Path(args.status).read_text(encoding="utf-8-sig").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "LEAN_DONE":
            done[parts[1]] = ROOT / parts[2]
    phases = {f"p{phase}": describe(done[f"v664_eos_p{phase}"]) for phase in range(PHASES) if f"v664_eos_p{phase}" in done}
    if len(phases) != PHASES or "v664_eos_long" not in done:
        print(f"missing runs: have {sorted(done)}", file=sys.stderr)
        return 1
    incomplete = [phase for phase, entry in phases.items() if not entry["complete"]]
    if incomplete:
        print(f"phases {incomplete} did not finish (read the engine log.txt of each, AGENTS rule 7)", file=sys.stderr)
        return 1
    long_run = describe(done["v664_eos_long"])
    phase = median_phase(phases)
    run = phases[phase]["run"]
    config = json.loads((RUN_CONFIGS / f"{run}.json").read_text(encoding="utf-8"))
    target = config["phase_v2"]["target_weights"]
    source = ROOT / target["weights_path"]
    if hashlib.sha256(source.read_bytes()).hexdigest() != target["weights_sha256"]:
        print(f"{source} is not the file the run froze", file=sys.stderr)
        return 1
    shutil.copyfile(source, ROOT / INSTALLED_WEIGHTS)
    target["weights_path"] = INSTALLED_WEIGHTS
    config["runtime"]["lean_window_override"] = None
    (ROOT / "config.json").write_text(json.dumps(config, indent=4), encoding="utf-8", newline="\n")
    candidate = {"survivors": [NAME], "method": None, "phase_index": int(phase[1:]), "history_start": "2023-07-01", "pinned_run": run}
    (ROOT / INSTALLED_CANDIDATE).write_text(json.dumps(candidate, indent=1), encoding="utf-8", newline="\n")
    (ROOT / "ml" / "evaluation" / "readme_lean_run.json").write_text(json.dumps({"run": run, "long_run": long_run["run"]}), encoding="utf-8", newline="\n")
    old = json.loads((ROOT / "ml" / "evaluation" / "v650" / "r_lean19.json").read_text(encoding="utf-8"))["detail"][NAME]["phases"]
    record = {
        "decision": "owner, 2026-11-07: Coinbase delisted EOS-USD (Problems #311)", "median_phase": phase, "pinned_run": run, "long_run": long_run["run"],
        "phases": phases, "long": long_run, "v650_phases_with_eos": {key: {"lean_sharpe": value["lean_sharpe"], "strategy_sharpe": value["strategy_sharpe"], "drawdown_pct": value["drawdown_pct"]} for key, value in old.items()},
        "median_strategy_sharpe_without_eos": float(np.median([entry["strategy_sharpe"] for entry in phases.values()])),
        "median_strategy_sharpe_with_eos": float(np.median([entry["strategy_sharpe"] for entry in old.values()])),
        "config_sha256": hashlib.sha256((ROOT / "config.json").read_bytes()).hexdigest(), "weights_sha256": target["weights_sha256"],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "eos_repin.json").write_text(json.dumps(record, indent=1, default=str), encoding="utf-8", newline="\n")
    print(json.dumps({key: record[key] for key in ("median_phase", "pinned_run", "long_run", "median_strategy_sharpe_without_eos", "median_strategy_sharpe_with_eos", "config_sha256", "weights_sha256")}, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="stage", required=True)
    sub.add_parser("reproduce")
    sub.add_parser("make")
    install = sub.add_parser("install")
    install.add_argument("--status", required=True)
    args = parser.parse_args(argv)
    return {"reproduce": stage_reproduce, "make": stage_make, "install": stage_install}[args.stage](args)


if __name__ == "__main__":
    raise SystemExit(main())
