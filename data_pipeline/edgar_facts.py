"""Point-in-time quarterly earnings per share from SEC EDGAR (V6.5.0, free, no account).

`companyfacts` keeps every filing of a figure with its `filed` date, so a backtest can see what was public on a day and
not what was later restated: a quarter's first filing is kept, and it is usable on the first session after that date.

SEC requires a contact in the client name: set AQ_SEC_CONTACT for the run, so that no address enters the repository. Requests stay
under SEC's limit of 10 per second.

    python -m data_pipeline.edgar_facts --apply
    python -m data_pipeline.edgar_facts --apply --splits
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time as _time
from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

OUTPUT = Path(__file__).resolve().parent.parent / "data" / "reference" / "edgar_eps.csv"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
USER_AGENT = "AetherQuantResearch/6.5 (github.com/leon1706-lol/Aether-quant)"
CONTACT_ENV = "AQ_SEC_CONTACT"
TICKER_ALIASES = {"FB": "META"}  # the universe keeps the old ticker; SEC's list has only the new one
EPS_TAGS = ("EarningsPerShareDiluted", "EarningsPerShareBasic")
MIN_QUARTER_DAYS, MAX_QUARTER_DAYS = 75, 105
SURPRISE_HISTORY, MIN_SURPRISE_HISTORY = 8, 4
YEAR_MIN_DAYS, YEAR_MAX_DAYS = 350, 380
SPLITS_OUTPUT = OUTPUT.with_name("equity_splits.csv")


def quarterly_first_filings(facts: dict) -> list[dict]:
    """{period_start, period_end, filed, eps} for every standalone quarter, first filing only. Year-to-date and annual
    figures are dropped by their duration; the first tag with data wins."""
    usgaap = ((facts or {}).get("facts") or {}).get("us-gaap") or {}
    for tag in EPS_TAGS:
        units = (usgaap.get(tag) or {}).get("units") or {}
        entries = units.get("USD/shares") or []
        first: dict[tuple[str, str], dict] = {}
        for entry in entries:
            start, end, filed, value = entry.get("start"), entry.get("end"), entry.get("filed"), entry.get("val")
            if not (start and end and filed) or value is None:
                continue
            days = (date.fromisoformat(end) - date.fromisoformat(start)).days
            if not MIN_QUARTER_DAYS <= days <= MAX_QUARTER_DAYS:
                continue
            key = (start, end)
            if key not in first or filed < first[key]["filed"]:
                first[key] = {"period_start": start, "period_end": end, "filed": filed, "eps": float(value)}
        if first:
            return sorted(first.values(), key=lambda row: row["period_end"])
    return []


def user_agent() -> str:
    """SEC refuses a client with no contact. The address comes from the environment so that it never enters the repository."""
    contact = os.environ.get(CONTACT_ENV, "").strip()
    return f"AetherQuantResearch/6.5 {contact}" if contact else USER_AGENT


def _get_json(url: str) -> dict:
    import requests

    response = requests.get(url, timeout=60, headers={"User-Agent": user_agent(), "Accept": "application/json"})
    response.raise_for_status()
    return response.json()


def fetch_eps(tickers: Iterable[str], get_json: Callable[[str], dict] = _get_json, pause_seconds: float = 0.15) -> tuple[list[dict], list[str]]:
    """(rows with a `ticker`, tickers with no data). A ticker that fails is reported, never guessed."""
    directory = get_json(TICKERS_URL)
    cik_by_ticker = {str(item["ticker"]).upper(): int(item["cik_str"]) for item in directory.values()}
    rows: list[dict] = []
    missing: list[str] = []
    for ticker in tickers:
        cik = cik_by_ticker.get(TICKER_ALIASES.get(str(ticker).upper(), str(ticker).upper()))
        if cik is None:
            missing.append(ticker)
            continue
        try:
            quarters = quarterly_first_filings(get_json(FACTS_URL.format(cik=cik)))
        except Exception as error:  # one failed company must not lose the others
            print(f"{ticker}: {error}")
            quarters = []
        if not quarters:
            missing.append(ticker)
        rows.extend({"ticker": ticker, **quarter} for quarter in quarters)
        if pause_seconds:
            _time.sleep(pause_seconds)
    return rows, missing


def write_eps(rows: list[dict], path: Path = OUTPUT) -> None:
    with Path(path).open("w", newline="\n", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker", "period_start", "period_end", "filed", "eps"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_eps(path: Path = OUTPUT) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"ticker": str, "period_start": str, "period_end": str, "filed": str})


def fetch_splits(tickers: Iterable[str]) -> list[dict]:
    """{ticker, date, ratio} from Yahoo. A ticker that fails stops the run: a silently missing split reads as a large miss."""
    import yfinance

    rows: list[dict] = []
    for ticker in tickers:
        splits = yfinance.Ticker(TICKER_ALIASES.get(ticker, ticker)).splits
        rows.extend({"ticker": ticker, "date": day.strftime("%Y-%m-%d"), "ratio": float(ratio)} for day, ratio in splits.items() if float(ratio) > 0.0)
    return rows


def write_splits(rows: list[dict], path: Path = SPLITS_OUTPUT) -> None:
    with Path(path).open("w", newline="\n", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker", "date", "ratio"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_splits(path: Path = SPLITS_OUTPUT) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"ticker": str, "date": str})


def split_adjusted_eps(eps: pd.DataFrame, splits: pd.DataFrame) -> pd.DataFrame:
    """EPS on one share basis per ticker. A first filing states EPS on the shares at its filing date, so it is divided by
    the splits after that date. A later split scales a ticker's whole history alike, so a standardised ratio sees no future."""
    adjusted = eps.copy()
    by_ticker = {ticker: group for ticker, group in splits.groupby("ticker")}

    def divisor(row) -> float:
        group = by_ticker.get(row["ticker"])
        if group is None:
            return 1.0
        return float(group.loc[group["date"] > row["filed"], "ratio"].prod())

    if len(adjusted):
        adjusted["eps"] = adjusted["eps"] / adjusted.apply(divisor, axis=1)
    return adjusted


