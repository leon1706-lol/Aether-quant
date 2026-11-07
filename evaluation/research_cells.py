"""Which data a V6.6.0 research step may read: a split by name and by time, enforced in code.

Every earlier phase read the project's own 104 assets over 2013-2026, so time alone holds nothing unread. Names outside that universe
have never been scored by any rule, so half of them stay out of selection altogether:

    TA  side A, 2004-2018   ML training rows only
    S   side A, 2011-2018   selection; SV (short volume, from 2018-08) and CS (crypto) are its siblings
    V1  side A, 2019-2026   later time on the read names
    V2  side B, 2011-2018   never-read names, same time
    V3  side B, 2019-2026   never-read names, later time: the cleanest cell
    P   both,   2004-2010   before XBRL fundamentals, price families only. ML training read side A here: disclosed
    CV  crypto holdout      side B coins on all dates, side A coins from 2023-01

`open_cell` is the only way in, and it refuses any cell outside `FREE_CELLS` unless given the digest recorded at the freeze. A panel
holds only its cell's names, so a rank, a label, a covariance or a history count can't see the other side.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from data_pipeline.sp500_membership import canonical_issuer

SALT = "aq-v660-names"
BENCHMARK_TICKERS = ("SPY", "AGG")
SWEEP_TICKER = "BIL"
WARMUP_SESSIONS = 300
STALE_ROWS = 5


@dataclass(frozen=True)
class Cell:
    name: str
    side: str
    start: str
    end: str
    split: str | None = None
    universe: str = "equity"


CELLS = {
    "TA": Cell("TA", "A", "2004-01-01", "2018-12-31"),
    "S": Cell("S", "A", "2011-01-01", "2018-12-31", "2015-01-01"),
    "SV": Cell("SV", "A", "2018-08-01", "2022-12-31", "2020-10-01"),
    "CS": Cell("CS", "A", "2018-01-01", "2022-12-31", "2020-07-01", "crypto"),
    "V1": Cell("V1", "A", "2019-01-01", "2026-11-02"),
    "V2": Cell("V2", "B", "2011-01-01", "2018-12-31"),
    "V3": Cell("V3", "B", "2019-01-01", "2026-11-02"),
    "CV": Cell("CV", "AB", "2018-01-01", "2026-11-02", None, "crypto"),
    "P": Cell("P", "AB", "2004-01-01", "2010-12-31"),
}
FREE_CELLS = frozenset({"TA", "S", "SV", "CS"})


def name_side(ticker: str, project_issuers: Iterable[str] = ()) -> str:
    """A or B, fixed by a hash of the issuer: share classes and renames share a side, and it can't be tuned. A name any earlier phase
    has read is always A."""
    issuer = canonical_issuer(str(ticker))
    if issuer in {canonical_issuer(str(name)) for name in project_issuers}:
        return "A"
    return "A" if hashlib.sha256((SALT + issuer).encode("utf-8")).digest()[0] % 2 == 0 else "B"


def coin_side(ticker: str, project_coins: Iterable[str] = ()) -> str:
    """The same split for coins, by base asset: BTCUSD and BTCUSDT are one coin."""
    base = str(ticker).upper()
    for quote in ("USDT", "USD"):
        if base.endswith(quote):
            base = base[: -len(quote)]
            break
    known = {str(name).upper().removesuffix("USD") for name in project_coins}
    if base in known:
        return "A"
    return "A" if hashlib.sha256((SALT + "coin" + base).encode("utf-8")).digest()[0] % 2 == 0 else "B"


def names_in_cell(cell: Cell, tickers: Iterable[str], project: Iterable[str]) -> list[str]:
    project = list(project)
    side_of = coin_side if cell.universe == "crypto" else name_side
    return sorted(ticker for ticker in tickers if cell.side == "AB" or side_of(ticker, project) == cell.side)


def freeze_digest_of(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assert_cell_open(cell_name: str, freeze_path: Path | None, freeze_digest: str | None) -> Cell:
    """The gate itself. A later cell needs the digest of the freeze file, and that file must be the one on disk."""
    if cell_name not in CELLS:
        raise ValueError(f"unknown cell {cell_name!r}; expected one of {sorted(CELLS)}")
    if cell_name in FREE_CELLS:
        return CELLS[cell_name]
    if not freeze_digest:
        raise PermissionError(f"cell {cell_name} is held out: it opens only with the digest of the recorded freeze")
    if freeze_path is None or not Path(freeze_path).exists():
        raise PermissionError(f"cell {cell_name}: no recorded freeze")
    actual = freeze_digest_of(Path(freeze_path))
    if actual != freeze_digest:
        raise PermissionError(f"cell {cell_name}: digest {freeze_digest} is not the recorded freeze {actual}")
    return CELLS[cell_name]


def window_rows(index: Iterable[str], cell: Cell, *, warmup: int = WARMUP_SESSIONS) -> list[str]:
    """The cell's sessions plus the `warmup` before them, which give a signal its history. A warm-up row can never hold a position:
    weights start at `cell.start`. Nothing after `cell.end` exists in the panel at all."""
    dates = sorted(str(day) for day in index if str(day) <= cell.end)
    first = next((position for position, day in enumerate(dates) if day >= cell.start), len(dates))
    return dates[max(0, first - warmup):]


def blank_stale(known: pd.DataFrame, closes: pd.DataFrame, *, rows: int = STALE_ROWS) -> pd.DataFrame:
    """`known_closes` carries the last price forward, so a name whose bars stopped would keep a signal forever. A cell with no bar over
    the last `rows` rows goes NaN. Looks backward only, and it never reads why the bars stopped."""
    recent = closes.reindex(index=known.index, columns=known.columns).notna().rolling(rows, min_periods=1).sum() > 0
    return known.where(recent)


def membership_mask(table: Mapping[str, list[tuple[str, str]]], sessions: list[str], columns: list[str]) -> pd.DataFrame:
    """Session x ticker, True while a member. Names outside the membership table are False."""
    mask = pd.DataFrame(False, index=sessions, columns=columns)
    for ticker in columns:
        for start, end in table.get(ticker, ()):
            mask[ticker] |= (mask.index >= start) & (mask.index < end)
    return mask


def record_holdout_read(path: Path, *, candidate: str, cells: tuple[str, ...], digest: str, created_at: str) -> None:
    """The once-only ledger of holdout reads. `write_freeze` only refuses its own path, so a second freeze file would otherwise reopen a cell.
    Written before the read: a crash after it still counts as spent."""
    path = Path(path)
    held = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
    spent = {cell for entry in held for cell in entry.get("cells", ())}
    again = sorted(spent & set(cells))
    if again:
        raise PermissionError(f"cells {again} have already been read: a holdout is read once")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({"candidate": candidate, "cells": list(cells), "digest": digest, "created_at": created_at}, sort_keys=True) + "\n")


def write_freeze(path: Path, payload: Mapping) -> str:
    """Writes the freeze file once and returns its digest. Refuses to overwrite: a second freeze would be a second look."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"{path} exists: a candidate is frozen once")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8", newline="\n")
    return freeze_digest_of(path)
