"""Is the offline as-live simulator a model of what Lean does? Rule R-CAL (V6.0.0, todo lead 2).

For each calibration window (a finished Lean run, optionally a sub-period) this compares the Lean main book - the main
book plus its crypto members, rebuilt day by day from the order events by `evaluation.lean_attribution` - with the
offline simulator run over the same dates, as a ladder of increasingly live-like variants:

    v580        the V5.8.0 as-live simulator (cadence counted on every date with enough rows)
    phase       + live's cadence: equity sessions only (no step on an equity holiday), on live's phase
    next_open   + an order decided at the close earns from the next open, not the next close
    min_fee     + the broker's per-order dollar floor at the live NAV
    live_gates  + live's resize threshold, entry cooldown and trailing stop
    calibrated  + the learned-topology sizing multiplier (mid peer bracket, scripts/topology_sizing_research.py)
    replay      the calibrated simulator with live's own gate decisions replayed (diagnostic only)

and reports, per variant: the daily P&L correlation, the annualised return gap, and the share of live rebalance dates
on which the offline book took the same decision (engaged / vetoed / kill-switch locked).

R-CAL (pre-registered, plan V6.0.0): calibrated iff on EVERY window the calibrated variant has daily correlation >= 0.50,
|annualised return gap| <= 2.0 percentage points and decision agreement >= 80%. Branch A (calibrated) lets R-GATE and
R-BOOK use the as-live simulator; branch B freezes the gates and judges alpha on the ungated book.

    python scripts/lean_calibration.py --dataset ml/datasets/full_dataset.csv \
        --window bt1=backtests/2026-10-13_17-54-47@2023-07-01..2025-06-30:backtest \
        --window bt2_backtest=backtests/2026-10-14_07-27-32@2023-07-01..2025-06-30:backtest+holdout \
        --window bt2_holdout=backtests/2026-10-14_07-27-32@2025-07-01..2026-09-30:backtest+holdout
    python scripts/lean_calibration.py --predict --dataset ... --window bt=@2023-07-01..2026-09-30:backtest+holdout
        (no Lean run yet: writes the calibrated simulator's prediction for the window, R-CAL's out-of-sample check)
"""

from __future__ import annotations

import argparse
import bisect
import json
import sys
from pathlib import Path

import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

BOOK_COMPONENTS = ("main_book", "crypto_core", "crypto_graduate")
MIN_CORRELATION = 0.50
MAX_ANNUAL_GAP = 0.02
MIN_DECISION_AGREEMENT = 0.80
CALIBRATED_VARIANT = "calibrated"


def parse_window(text: str) -> dict:
    """`name=<run dir>@START..END:split[+split]`; an empty run dir means "no Lean run" (prediction only)."""
    name, _, rest = text.partition("=")
    run_dir, _, rest = rest.partition("@")
    period, _, splits = rest.partition(":")
    start, _, end = period.partition("..")
    if not (name and start and end and splits):
        raise ValueError(f"bad --window {text!r}")
    return {"name": name, "run_dir": run_dir or None, "start": start, "end": end, "splits": tuple(splits.split("+"))}


def lean_book_returns(daily_components: dict, daily_equity: list) -> dict[str, float]:
    """{date: book net P&L / previous NAV} for the main book and its crypto members."""
    nav_dates = [date for date, _ in daily_equity]
    navs = [value for _, value in daily_equity]
    out = {}
    for date, components in daily_components.items():
        position = bisect.bisect_left(nav_dates, date) - 1
        nav = navs[position] if position >= 0 else (navs[0] if navs else 0.0)
        if nav > 0:
            out[date] = sum(components.get(name, 0.0) for name in BOOK_COMPONENTS) / nav
    return out


def bucket_to_offline_dates(lean_returns: dict[str, float], offline_dates: list[str]) -> dict[str, float]:
    """Offline return on date D covers (D, next offline date]; Lean's calendar-day P&L is summed into those buckets."""
    out = {date: 0.0 for date in offline_dates}
    for date, value in lean_returns.items():
        position = bisect.bisect_left(offline_dates, date) - 1
        if 0 <= position < len(offline_dates):
            out[offline_dates[position]] += value
    return out


def live_decisions(book_history: list[dict], start: str, end: str) -> dict[str, str]:
    """{date: engaged | vetoed | locked} for live's rebalance attempts in the window (warm-up records excluded)."""
    out = {}
    for record in book_history:
        date = record.get("date", "")
        if not (start <= date <= end) or record.get("gate_veto_reason") == "thin_universe_or_zero_top_n":
            continue
        decisions = record.get("book_member_decisions") or {}
        # a vetoed record also lists the HELD members, reduced by the kill switch: locked needs a formed book
        locked = bool(record.get("allocations")) and bool(decisions) and all(
            decision.get("action") == "reduce_risk" and any("kill_switch" in reason for reason in decision.get("reasons", []))
            for decision in decisions.values()
        )
        out[date] = "locked" if locked else ("engaged" if record.get("allocations") else "vetoed")
    return out


