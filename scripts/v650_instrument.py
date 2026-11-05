"""V6.5.0 instrument batch: the run configs that test the target-weights path against the offline engine, and the comparison.

    python scripts/v650_instrument.py make             # weight files and run configs of BT12-BT23
    python scripts/v650_instrument.py compare <name> <backtests/run>   # R-INSTR1 for one run
    python scripts/v650_instrument.py orders <backtests/a> <backtests/b>   # are two runs the same, order for order?

The plumbing weights are random on purpose. They carry no signal and cannot be selected, so running them on any window
reads nothing about any candidate. The window predates the verification data and spans a crypto fee change and March 2020.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from evaluation.target_weights_engine import MarketPanel, load_market_panel, simulate_target_weights  # noqa: E402
from portfolio.financing import load_rate_series  # noqa: E402
from portfolio.target_weights import load_weight_file, resolve_target_weights_config, write_weight_file  # noqa: E402

V650 = ROOT / "ml" / "evaluation" / "v650"
WEIGHTS = V650 / "weights"
RUN_CONFIGS = ROOT / "ml" / "evaluation" / "run_configs"
PLUMBING_WINDOW = ("2019-01-01", "2020-12-31")
VERIFICATION_WINDOW = ("2023-07-01", "2026-11-02")
RATE_CSV = ROOT / "data" / "alternative" / "interest-rate" / "usa" / "interest-rate.csv"


def target_path_config(base: dict, *, weights_path: str, weights_sha256: str, window: tuple[str, str], locks: bool = True) -> dict:
    """A run of the target-weights path under the risk settings of the plan's §3.4. `locks=False` is for plumbing
    weights, whose purpose is to compare the two engines over the whole window: they are random, not risk-controlled."""
    config = copy.deepcopy(base)
    config["phase_v2"]["target_weights"].update({"enabled": True, "weights_path": weights_path, "weights_sha256": weights_sha256})
    config["runtime"]["lean_window_override"] = {"start": window[0], "end": window[1]}
    config["phase6"]["risk"]["max_total_drawdown_pct"] = 0.15 if locks else 0.95
    config["phase6"]["risk"]["max_daily_drawdown_pct"] = 0.05 if locks else 0.95
    config["phase_v2"]["backtest"]["bypass_sticky_trade_lock"] = False
    kill = config["phase_v2"]["risk"]["kill_switch"]
    # off (rules_amendment_1.json): sticky at 3 x 7% / sqrt(252), one ordinary bad crypto day ended every run within months
    kill["max_drawdown_velocity_pct_per_bar"] = 1.0
    kill["min_rolling_sharpe"] = -100.0
    kill["min_live_rank_ic"] = -100.0
    kill["max_consecutive_losses"] = 100000
    kill["max_slippage_divergence_bps"] = 100000
    return config


def random_weights(panel: MarketPanel, tickers: list[str], *, seed: int, start: str, end: str, every: int, gross: float, neutral: bool) -> dict:
    rng = np.random.default_rng(seed)
    sessions = [date for date in panel.dates if date in panel.sessions and start <= date <= end]
    index = panel.index()
    rows: dict[str, dict[str, float]] = {}
    for position, date in enumerate(sessions):
        if position % every:
            continue
        row = panel.dates.index(date)
        live = [ticker for ticker in tickers if np.isfinite(panel.closes[max(0, row - 3):row + 1, index[ticker]]).any()]
        if not live:
            rows[date] = {}
            continue
        raw = rng.normal(size=len(live))
        if neutral:
            raw -= raw.mean()
        else:
            raw = np.abs(raw)
        scale = gross / np.abs(raw).sum()
        rows[date] = {ticker: float(value * scale) for ticker, value in zip(live, raw)}
    return rows


def oracle_weights(panel: MarketPanel, tickers: list[str], *, start: str, end: str, every: int, gross: float) -> dict:
    """Long the next period's winners and short its losers, using the future. A test of the machinery: what a perfect
    signal earns through this path, as a ceiling. Never selectable."""
    index = panel.index()
    sessions = [date for date in panel.dates if date in panel.sessions and start <= date <= end]
    rows: dict[str, dict[str, float]] = {}
    for position in range(0, len(sessions) - every - 1, every):
        now = panel.dates.index(sessions[position + 1])
        later = panel.dates.index(sessions[position + 1 + every])
        moves = {}
        for ticker in tickers:
            first, last = panel.opens[now, index[ticker]], panel.opens[later, index[ticker]]
            if np.isfinite(first) and np.isfinite(last) and first > 0.0:
                moves[ticker] = last / first - 1.0
        ranked = sorted(moves, key=moves.get)
        count = min(6, len(ranked) // 2)
        if count == 0:
            continue
        weight = gross / (2 * count)
        rows[sessions[position]] = {**{ticker: weight for ticker in ranked[-count:]}, **{ticker: -weight for ticker in ranked[:count]}}
    return rows


def _write_config(name: str, config: dict) -> str:
    text = json.dumps(config, indent=4)
    path = RUN_CONFIGS / f"{name}.json"
    path.write_text(text, encoding="utf-8", newline="\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make() -> dict:
    from v610_research import apply_dotted

    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    panel = load_market_panel(ROOT, base)
    WEIGHTS.mkdir(parents=True, exist_ok=True)
    classes = panel.asset_class
    equities = [t for t in panel.tickers if classes[t] == "equity"]
    bonds = [t for t in panel.tickers if classes[t] == "bond"]
    forex = [t for t in panel.tickers if classes[t] == "forex"]
    crypto = [t for t in ("BTCUSD", "ETHUSD", "LTCUSD") if t in classes]
    start, end = PLUMBING_WINDOW

    files = {
        "plumbing_equity": random_weights(panel, equities, seed=11, start=start, end=end, every=5, gross=1.0, neutral=True),
        "plumbing_crypto": random_weights(panel, crypto, seed=12, start=start, end=end, every=5, gross=0.3, neutral=False),
        "plumbing_oracle": oracle_weights(panel, equities, start=start, end=end, every=5, gross=1.0),
    }
    mixed = random_weights(panel, equities + bonds, seed=13, start=start, end=end, every=5, gross=0.8, neutral=True)
    mixed_fx = random_weights(panel, forex, seed=14, start=start, end=end, every=5, gross=0.4, neutral=True)
    mixed_crypto = random_weights(panel, crypto, seed=15, start=start, end=end, every=5, gross=0.1, neutral=False)
    files["plumbing_mixed"] = {date: {**mixed[date], **mixed_fx.get(date, {}), **mixed_crypto.get(date, {})} for date in mixed}

    manifest: dict[str, dict] = {}
    runs = {"v650_bt13": "plumbing_equity", "v650_bt14": "plumbing_crypto", "v650_bt15": "plumbing_mixed",
            "v650_bt16": "plumbing_equity", "v650_bt17": "plumbing_oracle"}
    hashes = {name: write_weight_file(rows, WEIGHTS / f"{name}.csv") for name, rows in files.items()}
    for run, name in runs.items():
        config = target_path_config(base, weights_path=f"ml/evaluation/v650/weights/{name}.csv", weights_sha256=hashes[name],
                                    window=PLUMBING_WINDOW, locks=name == "plumbing_oracle")
        manifest[run] = {"weights": name, "weights_sha": hashes[name], "config_sha": _write_config(run, config), "role": "plumbing"}

    # BT11's window, not the root config's (whose default window stops at the end of the backtest split)
    gated = copy.deepcopy(base)
    gated["runtime"]["lean_window_override"] = {"start": VERIFICATION_WINDOW[0], "end": VERIFICATION_WINDOW[1]}
    manifest["v650_bt12"] = {"role": "plumbing", "config_sha": _write_config("v650_bt12", gated), "is": "BT11's book on the new code, flag off"}

    ablations = {
        "v650_bt18": ("rolling IC gate off", {"rolling_ic_gate.enabled": False}),
        "v650_bt19": ("risk-off override off", {"regime_detection.risk_off_override_min_severity": 2.0}),
        "v650_bt20": ("spread floor 0", {"portfolio_book.min_rank_confidence_spread": 0.0}),
        "v650_bt21": ("non-model exits off", {"exits.enabled": False}),
        "v650_bt22": ("cost sizing off", {"costs.cost_sizing_enabled": False}),
    }
    everything: dict = {}
    for run, (label, changes) in ablations.items():
        everything.update(changes)
        manifest[run] = {"role": "candidate", "is": label, "config_sha": _write_config(run, apply_dotted(gated, changes))}
    manifest["v650_bt23"] = {"role": "candidate", "is": "all five off", "config_sha": _write_config("v650_bt23", apply_dotted(gated, everything))}
    (V650 / "instrument_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8", newline="\n")
    return manifest


def _engine_for(run_config: dict, panel: MarketPanel) -> dict:
    target = run_config["phase_v2"]["target_weights"]
    config = resolve_target_weights_config(target)
    weights = load_weight_file(ROOT / target["weights_path"], target["weights_sha256"])
    window = run_config["runtime"]["lean_window_override"]
    rf_dates, rf_rates = load_rate_series(RATE_CSV)
    from data_pipeline.fred_backfill import load_cached_fred_series
    from features.fx_carry import fx_carry_3m

    fred = load_cached_fred_series()
    kill = run_config["phase_v2"]["risk"]["kill_switch"]
    return simulate_target_weights(
        weights, panel, config, start=window["start"], end=window["end"], sweep_config=run_config["phase_v2"]["cash_sweep"],
        rf_dates=rf_dates, rf_rates=rf_rates,
        carry_fn=lambda ticker, date: fx_carry_3m(ticker, "forex", datetime.date.fromisoformat(date), fred),
        max_total_drawdown=run_config["phase6"]["risk"]["max_total_drawdown_pct"],
        max_drawdown_velocity=kill["max_drawdown_velocity_pct_per_bar"],
    )


def compare(name: str, run_dir: Path) -> dict:
    """Daily correlation and annual return gap of the engine against one finished Lean run (rule R-INSTR1)."""
    import pandas as pd

    from evaluation.backtest_audit import daily_equity_from_chart, load_backtest_run

    run_config = json.loads((RUN_CONFIGS / f"{name}.json").read_text(encoding="utf-8"))
    panel = load_market_panel(ROOT, run_config)
    engine = _engine_for(run_config, panel)
    points = daily_equity_from_chart(load_backtest_run(run_dir)["result"])
    lean_nav = pd.Series({day: value for day, value in points}, dtype=float).sort_index()
    window = run_config["runtime"]["lean_window_override"]
    lean_nav = lean_nav[(lean_nav.index >= window["start"]) & (lean_nav.index <= window["end"])]
    lean = lean_nav.pct_change().dropna()
    report: dict = {"name": name, "run": str(run_dir), "lean_days": int(len(lean)), "engine_days": int(len(engine["total"]))}
    for lag in (-1, 0, 1):
        joined = pd.concat([lean, engine["total"].shift(lag)], axis=1, join="inner").dropna()
        report[f"corr_lag{lag}"] = float(joined.corr().iloc[0, 1]) if len(joined) > 10 else None
    weekly = pd.concat([(1 + lean).groupby(pd.to_datetime(lean.index).to_period("W")).prod() - 1,
                        (1 + engine["total"]).groupby(pd.to_datetime(engine["total"].index).to_period("W")).prod() - 1],
                       axis=1, join="inner").dropna()
    report["corr_weekly"] = float(weekly.corr().iloc[0, 1]) if len(weekly) > 5 else None
    years = max(len(lean) / 365.25, 1e-9)
    report["lean_total_return"] = float(lean_nav.iloc[-1] / lean_nav.iloc[0] - 1.0)
    report["engine_total_return"] = float(engine["nav"].iloc[-1] / engine["nav"].iloc[0] - 1.0)
    report["annual_gap_bps"] = float((report["engine_total_return"] - report["lean_total_return"]) / years * 1e4)
    report["engine_fees"] = engine["fees"]
    report["engine_financing"] = engine["financing"]
    report["engine_fills"] = engine["fills"]
    report["engine_locked_on"] = engine["locked_on"]
    return report


def orders(first: Path, second: Path) -> dict:
    """Are two runs the same, order for order?"""
    from evaluation.backtest_audit import load_backtest_run
    from evaluation.lean_attribution import fills_from_order_events

    def fills(run_dir: Path) -> list[tuple]:
        run = load_backtest_run(run_dir)
        return [(fill.date, fill.ticker, round(fill.quantity, 6), round(fill.price, 6)) for fill in fills_from_order_events(run.get("order_events", []))]

    a, b = fills(first), fills(second)
    only_a, only_b = sorted(set(a) - set(b)), sorted(set(b) - set(a))
    return {"first": len(a), "second": len(b), "identical": a == b, "only_first": only_a[:10], "only_second": only_b[:10]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("make")
    compare_parser = commands.add_parser("compare")
    compare_parser.add_argument("name")
    compare_parser.add_argument("run_dir")
    orders_parser = commands.add_parser("orders")
    orders_parser.add_argument("first")
    orders_parser.add_argument("second")
    args = parser.parse_args()
    if args.command == "make":
        result = make()
    elif args.command == "compare":
        result = compare(args.name, ROOT / args.run_dir)
    else:
        result = orders(ROOT / args.first, ROOT / args.second)
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
