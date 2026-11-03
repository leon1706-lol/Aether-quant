"""R-CAL5 (V6.4.4, rule in ml/evaluation/v644/r_cal5_rule.json, the #249 lead): re-derive the simulator's live-gate replicas
from the engine's own trades.

  audit   for BT5 / BT7 / BT8: classify Lean's main-book trades (from the fills) and the calibrated simulator's (from its
          weights) into entries, exits, flips and resizes on and off live's rebalance dates
          (evaluation/gate_replica_audit.py) -> ml/evaluation/v644/gate_replica_audit.json
  score   run each candidate rung (a `simulate_rank_book` keyword set on top of the calibrated rung) through
          scripts/lean_calibration.run_window on the three runs and decide it by R-CAL5 -> r_cal5_result.json

    python scripts/v644_rcal5.py audit
    python scripts/v644_rcal5.py score --candidate '<name>={"key": value, ...}' [...]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

OUT_DIR = ROOT_DIR / "ml" / "evaluation" / "v644"
WINDOWS = {
    "bt5": "bt5=backtests/2026-10-22_10-56-13@2023-07-01..2026-10-16:backtest+holdout",
    "bt7": "bt7=backtests/2026-10-24_05-28-07@2023-07-01..2026-10-16:backtest+holdout",
    "bt8": "bt8=backtests/2026-10-24_18-50-22@2023-07-01..2026-10-16:backtest+holdout",
}
MIN_GAIN = 0.05
BRANCH_A = 0.9


def main_book_tickers(config: dict) -> set[str]:
    """Tickers the main book trades: equities that are not bond ETFs, and crypto (the T-bill sweep and sleeves excluded)."""
    sweep = str((config["phase_v2"].get("cash_sweep") or {}).get("ticker", "BIL")).upper()
    out = set()
    for asset in config["phase1"]["universe"]["assets"]:
        kind = str(asset.get("asset_class") or asset.get("security_type"))
        if kind in ("equity", "crypto") and str(asset["ticker"]).upper() != sweep:
            out.add(str(asset["ticker"]).upper())
    return out


def audit_window(text: str, dataset: Path, config: dict) -> dict:
    from as_live_levers import AsLiveHarness
    from lean_calibration import live_decisions, parse_window, rebalance_phase, topology_inputs_fn_for, window_config

    from evaluation.backtest_audit import load_backtest_run
    from evaluation.gate_replica_audit import compare_profiles, lean_trades, offline_trades, trade_profile
    from evaluation.lean_attribution import fills_from_order_events, find_book_history_for_run

    window = parse_window(text)
    config = window_config(window, config)
    run_dir = ROOT_DIR / window["run_dir"]
    run = load_backtest_run(run_dir)
    history_path = find_book_history_for_run(run_dir, ROOT_DIR / "visualization" / "book_history")
    history = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    live = live_decisions(history, window["start"], window["end"])
    harness = AsLiveHarness(window["splits"], dataset_path=dataset, config=config)
    sessions = sorted(harness.session_dates)
    in_window = [date for date in sessions if window["start"] <= date <= window["end"]]
    phase = rebalance_phase(min(live) if live else None, sessions, int(config["phase_v2"]["portfolio_book"]["rebalance_every_bars"]))
    harness.topology_inputs_fn = topology_inputs_fn_for(harness, config)
    harness._mechanisms.clear()
    from lean_calibration import ANALYZER_INCLUDE

    # the research default (scripts/v643_research.Chain.as_live): the calibrated rung plus the V6.1.0 mechanisms
    mechanisms = harness.v610_mechanisms(config, legacy=False)
    result = harness.as_live(log_weights=True, rebalance_counter_start=phase, intraday_next_return_column="next_intraday_return",
                             min_commission_usd_by_ticker=harness.min_commission_usd_by_ticker,
                             assumed_portfolio_value_usd=harness.initial_cash, include=ANALYZER_INCLUDE, **mechanisms)
    keep = [i for i, date in enumerate(result.per_date) if window["start"] <= date <= window["end"]]
    offline = offline_trades([result.per_date[i] for i in keep], [result.weights_log[i] for i in keep])
    tickers = main_book_tickers(config)
    lean = [trade for trade in lean_trades(fills_from_order_events(run["order_events"]), tickers)
            if window["start"] <= trade["date"] <= window["end"]]
    rebalance_dates = sorted(live)
    lean_profile = trade_profile(lean, rebalance_dates, in_window, lag_sessions=1)
    offline_profile = trade_profile(offline, rebalance_dates, in_window)
    return {"window": window["name"], "lean": lean_profile, "offline": offline_profile,
            "compare": compare_profiles(lean_profile, offline_profile), "live_rebalance_dates": len(rebalance_dates)}


def verdict(name: str, base: dict, cand: dict) -> dict:
    gains = {w: (cand[w] - base[w]) if cand.get(w) is not None and base.get(w) is not None else None for w in base}
    checks = {
        "bt5_gain_ge_0.05": gains["bt5"] is not None and gains["bt5"] >= MIN_GAIN,
        "bt7_not_lower": gains["bt7"] is not None and gains["bt7"] >= 0.0,
        "bt8_not_lower": gains["bt8"] is not None and gains["bt8"] >= 0.0,
    }
    adopted = all(checks.values())
    best = cand if adopted else base
    return {"candidate": name, "base_correlation": base, "candidate_correlation": cand, "gains": gains, "checks": checks,
            "adopted": adopted, "branch": "A" if all(v is not None and v >= BRANCH_A for v in best.values()) else "B"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["audit", "score"])
    parser.add_argument("--dataset", default=str(ROOT_DIR / "ml" / "datasets" / "full_dataset.csv"))
    parser.add_argument("--candidate", action="append", default=[], help='name={"simulate_rank_book keyword": value, ...}')
    parser.add_argument("--windows", nargs="*", default=list(WINDOWS))
    args = parser.parse_args()
    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    if args.mode == "audit":
        out = {name: audit_window(WINDOWS[name], Path(args.dataset), config) for name in args.windows}
        (OUT_DIR / "gate_replica_audit.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
        for name, entry in out.items():
            print(name, json.dumps({k: entry["compare"]["rows"][k] for k in entry["compare"]["ranked"][:4]}),
                  entry["compare"]["median_sessions_between_trades"], flush=True)
        return 0
    from lean_calibration import BOOK_COMPONENTS, parse_window, run_window

    candidates = {}
    for text in args.candidate:
        name, _, payload = text.partition("=")
        candidates[name] = {"base": "v610_mechanisms", **json.loads(payload)}
    results, rows = {}, {}
    base = {}
    for window in args.windows:
        report = run_window(parse_window(WINDOWS[window]), Path(args.dataset), config, BOOK_COMPONENTS, extra_ladder=candidates,
                            rcal2=True)
        base[window] = report["variants"]["v610_mechanisms"].get("daily_correlation")
        rows[window] = {name: {k: v for k, v in report["variants"][name].items() if k != "disagreement"} for name in candidates}
    for name in candidates:
        cand = {window: rows[window][name].get("daily_correlation") for window in args.windows}
        results[name] = verdict(name, base, cand)
    out = {"results": results, "rows": rows}
    (OUT_DIR / "r_cal5_result.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print("R-CAL5:", json.dumps({n: {k: r[k] for k in ("gains", "adopted")} for n, r in results.items()}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
