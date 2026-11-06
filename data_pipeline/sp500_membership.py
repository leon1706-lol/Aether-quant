"""Point-in-time S&P 500 membership (V6.6.0): which names a wide-universe book may hold on a date.

Source: github.com/fja05680/sp500, built from Wikipedia's change lists, so it has errors; that is disclosed wherever it is used.
A ticker's bars are used only inside its membership intervals, because tickers get reused: `AAL` was another company in 1996-97.

Yahoo has no delisted names. `coverage_by_year` measures the gap, which R-SURV1 charges against any result.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

SOURCE_URL = "https://raw.githubusercontent.com/fja05680/sp500/master/sp500_ticker_start_end.csv"
MEMBERSHIP_FILE = "sp500_ticker_start_end.csv"
FAR_FUTURE = "9999-12-31"

# Old ticker -> the ticker Yahoo holds the same company's history under. Applied before anything else.
RENAMES = {
    "FB": "META", "ANTM": "ELV", "WLP": "ELV", "ABC": "COR", "RE": "EG", "COG": "CTRA", "HFC": "DINO", "PKI": "RVTY", "FLT": "CPAY",
    "WLTW": "WTW", "PEAK": "DOC", "HCP": "DOC", "ADS": "BFH", "BBT": "TFC", "CBS": "PSKY", "VIAB": "PSKY", "VIAC": "PSKY", "PARA": "PSKY",
    "GPS": "GAP", "BLL": "BALL", "TMK": "GL", "UTX": "RTX", "HRS": "LHX", "SYMC": "GEN", "NLOK": "GEN", "LUK": "JEF", "KORS": "CPRI",
    "FBHS": "FBIN", "CDAY": "DAY", "BHGE": "BKR", "BHI": "BKR", "WYN": "TNL", "WYND": "TNL", "CTL": "LUMN", "DPS": "KDP", "JEC": "J",
    "FI": "FISV", "MMC": "MRSH",
}
# Two share classes, or two tickers of one company, must land on one side of the name split.
ISSUER_TWINS = {
    "GOOG": "GOOGL", "FOX": "FOXA", "NWS": "NWSA", "UA": "UAA", "DISCK": "WBD", "DISCA": "WBD", "DISCB": "WBD", "BF.A": "BF.B",
    "BRK.A": "BRK.B", "LEN.B": "LEN", "HEI.A": "HEI", "CMCSK": "CMCSA", "LBTYK": "LBTYA", "LSXMK": "LSXMA", "TAP.A": "TAP",
}


def yahoo_symbol_for_member(ticker: str) -> str:
    """BRK.B on Lean and in the membership list is BRK-B on Yahoo."""
    return str(ticker).replace(".", "-")


def canonical_issuer(ticker: str) -> str:
    ticker = RENAMES.get(str(ticker), str(ticker))
    return ISSUER_TWINS.get(ticker, ticker)


def parse_membership(text: str) -> dict[str, list[tuple[str, str]]]:
    """{ticker: [(start, end), ...]}, renames merged, sorted. `end` is exclusive and far in the future for a current member."""
    table: dict[str, list[tuple[str, str]]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        ticker = RENAMES.get(row["ticker"].strip(), row["ticker"].strip())
        start = row["start_date"].strip()
        end = row["end_date"].strip() or FAR_FUTURE
        if ticker and start:
            table.setdefault(ticker, []).append((start, end))
    return {ticker: _merged(intervals) for ticker, intervals in table.items()}


def _merged(intervals: list[tuple[str, str]]) -> list[tuple[str, str]]:
    ordered = sorted(intervals)
    merged: list[tuple[str, str]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def fetch_membership(out_dir: Path, get: Callable[[str], str] | None = None) -> dict:
    """Saves the source file and returns {"sha256", "tickers", "intervals"}."""
    if get is None:
        import requests

        def get(url: str) -> str:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            return response.text

    text = get(SOURCE_URL)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / MEMBERSHIP_FILE).write_text(text, encoding="utf-8", newline="\n")
    table = parse_membership(text)
    return {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "tickers": len(table), "intervals": sum(map(len, table.values()))}


def load_membership(path: Path) -> dict[str, list[tuple[str, str]]]:
    return parse_membership(Path(path).read_text(encoding="utf-8"))


def is_member(table: Mapping[str, list[tuple[str, str]]], ticker: str, date: str) -> bool:
    """Inside one of the ticker's intervals on `date`; the end date itself is out."""
    date = str(date)[:10]
    return any(start <= date < end for start, end in table.get(ticker, ()))


def tickers_touching(table: Mapping[str, list[tuple[str, str]]], start: str, end: str) -> list[str]:
    """Members at any point of [start, end]."""
    return sorted(ticker for ticker, intervals in table.items() if any(a <= end and b > start for a, b in intervals))


def suspect_interval(intervals: Iterable[tuple[str, str]], first_bar: str, *, window_start: str, grace_days: int = 30) -> bool:
    """True when the data begins well after a member interval inside the window began: a later company reusing the ticker, or
    a rename missing from RENAMES. Its bars are not this member's, so the name is left out rather than trusted."""
    from datetime import date, timedelta

    first = date.fromisoformat(first_bar[:10])
    earliest = date.fromisoformat(window_start[:10])
    for start, end in intervals:
        begin = max(date.fromisoformat(start[:10]), earliest)
        if date.fromisoformat(end[:10]) > earliest and first > begin + timedelta(days=grace_days):
            return True
    return False


def member_days_by_year(table: Mapping[str, list[tuple[str, str]]], tickers: Iterable[str], first_year: int, last_year: int) -> dict[int, float]:
    """Calendar member-days per year for `tickers`."""
    from datetime import date

    totals = dict.fromkeys(range(first_year, last_year + 1), 0.0)
    for ticker in tickers:
        for start, end in table.get(ticker, ()):
            for year in totals:
                low = max(date.fromisoformat(start[:10]), date(year, 1, 1))
                high = min(date.fromisoformat(min(end, "9999-12-31")[:10]), date(year + 1, 1, 1))
                if high > low:
                    totals[year] += (high - low).days
    return totals


def coverage_by_year(table: Mapping[str, list[tuple[str, str]]], available: set[str], first_year: int = 2004, last_year: int = 2026) -> dict[str, float]:
    """Share of member-days per year on names with no usable bars. Anything left out of `available`, for whatever reason, counts."""
    everyone = member_days_by_year(table, table, first_year, last_year)
    have = member_days_by_year(table, [ticker for ticker in table if ticker in available], first_year, last_year)
    return {str(year): (1.0 - have[year] / everyone[year]) if everyone[year] else 0.0 for year in everyone}


def write_coverage(path: Path, table: Mapping[str, list[tuple[str, str]]], available: set[str], excluded: Mapping[str, str]) -> dict:
    """`ml/evaluation/v660/wide_coverage.json`: never holds a price or a return."""
    report = {
        "missing_share_by_year": coverage_by_year(table, available),
        "available": len(available),
        "members_since_2004": len(tickers_touching(table, "2004-01-01", "2026-11-02")),
        "excluded": dict(sorted(excluded.items())),
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    return report
