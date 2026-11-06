"""V6.6.0's Lean runs: the instrument batch (BT24-BT27) and R-INSTR2.

    python scripts/v660_lean.py instrument       # writes run configs; every run stays inside free cells
    python scripts/v660_lean.py compare <name> <backtests/run>
    python scripts/v660_lean.py orders <backtests/a> <backtests/b>   # order-for-order, for BT24 against the pin
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from v650_instrument import oracle_weights, random_weights, target_path_config  # noqa: E402

from evaluation.research_cells import coin_side, name_side  # noqa: E402
from evaluation.target_weights_engine import load_market_panel, simulate_target_weights  # noqa: E402
from evaluation.wide_context import SECTOR_ETFS, project_tickers, wide_config_for  # noqa: E402
from portfolio.financing import load_rate_series  # noqa: E402
from portfolio.target_weights import load_weight_file, resolve_target_weights_config, write_weight_file  # noqa: E402

OUT = ROOT / "ml" / "evaluation" / "v660"
WEIGHTS = OUT / "weights"
RUN_CONFIGS = ROOT / "ml" / "evaluation" / "run_configs"
PIN = "backtests/2026-11-04_18-10-49"
# Inside free cells: side A names, inside S; side A coins, inside CS. Oracle weights read the future, which a plumbing run may.
WIDE_WINDOW = ("2014-01-02", "2015-12-31")
CRYPTO_WINDOW = ("2020-01-02", "2021-12-31")
WIDE_PATH = {"min_weight_change": 0.001, "no_bar_exit": True, "no_bar_exit_after": 2, "financing_enabled": True}


def write_run(name: str, config: dict, *, data_root: str | None = None) -> dict:
    text = json.dumps(config, indent=4)
    (RUN_CONFIGS / f"{name}.json").write_text(text, encoding="utf-8", newline="\n")
    dataroot = RUN_CONFIGS / f"{name}.dataroot"
    if data_root:
        dataroot.write_text(data_root + "\n", encoding="utf-8", newline="\n")
    elif dataroot.exists():
        dataroot.unlink()
    return {"name": name, "config_sha": hashlib.sha256(text.encode("utf-8")).hexdigest(), "data_root": data_root or "data"}


def wide_run(name: str, rows: dict, window: tuple[str, str], base: dict, tickers: set[str], *, data_root: str, locks: bool = False, config_for=None) -> dict:
    """A target-path run on a wide root. The run's universe is only the names its weight file holds, which keeps Lean's memory bounded."""
    WEIGHTS.mkdir(parents=True, exist_ok=True)
    sha = write_weight_file(rows, WEIGHTS / f"{name}.csv")
    universe = config_for(base, tickers) if config_for else wide_config_for(base, ROOT, tickers, data_dir=data_root)
    config = target_path_config(universe, weights_path=f"ml/evaluation/v660/weights/{name}.csv", weights_sha256=sha, window=window, locks=locks)
    config["phase_v2"]["target_weights"].update(WIDE_PATH)
    return {**write_run(name, config, data_root=data_root), "weights_sha": sha, "rows": len(rows)}


def stopping_name(panel, side_names: list[str], window: tuple[str, str]) -> str | None:
    """A side-A name whose bars stop inside the window, to prove `no_bar_exit` in Lean. None if the window has no such name."""
    index = panel.index()
    first, last = np.searchsorted(panel.dates, window[0]), np.searchsorted(panel.dates, window[1])
    for ticker in sorted(side_names):
        column = panel.closes[:, index[ticker]]
        if np.isfinite(column[first]) and not np.isfinite(column[last]):
            return ticker
    return None


def synthetic_stop(root: Path, ticker: str, stop_date: str, data_dir: str) -> dict:
    """Cuts one side-A name's bars at `stop_date` in a copy under its own ticker: a stock that stops, when the window's real data holds none."""
    from data_pipeline.data_audit import read_lean_daily_zip
    from data_pipeline.yfinance_backfill import scale_for_lean, write_lean_zip

    source = root / data_dir / "equity" / "usa" / "daily" / f"{ticker.lower()}.zip"
    frame = read_lean_daily_zip(source, "equity")
    frame = frame[frame["date"] <= pd.Timestamp(stop_date)]
    rows = [{"date": row.date.date(), "open": row.open, "high": row.high, "low": row.low, "close": row.close, "volume": row.volume} for row in frame.itertuples()]
    name = "ZZSTOP"
    write_lean_zip(root / data_dir / "equity" / "usa" / "daily" / f"{name.lower()}.zip", name, scale_for_lean(rows, "equity"), merge_with_existing=False)
    return {"ticker": name, "first": frame["date"].iloc[0].strftime("%Y-%m-%d"), "last": frame["date"].iloc[-1].strftime("%Y-%m-%d")}


def make_instrument() -> dict:
    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    project = project_tickers(base, "equity")
    manifest = json.loads((ROOT / "data_wide" / "wide_manifest.json").read_text(encoding="utf-8"))
    side_a = sorted(ticker for ticker, entry in manifest["tickers"].items() if entry.get("member") and name_side(ticker, [*project, *SECTOR_ETFS]) == "A")
    usable = [ticker for ticker in side_a if manifest["tickers"][ticker]["first"] < WIDE_WINDOW[0] and manifest["tickers"][ticker]["last"] > WIDE_WINDOW[1]]
    runs: dict[str, dict] = {}

    # BT24: the installed config on the phase's code, order for order with the pin
    gated = copy.deepcopy(base)
    gated["runtime"]["lean_window_override"] = {"start": "2023-07-01", "end": "2026-11-02"}
    runs["v660_bt24"] = {**write_run("v660_bt24", gated), "role": "plumbing", "is": f"equals {PIN}, order for order"}

    # BT25: random long/short ranks across 250 side-A names, and one that stops trading
    stop = synthetic_stop(ROOT, sorted(usable)[0], "2015-03-31", "data_wide")
    names = sorted(usable)[1:250]
    universe = {*names, stop["ticker"]}
    wide_tickers = dict(manifest["tickers"])
    wide_tickers[stop["ticker"]] = {"first": stop["first"], "last": stop["last"], "member": True}

    def config_for(config_base: dict, tickers: set[str]) -> dict:
        from build_wide_root import wide_config

        return wide_config(config_base, {"tickers": wide_tickers}, tickers=tickers, keep_project_crypto=False)

    panel = load_market_panel(ROOT, config_for(base, universe), data_dir="data_wide")
    rows = random_weights(panel, sorted(universe), seed=25, start=WIDE_WINDOW[0], end=WIDE_WINDOW[1], every=20, gross=1.2, neutral=True)
    runs["v660_bt25"] = {**wide_run("v660_bt25", rows, WIDE_WINDOW, base, universe, data_root="data_wide", config_for=config_for), "role": "plumbing", "stops": stop}

    # BT26: BT25 with locks low enough to trip, proving liquidation on the equity path
    sha = write_weight_file(rows, WEIGHTS / "v660_bt26.csv")
    locked = target_path_config(config_for(base, universe), weights_path="ml/evaluation/v660/weights/v660_bt26.csv", weights_sha256=sha, window=WIDE_WINDOW, locks=True)
    locked["phase_v2"]["target_weights"].update(WIDE_PATH)
    locked["phase6"]["risk"]["max_total_drawdown_pct"] = 0.02
    runs["v660_bt26"] = {**write_run("v660_bt26", locked, data_root="data_wide"), "role": "plumbing", "is": "a lock at 2% must close the book"}

    # BT27: oracle on side-A coins inside CS, including a coin that later delisted
    crypto = json.loads((ROOT / "data_crypto_wide" / "crypto_wide_manifest.json").read_text(encoding="utf-8"))
    project_coins = project_tickers(base, "crypto")
    side_a_coins = sorted(entry["ticker"] for entry in crypto["coins"].values() if coin_side(entry["ticker"], project_coins) == "A")
    alive = [coin["ticker"] for coin in crypto["coins"].values() if coin["ticker"] in side_a_coins and coin["first"] < CRYPTO_WINDOW[0] and coin["last"] >= CRYPTO_WINDOW[1]]
    died = [coin["ticker"] for coin in crypto["coins"].values() if coin["ticker"] in side_a_coins and coin["first"] < "2020-06-30" and CRYPTO_WINDOW[0] < coin["last"] < "2021-09-30"]
    coins = sorted({*alive[:12], *died[:2], "BTCUSD"})

    def crypto_config(config_base: dict, tickers: set[str]) -> dict:
        config = copy.deepcopy(config_base)
        config["phase1"]["universe"]["assets"] = [
            {"ticker": coin, "security_type": "crypto", "market": "coinbase", "data_path": f"data/crypto/coinbase/daily/{coin.lower()}_trade.zip"} for coin in sorted(tickers)
        ] + [{"ticker": ticker, "security_type": "equity", "market": "usa", "data_path": f"data/equity/usa/daily/{ticker.lower()}.zip"} for ticker in ("SPY", "AGG")]
        return config

    crypto_panel = load_market_panel(ROOT, crypto_config(base, set(coins)), data_dir="data_crypto_wide")
    oracle = oracle_weights(crypto_panel, coins, start=CRYPTO_WINDOW[0], end=CRYPTO_WINDOW[1], every=20, gross=0.3)
    # crypto is long-only on this path; the book keeps the winners' half
    oracle = {date: {ticker: weight for ticker, weight in row.items() if weight > 0.0} for date, row in oracle.items()}
    # hold a dead coin across its last bar, or nothing here tests the exit: an oracle reads its label, so it would never buy one that is about to stop
    dead = died[0]
    dead_last = next(coin["last"] for coin in crypto["coins"].values() if coin["ticker"] == dead)
    last_row = max(date for date in oracle if date < dead_last)
    oracle[last_row] = {**oracle[last_row], dead: 0.02}
    runs["v660_bt27"] = {**wide_run("v660_bt27", oracle, CRYPTO_WINDOW, base, set(coins), data_root="data_crypto_wide", config_for=crypto_config), "role": "plumbing", "died": died[:2]}

    (OUT / "instrument_manifest.json").write_text(json.dumps(runs, indent=1), encoding="utf-8", newline="\n")
    return runs


def compare(name: str, run_dir: Path) -> dict:
    """R-INSTR2 for one finished run: daily correlation and annual gap of the engine against Lean, and fees."""
    from evaluation.backtest_audit import daily_equity_from_chart, load_backtest_run

    run_config = json.loads((RUN_CONFIGS / f"{name}.json").read_text(encoding="utf-8"))
    dataroot = RUN_CONFIGS / f"{name}.dataroot"
    data_dir = dataroot.read_text(encoding="utf-8").strip() if dataroot.exists() else "data"
    panel = load_market_panel(ROOT, run_config, data_dir=data_dir)
    target = run_config["phase_v2"]["target_weights"]
    window = run_config["runtime"]["lean_window_override"]
    rf_dates, rf_rates = load_rate_series(ROOT / data_dir / "alternative" / "interest-rate" / "usa" / "interest-rate.csv")
    kill = run_config["phase_v2"]["risk"]["kill_switch"]
    engine = simulate_target_weights(
        load_weight_file(ROOT / target["weights_path"], target["weights_sha256"]), panel, resolve_target_weights_config(target), start=window["start"], end=window["end"],
        sweep_config=run_config["phase_v2"]["cash_sweep"], rf_dates=rf_dates, rf_rates=rf_rates, carry_fn=lambda ticker, date: 0.0,
        max_total_drawdown=run_config["phase6"]["risk"]["max_total_drawdown_pct"], max_drawdown_velocity=kill["max_drawdown_velocity_pct_per_bar"],
    )
    run = load_backtest_run(run_dir)
    points = daily_equity_from_chart(run["result"])
    nav = pd.Series(dict(points), dtype=float).sort_index()
    nav = nav[(nav.index >= window["start"]) & (nav.index <= window["end"])]
    lean = nav.pct_change().dropna()
    joined = pd.concat([lean, engine["total"]], axis=1, join="inner").dropna()
    joined.columns = ["lean", "engine"]
    years = max(len(nav) / 365.25, 1e-9)
    lean_annual = float((nav.iloc[-1] / nav.iloc[0]) ** (1.0 / years) - 1.0)
    engine_annual = float((1.0 + engine["total"]).prod() ** (1.0 / years) - 1.0)
    stats = (run["result"].get("statistics") or run["result"].get("Statistics") or {})
    fees_text = str(stats.get("Total Fees", "") or "").replace("$", "").replace(",", "")
    lean_fees = float(fees_text) if fees_text else None
    report = {
        "name": name, "run": str(run_dir), "days": len(joined), "correlation": float(joined.corr().iloc[0, 1]) if len(joined) > 2 else None,
        "lean_annual": lean_annual, "engine_annual": engine_annual, "annual_gap_bps": abs(lean_annual - engine_annual) * 1e4, "lean_fees": lean_fees, "engine_fees": float(engine["fees"]),
        "fees_within_2pct": None if not lean_fees else abs(lean_fees - float(engine["fees"])) / lean_fees <= 0.02, "no_bar_exits": engine["no_bar_exits"], "locked_on": engine.get("locked_on"),
    }
    report["passes_r_instr2"] = bool(report["correlation"] is not None and report["correlation"] >= 0.99 and report["annual_gap_bps"] <= 100.0 and report["fees_within_2pct"] in (True, None))
    results_path = OUT / "instrument_result.json"
    results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.exists() else {}
    results[name] = report
    results_path.write_text(json.dumps(results, indent=1), encoding="utf-8", newline="\n")
    return report


def compare_orders(first: Path, second: Path) -> dict:
    """Are two runs the same order for order? Time, symbol and quantity of every fill."""
    from evaluation.backtest_audit import load_backtest_run
    from evaluation.lean_attribution import fills_from_order_events

    def fills(path: Path) -> list[tuple]:
        return sorted((str(fill.date), fill.ticker, round(float(fill.quantity), 8)) for fill in fills_from_order_events(load_backtest_run(path).get("order_events", [])))

    a, b = fills(first), fills(second)
    report = {"first": str(first), "second": str(second), "fills_first": len(a), "fills_second": len(b), "equal": a == b}
    if a != b:
        report["only_first"] = sorted(set(a) - set(b))[:10]
        report["only_second"] = sorted(set(b) - set(a))[:10]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="stage", required=True)
    commands.add_parser("instrument")
    one = commands.add_parser("compare")
    one.add_argument("name")
    one.add_argument("run")
    orders = commands.add_parser("orders")
    orders.add_argument("first")
    orders.add_argument("second")
    args = parser.parse_args()
    if args.stage == "instrument":
        print(json.dumps(make_instrument(), indent=1))
    elif args.stage == "compare":
        print(json.dumps(compare(args.name, Path(args.run)), indent=1))
    else:
        print(json.dumps(compare_orders(Path(args.first), Path(args.second)), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
