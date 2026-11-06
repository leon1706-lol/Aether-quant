"""Published daily factor returns (V6.6.0): Kenneth French's library and AQR's data sets, free, no account.

A sleeve can earn more than SPY, AGG and BTC explain and still be a known premium anyone can buy. `evaluation.factor_spanning.factor_alpha`
reads these to tell the two apart. Reported beside a result, never blocking. These series lag: one ending before a window is reported as
such, never filled.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable

import numpy as np
import pandas as pd

FRENCH_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
FRENCH_FIVE = FRENCH_URL + "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"
FRENCH_MOMENTUM = FRENCH_URL + "F-F_Momentum_Factor_daily_CSV.zip"
AQR_URL = "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/"
AQR_QMJ = AQR_URL + "Quality-Minus-Junk-Factors-Daily.xlsx"
AQR_BAB = AQR_URL + "Betting-Against-Beta-Equity-Factors-Daily.xlsx"


def parse_french_zip(payload: bytes) -> pd.DataFrame:
    """Decimal returns by YYYY-MM-DD. The file has prose before its header and after its data; only dated rows are kept. The library
    states returns in percent and marks a missing value with -99.99 or -999."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        text = archive.read(archive.namelist()[0]).decode("utf-8", errors="replace")
    header = None
    rows: dict[str, list[float]] = {}
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if header is None:
            if len(parts) >= 2 and parts[0] == "" and all(name for name in parts[1:]):
                header = parts[1:]
            continue
        if len(parts) == len(header) + 1 and parts[0].isdigit() and len(parts[0]) == 8:
            rows[f"{parts[0][:4]}-{parts[0][4:6]}-{parts[0][6:]}"] = [float(value) for value in parts[1:]]
    frame = pd.DataFrame.from_dict(rows, orient="index", columns=header, dtype=float).sort_index()
    return frame.where(frame > -99.0) / 100.0


def parse_aqr_sheet(payload: bytes, *, sheet: str, name: str, column: str = "USA") -> pd.Series:
    """One factor's daily return from an AQR workbook, whose table starts below some prose. Dates are MM/DD/YYYY or real dates."""
    raw = pd.read_excel(io.BytesIO(payload), sheet_name=sheet, header=None, engine="openpyxl")
    header_row = next(index for index, value in enumerate(raw.iloc[:, 0].astype(str)) if value.strip().upper() == "DATE")
    table = raw.iloc[header_row + 1:].copy()
    table.columns = [str(value).strip() for value in raw.iloc[header_row]]
    dates = pd.to_datetime(table["DATE"], errors="coerce", format="mixed")
    values = pd.to_numeric(table[column], errors="coerce").to_numpy(dtype=float)
    series = pd.Series(values, index=dates.dt.strftime("%Y-%m-%d"), name=name)
    return series[series.index.notna()].dropna().sort_index()


def fetch_factors(get_bytes: Callable[[str], bytes]) -> pd.DataFrame:
    """Date x factor: Mkt-RF, SMB, HML, RMW, CMA, RF, Mom, and QMJ and BAB when the workbooks read. AQR's are optional: a failure there
    must not cost the French factors."""
    five = parse_french_zip(get_bytes(FRENCH_FIVE))
    momentum = parse_french_zip(get_bytes(FRENCH_MOMENTUM))
    momentum.columns = [str(column).strip() for column in momentum.columns]
    frame = five.join(momentum.rename(columns={momentum.columns[0]: "Mom"}), how="left")
    for url, sheet, name in ((AQR_QMJ, "QMJ Factors", "QMJ"), (AQR_BAB, "BAB Factors", "BAB")):
        try:
            frame[name] = parse_aqr_sheet(get_bytes(url), sheet=sheet, name=name).reindex(frame.index)
        except Exception as error:
            print(f"{name} left out: {type(error).__name__}: {error}")
    return frame.astype(np.float64)
