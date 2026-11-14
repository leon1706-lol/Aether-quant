"""A small wide equity root and a small wide crypto root for `evaluation/wide_context.py` (V6.6.6, #359): Lean zips, the manifests, sectors, S&P 500 membership, raw closes, EDGAR-shaped fundamentals and Binance-shaped
quote volume for names the research cells' hash puts on side A, so a free cell (`SV`, `CS`) opens on them."""

from __future__ import annotations

import datetime
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

import train_world as world
from evaluation.research_cells import coin_side, name_side

REPO = Path(__file__).resolve().parents[1]
FIRST = datetime.date(2017, 1, 2)
LAST = datetime.date(2022, 12, 30)
SECTORS = ["information_technology", "financials", "energy", "health_care"]


def side_a_equities(count: int = 14) -> list[str]:
    names = []
    for number in range(400):
        candidate = f"WQ{number:03d}"
        if name_side(candidate, world.EQUITIES + world.BONDS) == "A":
            names.append(candidate)
        if len(names) == count:
            break
    return names


def side_a_coins(count: int = 12) -> list[str]:
    coins = []
    for number in range(400):
        candidate = f"CQ{number:03d}USD"
        if coin_side(candidate, ["BTCUSD", "ETHUSD"]) == "A":
            coins.append(candidate)
        if len(coins) == count:
            break
    return coins


def weekdays() -> list[datetime.date]:
    out, day = [], FIRST
    while day <= LAST:
        if day.weekday() < 5:
            out.append(day)
        day += datetime.timedelta(days=1)
    return out


def all_days() -> list[datetime.date]:
    return [FIRST + datetime.timedelta(days=offset) for offset in range((LAST - FIRST).days + 1)]


def write_series(path: Path, dates: list[datetime.date], seed: int, *, equity: bool, start: float = 50.0) -> dict[str, float]:
    closes = world.path_walk(seed, len(dates), start, 0.012)
    rng = np.random.default_rng(seed + 50)
    lines, raw = [], {}
    previous = closes[0]
    for date, close in zip(dates, closes):
        open_, high, low, close = world.bar(float(close), float(previous), rng)
        previous = close
        volume = float(abs(rng.normal(2_000_000, 300_000)))
        stamp = date.strftime("%Y%m%d") + " 00:00"
        scale = 10000 if equity else 1
        lines.append(f"{stamp},{open_ * scale},{high * scale},{low * scale},{close * scale},{volume}")
        raw[date.isoformat()] = close
    world.write_zip(path, path.stem + ".csv", lines)
    return raw


def fundamentals_rows(tickers: list[str]) -> pd.DataFrame:
    rows = []
    for ticker in tickers:
        for year in (2016, 2017, 2018, 2019, 2020, 2021):
            filed = f"{year + 1}-03-02"
            for field, value in (("assets", 100.0 + year), ("equity", 50.0), ("gross_profit", 30.0), ("revenue", 60.0), ("cost_of_revenue", 30.0), ("net_income", 10.0),
                                 ("operating_cash_flow", 12.0), ("long_term_debt", 20.0), ("shares_outstanding", 1000.0 + year)):
                rows.append({"ticker": ticker, "field": field, "period_end": f"{year}-12-31", "filed": filed, "form": "10-K", "value": value})
    return pd.DataFrame(rows)


def build_equity_root(tmp_path: Path, *, with_info: bool = True) -> tuple[Path, dict]:
    root = tmp_path / "wide_project"
    data = root / "data_wide"
    names = side_a_equities()
    tickers = names + ["SPY", "AGG", "BIL", "TLT", "XLK"]
    manifest = {"tickers": {}}
    reference = data / "reference"
    (reference / "raw_closes").mkdir(parents=True)
    for index, ticker in enumerate(tickers):
        raw = write_series(data / "equity" / "usa" / "daily" / f"{ticker.lower()}.zip", weekdays(), index + 1, equity=True)
        (reference / "raw_closes" / f"{ticker.lower()}.json").write_text(json.dumps(raw), encoding="utf-8")
        manifest["tickers"][ticker] = {"first": FIRST.isoformat(), "last": LAST.isoformat()}
    (data / "wide_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (reference / "sectors.json").write_text(json.dumps({name: SECTORS[index % len(SECTORS)] for index, name in enumerate(names)}), encoding="utf-8")
    (reference / "sp500_ticker_start_end.csv").write_text("ticker,start_date,end_date\n" + "\n".join(f"{name},2010-01-01," for name in names) + "\n", encoding="utf-8")
    if with_info:
        fundamentals_rows(names).to_csv(reference / "edgar_fundamentals.csv.gz", index=False)
        eps_rows = [{"ticker": name, "period_start": f"{year}-{month:02d}-01", "period_end": f"{year}-{month + 2:02d}-28", "filed": f"{year}-{month + 3:02d}-10", "eps": 1.0 + 0.1 * year_index + 0.05 * (month // 3) + (0.2 if year_index % 3 == 0 else 0.0) * name_index}
                    for name_index, name in enumerate(names) for year_index, year in enumerate(range(2016, 2022)) for month in (1, 4, 7)]
        pd.DataFrame(eps_rows).to_csv(reference / "edgar_eps.csv.gz", index=False)
        extended = []
        for name in names:
            for year in (2016, 2017, 2018, 2019, 2020, 2021):
                for field, value in (("short_term_debt", 5.0), ("cash", 10.0), ("ttm_net_income", 8.0 + year - 2016), ("ttm_operating_cash_flow", 12.0), ("assets_q", 100.0), ("capex", 4.0 + year - 2016)):
                    extended.append({"ticker": name, "field": field, "period_end": f"{year}-12-31", "filed": f"{year + 1}-03-02", "form": "10-K", "value": value})
        pd.DataFrame(extended).to_csv(reference / "edgar_fundamentals_ext.csv.gz", index=False)
    scripts = root / "scripts"
    scripts.mkdir()
    shutil.copy(REPO / "scripts" / "build_wide_root.py", scripts / "build_wide_root.py")
    return root, world.build_config()


def build_crypto_root(tmp_path: Path, *, funding: bool = True) -> tuple[Path, dict, list[str]]:
    root = tmp_path / "crypto_project"
    data = root / "data_crypto_wide"
    coins = ["BTCUSD", "ETHUSD"] + side_a_coins()
    manifest = {"coins": {coin: {"ticker": coin} for coin in coins}}
    days = all_days()
    volume = {}
    for index, coin in enumerate(coins):
        write_series(data / "crypto" / "coinbase" / "daily" / f"{coin.lower()}_trade.zip", days, index + 1, equity=False, start=20.0)
        volume[coin] = world.path_walk(index + 100, len(days), 5e6 * (index + 1), 0.05)
    for ticker in ("SPY", "AGG"):
        write_series(data / "equity" / "usa" / "daily" / f"{ticker.lower()}.zip", weekdays(), 7, equity=True)
    (data / "crypto_wide_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    frame = pd.DataFrame(volume, index=pd.Index([day.isoformat() for day in days]))
    reference = data / "reference"
    reference.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(reference / "quote_volume.parquet")
    if funding:
        pd.DataFrame({coin: np.full(len(days), 0.0001) for coin in coins}, index=frame.index).to_parquet(reference / "funding.parquet")
    return root, world.build_config(), coins