def standardised_surprises(group: pd.DataFrame) -> np.ndarray:
    """One ticker's rows sorted by period end: the change from the same quarter a year earlier, over the spread of the
    latest earlier changes. Every input was filed by this row's filing date."""
    ends = pd.to_datetime(group["period_end"]).to_numpy()
    filed = group["filed"].to_numpy(dtype=str)
    values = group["eps"].to_numpy(dtype=float)
    size = len(group)
    changes = np.full(size, np.nan)
    surprises = np.full(size, np.nan)
    for row in range(size):
        for earlier in range(row - 1, -1, -1):
            days = int((ends[row] - ends[earlier]) / np.timedelta64(1, "D"))
            if days > YEAR_MAX_DAYS:
                break
            if days >= YEAR_MIN_DAYS and filed[earlier] <= filed[row]:
                changes[row] = values[row] - values[earlier]
                break
        past = [changes[earlier] for earlier in range(row) if np.isfinite(changes[earlier]) and filed[earlier] <= filed[row]][-SURPRISE_HISTORY:]
        if np.isfinite(changes[row]) and len(past) >= MIN_SURPRISE_HISTORY:
            spread = float(np.std(past, ddof=1))
            if spread > 0.0:
                surprises[row] = changes[row] / spread
    return surprises


def surprise_table(eps: pd.DataFrame, sessions: list[str], columns: list[str], *, hold_sessions: int) -> pd.DataFrame:
    """session x ticker: `standardised_surprises` of the latest filing, from the session after it was filed for
    `hold_sessions` sessions; NaN otherwise, so a ticker is ranked only while its news is recent. Pass split-adjusted EPS."""
    sorted_sessions = np.asarray(sessions)
    table = pd.DataFrame(np.nan, index=sessions, columns=columns, dtype=float)
    for ticker, group in eps.groupby("ticker"):
        if ticker not in table.columns:
            continue
        group = group.sort_values("period_end").reset_index(drop=True)
        surprise = standardised_surprises(group)
        for row in range(len(group)):
            value = surprise[row]
            if not np.isfinite(value):
                continue
            first = int(np.searchsorted(sorted_sessions, group["filed"].iloc[row], side="right"))
            if first >= len(sessions):
                continue
            stop = min(first + hold_sessions, len(sessions))
            table.iloc[first:stop, table.columns.get_loc(ticker)] = float(value)
    return table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--splits", action="store_true", help="with --apply: refresh the split list from Yahoo instead of the EPS file")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parent.parent / "config.json"))
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    tickers = [str(asset["ticker"]) for asset in config["phase1"]["universe"]["assets"]
               if asset.get("security_type") == "equity" and not asset.get("asset_class")]
    if not args.apply:
        print(f"would fetch {len(tickers)} tickers into {OUTPUT}")
        return 0
    if args.splits:
        rows = fetch_splits(tickers)
        write_splits(rows)
        print(f"{len(rows)} splits for {len({row['ticker'] for row in rows})} tickers -> {SPLITS_OUTPUT}")
        return 0
    rows, missing = fetch_eps(tickers)
    write_eps(rows)
    print(f"{len(rows)} quarters for {len(tickers) - len(missing)} tickers -> {OUTPUT}; no data for: {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
