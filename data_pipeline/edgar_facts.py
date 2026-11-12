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
from typing import Any

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


def quarterly_first_filings(facts: dict[str, Any]) -> list[dict]:
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


# Annual figures of the wide universe (V6.6.0). The first tag with data wins, per fiscal year: filers change tags over time.
FUNDAMENTAL_TAGS = {
    "assets": (("us-gaap", "Assets"),),
    "equity": (("us-gaap", "StockholdersEquity"), ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")),
    "gross_profit": (("us-gaap", "GrossProfit"),),
    "revenue": (("us-gaap", "Revenues"), ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"), ("us-gaap", "SalesRevenueNet")),
    "cost_of_revenue": (("us-gaap", "CostOfRevenue"), ("us-gaap", "CostOfGoodsAndServicesSold"), ("us-gaap", "CostOfGoodsSold")),
    "net_income": (("us-gaap", "NetIncomeLoss"),),
    "operating_cash_flow": (("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),),
    "long_term_debt": (("us-gaap", "LongTermDebt"), ("us-gaap", "LongTermDebtNoncurrent")),
    # `dei`, not `us-gaap`: the cover page's count, which `quarterly_first_filings` above never reads.
    "shares_outstanding": (("dei", "EntityCommonStockSharesOutstanding"),),
}
ANNUAL_FORMS = ("10-K", "10-K/A", "20-F", "40-F", "10-KT")
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FUNDAMENTALS_COLUMNS = ["ticker", "field", "period_end", "filed", "form", "value"]
WIDE_USER_AGENT_VERSION = "6.6"


def first_filings_annual(facts: dict[str, Any], tag: str, *, taxonomy: str = "us-gaap") -> list[dict]:
    """{period_end, filed, form, value} per fiscal year, first filing only, from annual forms: what was public, not what a later
    restatement says. A figure may appear in many later filings as a comparative; only the earliest counts."""
    concept = ((facts or {}).get("facts") or {}).get(taxonomy, {}).get(tag) or {}
    first: dict[str, dict] = {}
    for entries in (concept.get("units") or {}).values():
        for entry in entries:
            end, filed, value, form = entry.get("end"), entry.get("filed"), entry.get("val"), entry.get("form")
            if not end or not filed or value is None or form not in ANNUAL_FORMS:
                continue
            start = entry.get("start")
            if start is not None:
                days = (date.fromisoformat(end) - date.fromisoformat(start)).days
                if not YEAR_MIN_DAYS <= days <= YEAR_MAX_DAYS:
                    continue  # a quarter or a part-year comparative inside a 10-K
            if end not in first or filed < first[end]["filed"]:
                first[end] = {"period_end": end, "filed": filed, "form": form, "value": float(value)}
    return sorted(first.values(), key=lambda row: row["period_end"])


def fundamentals_rows(facts: dict[str, Any]) -> list[dict]:
    """Every field's annual first filings. For a field with several tags, an earlier tag wins a fiscal year; a later one only fills
    years it doesn't have."""
    rows: list[dict] = []
    for field, tags in FUNDAMENTAL_TAGS.items():
        by_period: dict[str, dict] = {}
        for taxonomy, tag in tags:
            for row in first_filings_annual(facts, tag, taxonomy=taxonomy):
                by_period.setdefault(row["period_end"], row)
        rows.extend({"field": field, **row} for _, row in sorted(by_period.items()))
    return rows


# V6.6.1: annual fields for net operating assets and capital spending, and the quarterly figures behind trailing-twelve-month accruals.
EXTENDED_ANNUAL_TAGS = {
    "cash": (("us-gaap", "CashAndCashEquivalentsAtCarryingValue"), ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents")),
    "short_term_debt": (("us-gaap", "DebtCurrent"), ("us-gaap", "LongTermDebtCurrent"), ("us-gaap", "ShortTermBorrowings")),
    "capex": (("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"), ("us-gaap", "PaymentsToAcquireProductiveAssets")),
    "rd_expense": (("us-gaap", "ResearchAndDevelopmentExpense"),),
}
TTM_TAGS = {"ttm_net_income": ("NetIncomeLoss",), "ttm_operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",)}
QUARTERLY_FORMS = ("10-Q", "10-Q/A", *ANNUAL_FORMS)
COMPARATIVE_TOLERANCE_DAYS = 7


def _first_filed_durations(facts: dict[str, Any], tag: str, *, taxonomy: str = "us-gaap") -> dict[tuple[str, str], dict]:
    """{(start, end): first filing} of a flow figure, across annual and quarterly forms."""
    concept = ((facts or {}).get("facts") or {}).get(taxonomy, {}).get(tag) or {}
    first: dict[tuple[str, str], dict] = {}
    for entries in (concept.get("units") or {}).values():
        for entry in entries:
            start, end, filed, value, form = entry.get("start"), entry.get("end"), entry.get("filed"), entry.get("val"), entry.get("form")
            if not start or not end or not filed or value is None or form not in QUARTERLY_FORMS:
                continue
            key = (start, end)
            if key not in first or filed < first[key]["filed"]:
                first[key] = {"filed": filed, "form": form, "value": float(value)}
    return first


def _days_between(first: str, second: str) -> int:
    return (date.fromisoformat(second) - date.fromisoformat(first)).days


def _ttm_rows(durations: dict[tuple[str, str], dict]) -> list[dict]:
    """A trailing twelve months per period end: a full year as filed, else last year + this year to date - last year to date. A filing's
    cash-flow figures are year to date, so standalone quarters can't simply be summed. Usable from the latest filing among its parts."""
    annual = {end: row for (start, end), row in durations.items() if YEAR_MIN_DAYS <= _days_between(start, end) <= YEAR_MAX_DAYS}
    best: dict[str, dict] = {}

    def offer(end: str, row: dict[str, Any]) -> None:
        if end not in best or row["filed"] < best[end]["filed"]:
            best[end] = {"period_end": end, **row}

    for end, row in annual.items():
        offer(end, row)
    ytd_spans = [(start, end, row) for (start, end), row in durations.items() if _days_between(start, end) < YEAR_MIN_DAYS]
    for start, end, row in ytd_spans:
        # A year-to-date figure starts the day after a fiscal year ended; a standalone second quarter doesn't, so it finds no year here.
        year = next((annual[candidate] for candidate in annual if abs(_days_between(candidate, start) - 1) <= COMPARATIVE_TOLERANCE_DAYS), None)
        if year is None:
            continue
        comparative = next(
            (
                other for other_start, other_end, other in ytd_spans
                if abs(_days_between(other_start, start) - 365) <= COMPARATIVE_TOLERANCE_DAYS and abs(_days_between(other_end, end) - 365) <= COMPARATIVE_TOLERANCE_DAYS
            ),
            None,
        )
        if comparative is None:
            continue
        offer(end, {
            "filed": max(row["filed"], year["filed"], comparative["filed"]), "form": row["form"],
            "value": year["value"] + row["value"] - comparative["value"],
        })
    return sorted(best.values(), key=lambda item: item["period_end"])


def _first_filed_instants(facts: dict[str, Any], tag: str, *, taxonomy: str = "us-gaap") -> list[dict]:
    """A balance-sheet figure per period end, first filing only, from annual and quarterly forms."""
    concept = ((facts or {}).get("facts") or {}).get(taxonomy, {}).get(tag) or {}
    first: dict[str, dict] = {}
    for entries in (concept.get("units") or {}).values():
        for entry in entries:
            end, filed, value, form = entry.get("end"), entry.get("filed"), entry.get("val"), entry.get("form")
            if not end or not filed or value is None or form not in QUARTERLY_FORMS:
                continue
            if end not in first or filed < first[end]["filed"]:
                first[end] = {"period_end": end, "filed": filed, "form": form, "value": float(value)}
    return sorted(first.values(), key=lambda row: row["period_end"])


def quarterly_ttm_rows(facts: dict[str, Any]) -> list[dict]:
    """`ttm_net_income`, `ttm_operating_cash_flow` and `assets_q`, in FUNDAMENTALS_COLUMNS' shape without the ticker."""
    rows: list[dict] = []
    for field, tags in TTM_TAGS.items():
        by_period: dict[str, dict] = {}
        for tag in tags:
            for row in _ttm_rows(_first_filed_durations(facts, tag)):
                by_period.setdefault(row["period_end"], row)
        rows.extend({"field": field, **row} for _, row in sorted(by_period.items()))
    rows.extend({"field": "assets_q", **row} for row in _first_filed_instants(facts, "Assets"))
    return rows


def extended_rows(facts: dict[str, Any]) -> list[dict]:
    """Every V6.6.1 field. For a field with several tags, an earlier tag wins a fiscal year, as in `fundamentals_rows`."""
    rows = list(quarterly_ttm_rows(facts))
    for field, tags in EXTENDED_ANNUAL_TAGS.items():
        by_period: dict[str, dict] = {}
        for taxonomy, tag in tags:
            for row in first_filings_annual(facts, tag, taxonomy=taxonomy):
                by_period.setdefault(row["period_end"], row)
        rows.extend({"field": field, **row} for _, row in sorted(by_period.items()))
    return rows


def fetch_extended(
    tickers: Iterable[str], get_json: Callable[[str], dict] | None = None, pause_seconds: float = 0.15, cache_dir: Path | None = None,
) -> tuple[list[dict], list[str]]:
    """(rows with a `ticker`, tickers with nothing). Each company's parsed body is dropped once its rows are read, and a run with `cache_dir` resumes."""
    get_json = get_json or _get_json
    directory = get_json(TICKERS_URL)
    cik_by_ticker = {str(item["ticker"]).upper().replace("-", "."): int(item["cik_str"]) for item in directory.values()}
    rows: list[dict] = []
    missing: list[str] = []
    for ticker in tickers:
        cached = Path(cache_dir) / f"{ticker.lower()}.json" if cache_dir else None
        if cached is not None and cached.exists():
            saved = json.loads(cached.read_text(encoding="utf-8"))
        else:
            cik = cik_by_ticker.get(str(ticker).upper())
            if cik is None:
                missing.append(ticker)
                continue
            try:
                saved = extended_rows(get_json(FACTS_URL.format(cik=cik)))
            except Exception as error:  # one failed company must not lose the others
                print(f"{ticker}: {type(error).__name__}", flush=True)
                missing.append(ticker)
                continue
            if cached is not None:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps(saved, separators=(",", ":")), encoding="utf-8", newline="\n")
            if pause_seconds:
                _time.sleep(pause_seconds)
        if not saved:
            missing.append(ticker)
        rows.extend({"ticker": ticker, **row} for row in saved)
    return rows, missing


def sector_for_sic(sic: int | str | None) -> str:
    """A sector label from a SEC SIC code, in the GICS sector names. Coarse, and today's code rather than the code at each date: it
    only sets which names are ranked together. A company with no code is `unknown`, which is never traded."""
    try:
        code = int(sic)
    except (TypeError, ValueError):
        return "unknown"
    if code <= 0:
        return "unknown"
    if code in (1311, 1381, 1382, 1389, 2911, 2990, 2992, 5171, 5172) or 2900 <= code <= 2999 or code in (4610, 4612, 4613):
        return "energy"
    if 2830 <= code <= 2836 or 3841 <= code <= 3851 or 8000 <= code <= 8099 or code == 5912 or code == 5122:
        return "health_care"
    if 3570 <= code <= 3579 or 3660 <= code <= 3679 or 3810 <= code <= 3829 or 7370 <= code <= 7379:
        return "information_technology"
    if 4800 <= code <= 4899 or 2700 <= code <= 2799 or code in (7812, 7819, 7822, 7829, 7830, 7841):
        return "communication_services"
    if 4900 <= code <= 4999:
        return "utilities"
    if code == 6798 or 6500 <= code <= 6553:
        return "real_estate"
    if 6000 <= code <= 6799:
        return "financials"
    if 2000 <= code <= 2199 or 5400 <= code <= 5499 or code in (5140, 5141, 5149, 5180, 5181, 5182, 5194) or 2840 <= code <= 2844:
        return "consumer_staples"
    if 2200 <= code <= 2399 or 2500 <= code <= 2599 or 3630 <= code <= 3652 or 3711 <= code <= 3716 or 3900 <= code <= 3999 or 5200 <= code <= 5399 or 5500 <= code <= 5999 or 7000 <= code <= 7299 or 7800 <= code <= 7999 or code == 3140:
        return "consumer_discretionary"
    if 1000 <= code <= 1499 or 2400 <= code <= 2499 or 2600 <= code <= 2699 or 2800 <= code <= 2829 or 2845 <= code <= 2899 or 3000 <= code <= 3299 or 3300 <= code <= 3399:
        return "materials"
    return "industrials"


def fetch_fundamentals(
    tickers: Iterable[str], get_json: Callable[[str], dict] | None = None, pause_seconds: float = 0.15, cache_dir: Path | None = None,
) -> tuple[list[dict], dict[str, str], list[str]]:
    """(rows with a `ticker`, {ticker: sector}, tickers SEC has no data for). SEC's ticker list holds current tickers only, so a
    name that no longer trades has none: such a name reads as missing, and R-SURV1 counts it. A run with `cache_dir` resumes."""
    get_json = get_json or _get_json
    directory = get_json(TICKERS_URL)
    cik_by_ticker = {str(item["ticker"]).upper().replace("-", "."): int(item["cik_str"]) for item in directory.values()}
    rows: list[dict] = []
    sectors: dict[str, str] = {}
    missing: list[str] = []
    for ticker in tickers:
        cached = Path(cache_dir) / f"{ticker.lower()}.json" if cache_dir else None
        if cached is not None and cached.exists():
            saved = json.loads(cached.read_text(encoding="utf-8"))
        else:
            cik = cik_by_ticker.get(str(ticker).upper())
            if cik is None:
                missing.append(ticker)
                continue
            try:
                facts = get_json(FACTS_URL.format(cik=cik))
                saved = {
                    "rows": fundamentals_rows(facts),
                    "eps": quarterly_first_filings(facts),
                    "sector": sector_for_sic(get_json(SUBMISSIONS_URL.format(cik=cik)).get("sic")),
                }
            except Exception as error:  # one failed company must not lose the others
                print(f"{ticker}: {type(error).__name__}")
                missing.append(ticker)
                continue
            if cached is not None:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps(saved, separators=(",", ":")), encoding="utf-8", newline="\n")
            if pause_seconds:
                _time.sleep(pause_seconds)
        sectors[ticker] = saved["sector"]
        if not saved["rows"]:
            missing.append(ticker)
        rows.extend({"ticker": ticker, **row} for row in saved["rows"])
    return rows, sectors, missing


def collect_cached_eps(tickers: Iterable[str], cache_dir: Path) -> list[dict]:
    """The quarterly EPS rows `fetch_fundamentals` saved, in `read_eps`'s shape: the same download serves both."""
    rows: list[dict] = []
    for ticker in tickers:
        cached = Path(cache_dir) / f"{ticker.lower()}.json"
        if cached.exists():
            rows.extend({"ticker": ticker, **row} for row in json.loads(cached.read_text(encoding="utf-8")).get("eps", []))
    return rows


def write_fundamentals(rows: list[dict], path: Path) -> None:
    """Write fundamentals rows as a gzipped CSV in the canonical column order, creating the folder."""
    frame = pd.DataFrame(rows, columns=FUNDAMENTALS_COLUMNS)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n", compression="gzip")


def read_fundamentals(path: Path) -> pd.DataFrame:
    """Read a cached EDGAR fundamentals table, with its keys and dates as strings."""
    return pd.read_csv(path, dtype={"ticker": str, "field": str, "period_end": str, "filed": str, "form": str, "value": float})


def fundamentals_table(rows: pd.DataFrame, sessions: list[str], columns: list[str], field: str, *, lag_sessions: int = 1) -> pd.DataFrame:
    """Session x ticker, each cell the latest fiscal year's value filed by then. A filing dated D is usable a session later: it can
    arrive after the close. Nothing filed later shows, whatever fiscal year it covers."""
    table = pd.DataFrame(np.nan, index=sessions, columns=columns, dtype=float)
    subset = rows[rows["field"] == field]
    positions = pd.Index(sessions)
    for ticker, group in subset.groupby("ticker"):
        if ticker not in table.columns:
            continue
        ordered = group.sort_values(["filed", "period_end"])
        # a late filing of an older year must not replace a newer year already public
        ordered = ordered[ordered["period_end"] >= ordered["period_end"].cummax()]
        location = positions.searchsorted(ordered["filed"].to_numpy(), side="left") + lag_sessions
        keep = location < len(sessions)
        series = pd.Series(np.nan, index=sessions, dtype=float)
        series.iloc[location[keep]] = ordered["value"].to_numpy()[keep]
        table[ticker] = series.ffill()
    return table


def split_factor_after(splits: pd.DataFrame, ticker: str, filed: str) -> float:
    """Product of the ticker's split ratios after `filed`, up to today: what turns a share count as filed into Yahoo's units."""
    if splits is None or splits.empty:
        return 1.0
    subset = splits[(splits["ticker"] == ticker) & (splits["date"] > filed)]
    return float(subset["ratio"].prod()) if len(subset) else 1.0


def market_cap_table(raw_closes: pd.DataFrame, rows: pd.DataFrame, splits: pd.DataFrame, *, lag_sessions: int = 1) -> pd.DataFrame:
    """Close x shares outstanding, as of each session. `raw_closes` are Yahoo's split-adjusted closes without dividends, so a count
    as filed is restated by the splits after its filing date to match: the product can't depend on any later split or dividend. An
    adjusted close would embed later dividends, and valuation ratios built on it would read the future."""
    shares = rows[rows["field"] == "shares_outstanding"].copy()
    if not shares.empty:
        factors = {
            (ticker, filed): split_factor_after(splits, ticker, filed)
            for ticker, filed in shares[["ticker", "filed"]].drop_duplicates().itertuples(index=False)
        }
        shares["value"] = [value * factors[(ticker, filed)] for ticker, filed, value in shares[["ticker", "filed", "value"]].itertuples(index=False)]
    held = fundamentals_table(shares, list(raw_closes.index), list(raw_closes.columns), "shares_outstanding", lag_sessions=lag_sessions)
    return raw_closes * held


def user_agent() -> str:
    """SEC refuses a client with no contact. The address comes from the environment so that it never enters the repository."""
    contact = os.environ.get(CONTACT_ENV, "").strip()
    return f"AetherQuantResearch/6.5 {contact}" if contact else USER_AGENT


def _get_json(url: str) -> dict[str, Any]:
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
    """Read the cached EDGAR earnings-per-share table, with its date columns as strings."""
    return pd.read_csv(path, dtype={"ticker": str, "period_start": str, "period_end": str, "filed": str})


def fetch_splits(tickers: Iterable[str]) -> list[dict]:
    """{ticker, date, ratio} from Yahoo. A ticker that fails stops the run: a silently missing split reads as a large miss."""
    import yfinance

    rows: list[dict] = []
    for ticker in tickers:
        splits = yfinance.Ticker(TICKER_ALIASES.get(ticker, ticker)).splits
        rows.extend({"ticker": ticker, "date": day.strftime("%Y-%m-%d"), "ratio": float(ratio)} for day, ratio in splits.items() if float(ratio) > 0.0)
    return rows


def fetch_splits_tolerant(tickers: Iterable[str]) -> tuple[list[dict], list[str]]:
    """`fetch_splits` for the wide universe, where one failed name mustn't stop 1,000: (rows, tickers that failed). The caller treats a
    failed name's market cap as unknown rather than guessing it had no split."""
    import yfinance

    rows: list[dict] = []
    failed: list[str] = []
    for ticker in tickers:
        try:
            splits = yfinance.Ticker(str(ticker).replace(".", "-")).splits
        except Exception:
            failed.append(ticker)
            continue
        rows.extend({"ticker": ticker, "date": day.strftime("%Y-%m-%d"), "ratio": float(ratio)} for day, ratio in splits.items() if float(ratio) > 0.0)
    return rows, failed


def write_splits(rows: list[dict], path: Path = SPLITS_OUTPUT) -> None:
    with Path(path).open("w", newline="\n", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker", "date", "ratio"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_splits(path: Path = SPLITS_OUTPUT) -> pd.DataFrame:
    """Read the cached stock-split table, with ticker and date as strings."""
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
