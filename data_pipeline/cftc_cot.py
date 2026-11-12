"""CFTC Commitments of Traders positioning (V6.5.0, free, no account): speculators' net position as a share of open interest.

The report is dated Tuesday and published Friday afternoon, after the equity close, so a row is first usable on the next
session after `publication_date` (report date + 3 days); keying on the report date would read three days ahead.

    python -m data_pipeline.cftc_cot --apply --start-year 2005
"""

from __future__ import annotations

import argparse
import csv
import io
import zipfile
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

OUTPUT = Path(__file__).resolve().parent.parent / "data" / "reference" / "cot_positioning.csv"
URL = "https://www.cftc.gov/files/dea/history/deacot{year}.zip"
PUBLICATION_LAG_DAYS = 3
CHANGE_WEEKS = 13

# market key -> the CFTC market names it has appeared under
MARKETS = {
    "EUR": ("EURO FX - CHICAGO MERCANTILE EXCHANGE",),
    "JPY": ("JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE",),
    "GBP": ("BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE", "BRITISH POUND - CHICAGO MERCANTILE EXCHANGE"),
    "AUD": ("AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",),
    "CAD": ("CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",),
    "CHF": ("SWISS FRANC - CHICAGO MERCANTILE EXCHANGE",),
    "NZD": ("NEW ZEALAND DOLLAR - CHICAGO MERCANTILE EXCHANGE", "NZ DOLLAR - CHICAGO MERCANTILE EXCHANGE"),
    "UST10": ("10-YEAR U.S. TREASURY NOTES - CHICAGO BOARD OF TRADE", "UST 10Y NOTE - CHICAGO BOARD OF TRADE"),
    "SPX": ("E-MINI S&P 500 STOCK INDEX - CHICAGO MERCANTILE EXCHANGE", "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE"),
}
_KEY_BY_NAME = {name: key for key, names in MARKETS.items() for name in names}


def parse_annual_text(text: str) -> list[dict]:
    """Rows of one `annual.txt`, for the markets above: {report_date, publication_date, market, net_pct_oi}. A row with a
    missing or zero open interest is dropped."""
    rows: list[dict] = []
    for row in csv.DictReader(io.StringIO(text)):
        key = _KEY_BY_NAME.get(str(row.get("Market and Exchange Names", "")).strip())
        if key is None:
            continue
        try:
            open_interest = float(row["Open Interest (All)"])
            long_positions = float(row["Noncommercial Positions-Long (All)"])
            short_positions = float(row["Noncommercial Positions-Short (All)"])
            report = date.fromisoformat(str(row["As of Date in Form YYYY-MM-DD"]).strip())
        except (KeyError, TypeError, ValueError):
            continue
        if open_interest <= 0.0:
            continue
        rows.append({
            "report_date": report.isoformat(),
            "publication_date": (report + timedelta(days=PUBLICATION_LAG_DAYS)).isoformat(),
            "market": key,
            "net_pct_oi": (long_positions - short_positions) / open_interest,
        })
    return rows


def parse_zip_bytes(payload: bytes) -> list[dict]:
    """Rows of the first text file in a CFTC Commitments of Traders zip, or [] when it holds none."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        name = next((item for item in archive.namelist() if item.lower().endswith(".txt")), None)
        return parse_annual_text(archive.read(name).decode("latin-1")) if name else []


def _download(url: str) -> bytes:
    import requests

    response = requests.get(url, timeout=120, headers={"User-Agent": "AetherQuantResearch/6.5 (github.com/leon1706-lol/Aether-quant)"})
    response.raise_for_status()
    return response.content


def fetch_years(years: Iterable[int], fetch_fn: Callable[[str], bytes] = _download) -> list[dict]:
    rows: list[dict] = []
    for year in years:
        rows.extend(parse_zip_bytes(fetch_fn(URL.format(year=year))))
    return sorted(rows, key=lambda row: (row["report_date"], row["market"]))


def write_positioning(rows: list[dict], path: Path = OUTPUT) -> None:
    with Path(path).open("w", newline="\n", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["report_date", "publication_date", "market", "net_pct_oi"], lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "net_pct_oi": f"{row['net_pct_oi']:.6f}"})


def read_positioning(path: Path = OUTPUT) -> pd.DataFrame:
    """Read the cached CFTC positioning table, with its dates and market as strings."""
    return pd.read_csv(path, dtype={"report_date": str, "publication_date": str, "market": str})


def change_by_session(positioning: pd.DataFrame, sessions: list[str], weeks: int = CHANGE_WEEKS) -> pd.DataFrame:
    """session x market: the `weeks`-report change in net positioning, as known at each session's close. A report
    published on date P (after the close) is usable on the first session after P."""
    frame = positioning.sort_values("report_date")
    pivot = frame.pivot_table(index="publication_date", columns="market", values="net_pct_oi", aggfunc="last").sort_index()
    change = pivot - pivot.shift(weeks)
    union = change.reindex(sorted(set(change.index) | set(sessions))).ffill()
    # shift(1) over the union: a row published on a session date is first read on the next entry
    return union.shift(1).reindex(sessions)


def fx_pair_scores(change: pd.DataFrame, pairs: Iterable[str]) -> pd.DataFrame:
    """Each pair's score: the change in speculators' positioning in its base currency minus that in its quote currency
    (the dollar has no contract of its own and counts as zero)."""
    out = {}
    for pair in pairs:
        base, quote = pair[:3], pair[3:]
        first = change[base] if base in change else (0.0 if base == "USD" else np.nan)
        second = change[quote] if quote in change else (0.0 if quote == "USD" else np.nan)
        out[pair] = first - second
    return pd.DataFrame(out, index=change.index)


def macro_scores(change: pd.DataFrame) -> pd.DataFrame:
    """Direction for the index and the bond ETFs from the S&P and 10-year contracts."""
    return pd.DataFrame(
        {"SPY": np.sign(change["SPX"]), "IEF": np.sign(change["UST10"]), "TLT": np.sign(change["UST10"])}, index=change.index
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="download and write; without it, only prints what would be done")
    parser.add_argument("--start-year", type=int, default=2005)
    parser.add_argument("--end-year", type=int, default=date.today().year)
    args = parser.parse_args(argv)
    years = range(args.start_year, args.end_year + 1)
    if not args.apply:
        print(f"would fetch {len(list(years))} years into {OUTPUT}")
        return 0
    rows = fetch_years(years)
    write_positioning(rows)
    print(f"{len(rows)} rows, {rows[0]['report_date']}..{rows[-1]['report_date']} -> {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
