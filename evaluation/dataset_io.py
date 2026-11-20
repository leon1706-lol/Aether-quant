"""Read a few columns of the 800 MB training dataset without holding all of it (V6.6.9, #389).

`pd.read_csv` of the whole file needs about 3 GB; the dev PC has 3.9. A chunked read of the columns a step needs, as float32
where they are numeric, and with an optional date floor applied chunk by chunk, fits in a few hundred MB."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

TEXT_COLUMNS = frozenset({"date", "ticker", "split", "timestamp", "security_type", "market", "asset_class"})


def read_dataset_columns(path: Path | str, columns: Sequence[str], *, start: str | None = None, chunk_rows: int = 50_000) -> pd.DataFrame:
    """`columns` of the CSV at `path`, rows dated `start` or later (the `date` column is read for the floor even when not asked for).
    Numeric columns come back as float32; `date` as an ISO string. A requested column the file lacks is an error, never a silent gap."""
    wanted = list(dict.fromkeys(columns))
    header = pd.read_csv(path, nrows=0).columns
    missing = [name for name in wanted if name not in header]
    if missing:
        raise KeyError(f"columns not in {Path(path).name}: {missing[:5]}")
    read = list(dict.fromkeys([*wanted, "date"])) if start is not None else wanted
    pieces = []
    for chunk in pd.read_csv(path, usecols=read, chunksize=max(1, int(chunk_rows))):
        if "date" in chunk:
            chunk["date"] = chunk["date"].astype(str).str[:10]
        if start is not None:
            chunk = chunk[chunk["date"] >= str(start)[:10]]
        numeric = [name for name in chunk.columns if name not in TEXT_COLUMNS and pd.api.types.is_numeric_dtype(chunk[name])]
        chunk = chunk.astype(dict.fromkeys(numeric, np.float32))
        pieces.append(chunk[wanted])
    return pd.concat(pieces, ignore_index=True)


def read_dataset_rows(path: Path | str, *, split: str | Sequence[str] | None = None, chunk_rows: int = 50_000) -> pd.DataFrame:
    """Every column of the rows whose `split` is `split` (or one of several; all rows when None), read in chunks so the rows of the
    other splits are never held. The values are exactly those of a plain `pd.read_csv`: a rank-book evaluation reads closes and
    returns, which stay float64."""
    wanted = None if split is None else ({split} if isinstance(split, str) else set(split))
    pieces = []
    for chunk in pd.read_csv(path, chunksize=max(1, int(chunk_rows))):
        pieces.append(chunk if wanted is None else chunk[chunk["split"].isin(wanted)])
    return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()