def offline_decisions(rebalance_log: list[dict]) -> dict[str, str]:
    return {
        entry["date"]: "locked" if entry.get("locked") and entry.get("engaged") else ("engaged" if entry["engaged"] else "vetoed")
        for entry in rebalance_log
    }


def decision_agreement(live: dict[str, str], offline: dict[str, str], *, binary: bool = True) -> float | None:
    """Share of live rebalance dates with the same offline decision. R-CAL's clause is binary - the book traded
    (engaged) or did not (vetoed / locked); `binary=False` compares the three states. A date the offline book did not
    rebalance on counts as a disagreement."""
    if not live:
        return None
    if binary:
        traded = lambda state: state == "engaged"  # noqa: E731
        return sum(1 for date, state in live.items() if date in offline and traded(offline[date]) == traded(state)) / len(live)
    return sum(1 for date, state in live.items() if offline.get(date) == state) / len(live)


def rebalance_phase(first_live_date: str | None, offline_dates: list[str], rebalance_every_bars: int) -> int:
    """Counter start that puts the offline cadence on live's first in-window rebalance date."""
    if not first_live_date or first_live_date not in offline_dates:
        return 0
    steps = offline_dates.index(first_live_date)
    return (-steps) % max(1, rebalance_every_bars)


def compare(lean: dict[str, float], offline_dates: list[str], offline_returns: list[float]) -> dict:
    offline = dict(zip(offline_dates, offline_returns))
    common = [date for date in offline_dates if date in lean]
    a = np.array([offline[date] for date in common])
    b = np.array([lean[date] for date in common])
    correlation = float(np.corrcoef(a, b)[0, 1]) if len(common) > 2 and a.std() > 0 and b.std() > 0 else None
    years = len(common) / 252.0 if common else 0.0
    return {
        "days": len(common),
        "daily_correlation": correlation,
        "offline_annual_return": float(a.sum() / years) if years else None,
        "lean_annual_return": float(b.sum() / years) if years else None,
        "annual_return_gap": float((a.sum() - b.sum()) / years) if years else None,
        "offline_sharpe": float(a.mean() / a.std() * np.sqrt(252)) if len(a) > 2 and a.std() > 0 else None,
        "lean_sharpe": float(b.mean() / b.std() * np.sqrt(252)) if len(b) > 2 and b.std() > 0 else None,
    }


def live_book_weights(run: dict, history: list[dict], config: dict) -> dict[str, dict[str, float]]:
    """{date: {ticker: end-of-day weight}} of live's book members (main pool incl. crypto), position x close / NAV."""
    from evaluation.backtest_audit import daily_equity_from_chart
    from evaluation.lean_attribution import (
        closes_for_universe,
        daily_ticker_pnl,
        fills_from_order_events,
        formed_book_by_date,
    )

    class_by_ticker = {
        str(asset["ticker"]).upper(): str(asset.get("asset_class") or asset.get("security_type"))
        for asset in config["phase1"]["universe"]["assets"]
    }
    fills = fills_from_order_events(run["order_events"])
    daily_equity = daily_equity_from_chart(run["result"])
    closes = closes_for_universe(config, ROOT_DIR, {fill.ticker for fill in fills})
    pnl = daily_ticker_pnl(fills, closes, [date for date, _ in daily_equity])
    members = formed_book_by_date(history, sorted(pnl))
    nav_by_date = dict(daily_equity)
    out = {}
    last_nav = daily_equity[0][1] if daily_equity else 1.0
    for date in sorted(pnl):
        last_nav = nav_by_date.get(date, last_nav)
        weights = {}
        for ticker, entry in pnl[date].items():
            if entry["position"] and ticker in members.get(date, frozenset()) and class_by_ticker.get(ticker) in ("equity", "crypto"):
                close = closes.get(ticker, {}).get(date)
                if close:
                    weights[ticker] = entry["position"] * close / last_nav
        out[date] = weights
    return out


