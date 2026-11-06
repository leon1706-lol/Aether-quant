"""Insider trades from SEC's Form 3/4/5 data sets (V6.6.0, free; SEC needs a contact in the client name, see `edgar_facts`).

A quarter's zip holds every filing's transactions. Only open-market purchases (`P`) and sales (`S`) say anything about an insider's
view: grants, exercises and tax withholding don't. Cohen, Malloy and Pomorski (2012) split those trades: an insider who traded in the
same calendar month of each of the prior three years is routine, and the rest are opportunistic, which is where the information was.

Keyed by the filing date, when the market could first know, never the transaction date.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable, Iterable

import numpy as np
import pandas as pd

ZIP_URL = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{year}q{quarter}_form345.zip"
TRADE_COLUMNS = ["ticker", "owner", "filed", "traded", "code", "value"]
MARKET_CODES = ("P", "S")


def quarters(start_year: int, end_year: int, end_quarter: int) -> list[tuple[int, int]]:
    return [(year, quarter) for year in range(start_year, end_year + 1) for quarter in (1, 2, 3, 4) if (year, quarter) <= (end_year, end_quarter)]


def _member(archive: zipfile.ZipFile, name: str) -> str | None:
    return next((item for item in archive.namelist() if item.upper().endswith(name)), None)


def parse_quarter(payload: bytes, wanted: set[str] | None = None) -> pd.DataFrame:
    """`TRADE_COLUMNS` rows of one quarter's zip: non-derivative open-market trades with a price."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        submissions = pd.read_csv(
            archive.open(_member(archive, "SUBMISSION.TSV")), sep="\t", dtype=str,
            usecols=["ACCESSION_NUMBER", "FILING_DATE", "ISSUERTRADINGSYMBOL"],
        )
        owners = pd.read_csv(archive.open(_member(archive, "REPORTINGOWNER.TSV")), sep="\t", dtype=str, usecols=["ACCESSION_NUMBER", "RPTOWNERCIK"])
        trades = pd.read_csv(
            archive.open(_member(archive, "NONDERIV_TRANS.TSV")), sep="\t", dtype=str,
            usecols=["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES", "TRANS_PRICEPERSHARE"],
        )
    trades = trades[trades["TRANS_CODE"].isin(MARKET_CODES)]
    # A filing can list joint owners; one trade is one trade.
    owners = owners.drop_duplicates("ACCESSION_NUMBER")
    merged = trades.merge(submissions, on="ACCESSION_NUMBER", how="inner").merge(owners, on="ACCESSION_NUMBER", how="left")
    merged["ticker"] = merged["ISSUERTRADINGSYMBOL"].astype(str).str.strip().str.upper()
    if wanted is not None:
        merged = merged[merged["ticker"].isin(wanted)]
    shares = pd.to_numeric(merged["TRANS_SHARES"], errors="coerce")
    price = pd.to_numeric(merged["TRANS_PRICEPERSHARE"], errors="coerce")
    out = pd.DataFrame({
        "ticker": merged["ticker"],
        "owner": merged["RPTOWNERCIK"].astype(str),
        "filed": pd.to_datetime(merged["FILING_DATE"], format="%d-%b-%Y", errors="coerce"),
        "traded": pd.to_datetime(merged["TRANS_DATE"], format="%d-%b-%Y", errors="coerce"),
        "code": merged["TRANS_CODE"],
        "value": shares * price,
    }).dropna(subset=["filed", "traded", "value"])
    out = out[out["value"] > 0.0]
    out["filed"] = out["filed"].dt.strftime("%Y-%m-%d")
    out["traded"] = out["traded"].dt.strftime("%Y-%m-%d")
    return out[TRADE_COLUMNS]


def fetch_trades(
    periods: Iterable[tuple[int, int]], get_bytes: Callable[[str], bytes | None], wanted: set[str] | None = None,
    pause: Callable[[], None] = lambda: None,
) -> pd.DataFrame:
    pieces = []
    for year, quarter in periods:
        payload = get_bytes(ZIP_URL.format(year=year, quarter=quarter))
        if payload:
            pieces.append(parse_quarter(payload, wanted))
        pause()
    return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame(columns=TRADE_COLUMNS)


def opportunistic(trades: pd.DataFrame) -> pd.DataFrame:
    """The trades of insiders not routine at that moment: routine means a trade in this calendar month of each of the three prior
    years, which uses nothing after the trade. An insider with too little history is opportunistic, as in the paper."""
    if trades.empty:
        return trades.copy()
    frame = trades.copy()
    stamp = pd.to_datetime(frame["traded"])
    frame["_year"] = stamp.dt.year
    frame["_month"] = stamp.dt.month
    seen = set(zip(frame["ticker"], frame["owner"], frame["_year"], frame["_month"]))
    routine = [
        all((ticker, owner, year - back, month) in seen for back in (1, 2, 3))
        for ticker, owner, year, month in zip(frame["ticker"], frame["owner"], frame["_year"], frame["_month"])
    ]
    return frame.loc[~np.asarray(routine, dtype=bool), TRADE_COLUMNS]


def insider_net_table(trades: pd.DataFrame, sessions: list[str], columns: list[str], *, window_days: int = 180, lag_sessions: int = 1) -> pd.DataFrame:
    """Session x ticker: open-market buys less sales over the trailing `window_days`, by filing date, a session late: a filing can
    arrive after the close. Nothing in the window is NaN for a covered ticker: no insider trading is a real 0."""
    positions = pd.Index(sessions)
    table = pd.DataFrame(0.0, index=sessions, columns=columns, dtype=float)
    signed = trades.assign(signed=np.where(trades["code"] == "P", trades["value"], -trades["value"]))
    stamps = pd.to_datetime(pd.Index(sessions))
    for ticker, group in signed.groupby("ticker"):
        if ticker not in table.columns:
            continue
        daily = group.groupby("filed")["signed"].sum()
        location = positions.searchsorted(daily.index.to_numpy(), side="left") + lag_sessions
        keep = location < len(sessions)
        flow = pd.Series(0.0, index=stamps, dtype=float)
        np.add.at(flow.values, location[keep], daily.to_numpy()[keep])
        table[ticker] = flow.rolling(f"{int(window_days)}D").sum().to_numpy()
    return table
