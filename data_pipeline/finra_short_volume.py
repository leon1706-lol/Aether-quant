"""FINRA's daily short sale volume files (V6.6.0, free, no account): the consolidated `CNMS` file, Date|Symbol|ShortVolume|... per day.

Short volume isn't short interest: market makers' short sales fill much of it, so its level says little. A name's ratio against its
own past is what the literature (Boehmer, Jones and Zhang) reads. The files begin in 2018-08; earlier dates return 403.
"""

from __future__ import annotations

import io
from collections.abc import Callable, Iterable

import numpy as np
import pandas as pd

FILE_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{day}.txt"


def finra_symbol(ticker: str) -> str:
    """BRK.B here is BRK/B there."""
    return str(ticker).replace(".", "/")


def parse_day(text: str, wanted: dict[str, str] | None = None) -> dict[str, float]:
    """{ticker: short volume / total volume}. A file ends with a record count, and a row with no volume says nothing."""
    frame = pd.read_csv(io.StringIO(text), sep="|", dtype={"Symbol": str}, keep_default_na=False)
    if not {"Symbol", "ShortVolume", "TotalVolume"} <= set(frame.columns):
        return {}
    short = pd.to_numeric(frame["ShortVolume"], errors="coerce")
    total = pd.to_numeric(frame["TotalVolume"], errors="coerce")
    usable = total.gt(0.0) & short.notna()
    out: dict[str, float] = {}
    for symbol, ratio in zip(frame.loc[usable, "Symbol"], (short[usable] / total[usable]).to_numpy()):
        name = wanted.get(symbol) if wanted is not None else symbol
        if name is not None:
            out[name] = float(ratio)
    return out


def fetch_ratios(days: Iterable[str], get_text: Callable[[str], str | None], tickers: Iterable[str]) -> pd.DataFrame:
    """Day x ticker. A day with no file (a holiday, or before the series began) is simply absent. `days` are YYYY-MM-DD."""
    wanted = {finra_symbol(ticker): ticker for ticker in tickers}
    rows: dict[str, dict[str, float]] = {}
    for day in days:
        text = get_text(FILE_URL.format(day=day.replace("-", "")))
        if text:
            values = parse_day(text, wanted)
            if values:
                rows[day] = values
    return pd.DataFrame.from_dict(rows, orient="index").sort_index()


def short_ratio_table(ratios: pd.DataFrame, sessions: list[str], columns: list[str], *, window: int = 20, lag_sessions: int = 1) -> pd.DataFrame:
    """Session x ticker: the mean daily short ratio over `window` sessions, a session late, since the file posts in the evening. A gap
    stays NaN: a file that never arrived isn't a ratio of zero."""
    table = ratios.reindex(index=sessions, columns=columns)
    return table.rolling(window, min_periods=max(5, window // 2)).mean().shift(lag_sessions).astype(np.float64)