def compare_weights(live: dict[str, dict[str, float]], offline_dates: list[str], offline_weights: list[dict]) -> dict:
    """Offline weights decided on D are held from the next session: compared with live's end-of-day weights there."""
    l1, overlap, live_gross, offline_gross = [], [], [], []
    for index, date in enumerate(offline_dates[:-1]):
        held_on = offline_dates[index + 1]
        if held_on not in live:
            continue
        a, b = offline_weights[index], live[held_on]
        names = set(a) | set(b)
        l1.append(sum(abs(a.get(name, 0.0) - b.get(name, 0.0)) for name in names))
        if names:
            overlap.append(len(set(a) & set(b)) / len(names))
        live_gross.append(sum(abs(value) for value in b.values()))
        offline_gross.append(sum(abs(value) for value in a.values()))
    mean = lambda values: float(np.mean(values)) if values else None  # noqa: E731
    return {"weight_l1": mean(l1), "name_overlap": mean(overlap), "live_gross": mean(live_gross), "offline_gross": mean(offline_gross)}


def window_passes(row: dict) -> bool:
    return (
        row.get("daily_correlation") is not None and row["daily_correlation"] >= MIN_CORRELATION
        and row.get("annual_return_gap") is not None and abs(row["annual_return_gap"]) <= MAX_ANNUAL_GAP
        and row.get("decision_agreement") is not None and row["decision_agreement"] >= MIN_DECISION_AGREEMENT
    )


def topology_inputs_fn_for(harness, config: dict, peer_distance: float = 0.5):
    """Live's learned-topology sizing inputs per (date, ticker) for the harness frame, at the mid peer bracket."""
    from topology_sizing_research import topology_inputs_by_row

    from evaluation.model_predictions import predict_heads

    learning = config["phase_v2"].get("topology_learning", {})
    ml = ROOT_DIR / "ml"
    topo_model = json.loads((ml / "topology_model.json").read_text(encoding="utf-8"))
    topo_schema = json.loads((ml / "topology_feature_schema.json").read_text(encoding="utf-8"))
    mt_schema = json.loads((ml / "multitask_feature_schema.json").read_text(encoding="utf-8"))
    mt_model = json.loads((ml / "multitask_model.json").read_text(encoding="utf-8"))
    probabilities = predict_heads(
        harness.frame, mt_model, list(mt_schema["model_input_names"]), ["direction"], model_kind="multitask", batched=True
    )["direction"]
    table = topology_inputs_by_row(
        harness.frame, topo_model, topo_schema, probabilities, peer_distance,
        temperature=float(learning.get("temperature", 0.35)), min_confidence=float(learning.get("min_confidence_for_learned", 0.2)),
    )
    return lambda symbol, date: table.get((str(date)[:10], str(symbol)))


def calibrated_overrides(harness, *, phase: int = 0) -> dict:
    """The `AsLiveHarness.as_live` keyword arguments of the calibrated simulator (R-CAL's `live_gates` rung): live's cadence
    phase, next-open fills and the broker's per-order floor. The resize / cooldown / trailing-stop gates come from the
    config through `build_as_live_kwargs`; the learned-topology sizing is plugged in with `use_topology`."""
    return {
        "rebalance_counter_start": phase,
        "intraday_next_return_column": "next_intraday_return",
        "min_commission_usd_by_ticker": harness.min_commission_usd_by_ticker,
        "assumed_portfolio_value_usd": harness.initial_cash,
    }


def use_topology(harness, topology_fn) -> None:
    """Switch the learned-topology sizing multiplier on (a function) or off (None) for the next runs."""
    if harness.topology_inputs_fn is not topology_fn:
        harness.topology_inputs_fn = topology_fn
        harness._mechanisms.clear()


