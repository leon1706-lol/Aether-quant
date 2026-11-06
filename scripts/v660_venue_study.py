"""Evidence for the owner's live crypto venue decision (Problems.md #192). IB can't fill spot crypto, and the installed sleeve is crypto.

Measures how closely spot ETFs a stock broker can fill track the coins, and writes one Lean run of the sleeve's BTC and ETH legs on those
ETFs. It decides nothing. Fees and access in `ROUTES` come from each provider's public terms as of writing and are to be checked before use.

    python scripts/v660_venue_study.py make    # fetches the ETFs into data_wide, tracking, the run config
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

from build_wide_root import fetch_adjusted_and_raw  # noqa: E402
from v650_instrument import target_path_config  # noqa: E402
from v660_lean import WEIGHTS, write_run  # noqa: E402

from data_pipeline.data_audit import read_lean_daily_zip  # noqa: E402
from data_pipeline.yfinance_backfill import sanitize_ohlc, scale_for_lean, write_lean_zip  # noqa: E402
from portfolio.target_weights import load_weight_file, write_weight_file  # noqa: E402

OUT = ROOT / "ml" / "evaluation" / "v660"
PROXIES = {"BTCUSD": "IBIT", "ETHUSD": "ETHA"}
FIRST_FULL_DATE = "2024-08-01"  # ETHA listed in July 2024
ROUTES = {
    "coinbase_direct": {
        "instruments": "all 12 coins of the sleeve", "account": "a Coinbase account: not one this project has", "fee_model": "the blocking cost of every run, up to 80 bps taker + 10 bps slippage",
        "note": "Lean's Coinbase brokerage supports crypto on cash accounts, so the book is long-only there, which the sleeve already is.",
    },
    "ib_spot_etfs": {
        "instruments": "IBIT and ETHA: BTC and ETH only, so the sleeve's other 10 coins have no route", "account": "the existing IB route", "fee_model": "equity commission and ETF spread, plus each fund's 0.25% a year expense ratio",
        "note": "EU retail clients generally can't buy US-domiciled ETFs (PRIIPs): check the owner's account class before relying on this route. Equivalent UCITS or ETP listings were not studied.",
    },
    "ib_cme_micro_futures": {
        "instruments": "CME micro bitcoin and micro ether futures", "account": "the existing IB route, with futures permissions", "fee_model": "exchange and IB fees per contract, plus the basis and roll",
        "note": "A contract is 0.1 BTC or 0.1 ETH: at this sleeve's sizes on $100k, the position rounds to at most a contract or two, so it can't track. Not run.",
    },
}


def fetch_proxies(root: Path) -> dict:
    report = {}
    for ticker in PROXIES.values():
        path = root / "equity" / "usa" / "daily" / f"{ticker.lower()}.zip"
        rows, _ = fetch_adjusted_and_raw(ticker, "2024-01-01", "2026-11-03")
        rows, _ = sanitize_ohlc(rows)
        if not rows:
            report[ticker] = {"status": "no bars"}
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        write_lean_zip(path, ticker, scale_for_lean(rows, "equity"), merge_with_existing=False)
        report[ticker] = {"status": "ok", "first": rows[0]["date"].isoformat(), "last": rows[-1]["date"].isoformat(), "rows": len(rows)}
    return report


def tracking(root: Path) -> dict:
    """ETF session return against its coin over the same span. A coin's bar closes at midnight UTC and the fund's at 4pm New York, so a daily
    correlation understates the link: the weekly one is the fairer figure."""
    report = {}
    for coin, ticker in PROXIES.items():
        etf = read_lean_daily_zip(root / "equity" / "usa" / "daily" / f"{ticker.lower()}.zip", "equity")
        spot = read_lean_daily_zip(ROOT / "data" / "crypto" / "coinbase" / "daily" / f"{coin.lower()}_trade.zip", "crypto")
        etf_close = etf.set_index(etf["date"].dt.strftime("%Y-%m-%d"))["close"]
        spot_close = spot.set_index(spot["date"].dt.strftime("%Y-%m-%d"))["close"]
        both = pd.concat({"etf": etf_close, "coin": spot_close.shift(1).reindex(etf_close.index)}, axis=1).dropna()
        daily = both.pct_change().dropna()
        weekly = both.iloc[::5].pct_change().dropna()
        report[ticker] = {
            "coin": coin, "sessions": len(daily), "daily_correlation": float(daily.corr().iloc[0, 1]), "weekly_correlation": float(weekly.corr().iloc[0, 1]),
            "annual_return_gap": float(((1.0 + daily["etf"]).prod() ** (252.0 / len(daily)) - 1.0) - ((1.0 + daily["coin"]).prod() ** (252.0 / len(daily)) - 1.0)),
            "weekly_tracking_error_annual": float((weekly["etf"] - weekly["coin"]).std(ddof=1) * np.sqrt(52.0)),
        }
    return report


def proxy_rows(weights: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    """The sleeve's rows with BTC and ETH on their ETFs, and nothing for coins with no route. A flat row stays flat."""
    return {date: {PROXIES[ticker]: weight for ticker, weight in row.items() if ticker in PROXIES} for date, row in weights.items() if date >= FIRST_FULL_DATE}


def make() -> dict:
    root = ROOT / "data_wide"
    fetched = fetch_proxies(root)
    report = {"routes": ROUTES, "fetched": fetched, "tracking": tracking(root)}
    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    target = base["phase_v2"]["target_weights"]
    rows = proxy_rows(load_weight_file(ROOT / target["weights_path"], target["weights_sha256"]))
    WEIGHTS.mkdir(parents=True, exist_ok=True)
    sha = write_weight_file(rows, WEIGHTS / "v660_venue_etf.csv")
    config = dict(base)
    config["phase1"] = {**base["phase1"], "universe": {**base["phase1"]["universe"], "assets": [
        {"ticker": ticker, "security_type": "equity", "market": "usa", "data_path": f"data/equity/usa/daily/{ticker.lower()}.zip"} for ticker in ("SPY", "AGG", *PROXIES.values())
    ]}}
    run = target_path_config(config, weights_path="ml/evaluation/v660/weights/v660_venue_etf.csv", weights_sha256=sha, window=(FIRST_FULL_DATE, "2026-11-02"))
    report["run"] = {**write_run("v660_venue_etf", run, data_root="data_wide"), "weights_sha": sha, "role": "plumbing"}
    (OUT / "venue_study.json").write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["make"])
    parser.parse_args()
    print(json.dumps(make(), indent=1)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