def run_window(window: dict, dataset: Path, config: dict) -> dict:
    from as_live_levers import AsLiveHarness

    from evaluation.backtest_audit import load_backtest_run
    from evaluation.lean_attribution import attribute_run, find_book_history_for_run

    harness = AsLiveHarness(window["splits"], dataset_path=dataset)
    frame_dates = sorted(harness.session_dates)
    rebalance_every = int(config["phase_v2"]["portfolio_book"].get("rebalance_every_bars", 10))
    report: dict = {"window": window, "variants": {}}

    live, lean = {}, {}
    if window["run_dir"]:
        run_dir = ROOT_DIR / window["run_dir"]
        history_path = find_book_history_for_run(run_dir, ROOT_DIR / "visualization" / "book_history")
        history = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        attribution = attribute_run(load_backtest_run(run_dir), history, config, ROOT_DIR, period=(window["start"], window["end"]))
        lean = lean_book_returns(attribution["daily_components"], attribution["daily_equity"])
        live = live_decisions(history, window["start"], window["end"])
        live_weights = live_book_weights(load_backtest_run(run_dir), history, config)
        report["lean_components"] = {name: round(entry["net"], 2) for name, entry in attribution["components"].items()}
        report["live_decision_counts"] = {state: sum(1 for value in live.values() if value == state) for state in ("engaged", "vetoed", "locked")}

    in_window = [date for date in frame_dates if window["start"] <= date <= window["end"]]
    first_live = min(live) if live else None
    # the simulator starts at the frame's first date; the window may start later (BT2's holdout stretch)
    phase = rebalance_phase(first_live, frame_dates, rebalance_every) if first_live else 0
    floors = dict(min_commission_usd_by_ticker=harness.min_commission_usd_by_ticker, assumed_portfolio_value_usd=harness.initial_cash)
    no_gates = {"resize_threshold_weight": 0.0, "trade_cooldown_dates": 0, "trailing_stop_pct": None}
    ladder = {
        "v580": {"rebalance_session_dates": None, **no_gates},
        "phase": {"rebalance_counter_start": phase, **no_gates},
        "next_open": {"rebalance_counter_start": phase, "intraday_next_return_column": "next_intraday_return", **no_gates},
        "min_fee": {"rebalance_counter_start": phase, "intraday_next_return_column": "next_intraday_return", **floors, **no_gates},
    }
    ladder["live_gates"] = {key: value for key, value in ladder["min_fee"].items() if key not in no_gates}
    ladder["calibrated"] = dict(ladder["live_gates"], topology="mid")
    if live:
        ladder["replay"] = dict(ladder["calibrated"], decision_overrides=live)
    ladder["calibrated_ungated"] = dict(ladder["calibrated"], gate="off", min_rank_confidence_spread=0.0)
    topology_fn = topology_inputs_fn_for(harness, config)

    for name, overrides in ladder.items():
        overrides = dict(overrides)
        gate = overrides.pop("gate", "on")
        use_topology = overrides.pop("topology", None) is not None
        if (harness.topology_inputs_fn is not None) != use_topology:
            harness.topology_inputs_fn = topology_fn if use_topology else None
            harness._mechanisms.clear()
        result = harness.as_live(gate=gate, log_weights=True, **overrides)
        dates = list(result.per_date)
        returns = list(result.per_date_net_return)
        weights = list(result.weights_log)
        keep = [index for index, date in enumerate(dates) if window["start"] <= date <= window["end"]]
        dates = [dates[index] for index in keep]
        returns = [returns[index] for index in keep]
        weights = [weights[index] for index in keep]
        row = {"offline_net_return_window": float(np.prod([1 + value for value in returns]) - 1) if returns else None}
        if lean:
            row.update(compare(bucket_to_offline_dates(lean, in_window), dates, returns))
            offline_states = offline_decisions(result.rebalance_log)
            row["decision_agreement"] = decision_agreement(live, offline_states)
            row["decision_agreement_three_state"] = decision_agreement(live, offline_states, binary=False)
            row.update(compare_weights(live_weights, dates, weights))
        else:
            row.update({"offline_daily_returns": dict(zip(dates, returns)),
                        "offline_sharpe": float(np.mean(returns) / np.std(returns) * np.sqrt(252)) if np.std(returns) > 0 else None})
        report["variants"][name] = row
        print(
            f"  {window['name']:14s} {name:16s} r={row.get('daily_correlation')} gap={row.get('annual_return_gap')} "
            f"agree={row.get('decision_agreement')} offline_ret={row['offline_net_return_window']} "
            f"l1={row.get('weight_l1')} overlap={row.get('name_overlap')} gross live/off={row.get('live_gross')}/{row.get('offline_gross')}",
            flush=True,
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=str(ROOT_DIR / "ml" / "datasets" / "full_dataset.csv"))
    parser.add_argument("--window", action="append", required=True)
    parser.add_argument("--predict", action="store_true", help="no Lean comparison: write the prediction only")
    parser.add_argument("--out", default=str(ROOT_DIR / "ml" / "evaluation" / "v600" / "calibration.json"))
    args = parser.parse_args()
    config = json.loads((ROOT_DIR / "config.json").read_text(encoding="utf-8"))
    windows = [parse_window(text) for text in args.window]
    reports = {window["name"]: run_window(window, Path(args.dataset), config) for window in windows}
    verdict = None
    if not args.predict:
        passes = {name: window_passes(report["variants"][CALIBRATED_VARIANT]) for name, report in reports.items()}
        verdict = {"per_window": passes, "calibrated": all(passes.values()), "branch": "A" if all(passes.values()) else "B",
                   "thresholds": {"min_correlation": MIN_CORRELATION, "max_annual_gap": MAX_ANNUAL_GAP,
                                  "min_decision_agreement": MIN_DECISION_AGREEMENT}}
        print("R-CAL:", json.dumps(verdict))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"windows": reports, "verdict": verdict}, indent=1, default=str), encoding="utf-8")
    print(f"written {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
