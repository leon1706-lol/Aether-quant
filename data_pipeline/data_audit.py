"""Lean daily-data audit and file manifest (V5.8.0).

V5.8.0 rewrites every universe zip from one Yahoo pull to extend the window to 2026. A rewrite that silently drops a
month, writes an unadjusted split or a spinoff gap, or leaves a quote zip stopping years early (BTC's ended 2018-12-24)
would poison the dataset the way #130 (double-adjusted factor files) and #141 (Codespace-only FRED files) did. This module
reads each zip the way Lean does and reports, per ticker:

  * coverage: first/last date, rows, missing weekdays per year (equity/forex) or missing days (crypto, 7-day calendar),
  * suspicious moves: |1-day close return| above a per-class threshold (a split or spinoff the source did not adjust),
  * OHLC sanity (low <= open/close <= high, all > 0) and long flat runs,
  * quote-zip coverage against the trade zip (crypto) and factor-file presence (equity).

`build_data_manifest` / `compare_manifests` give a size + SHA-256 file list so local `data/` and the Codespace copy can
be proven identical file-for-file. Pure stdlib + pandas; reading only.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

# |1-day close return| above which a move is flagged for a manual look (a missed split/spinoff, a bad print)
OUTLIER_RETURN_BY_CLASS = {"equity": 0.25, "bond": 0.12, "crypto": 0.60, "forex": 0.08}
# NYSE has ~9-10 holidays a year; more missing weekdays than this per year is a coverage gap
MAX_MISSING_WEEKDAYS_PER_YEAR = {"equity": 12.0, "bond": 12.0, "forex": 6.0}
FLAT_RUN_FLAG = 5


def read_lean_daily_zip(path: Path, security_type: str) -> pd.DataFrame:
    """date/open/high/low/close/volume from a Lean daily zip. Equity prices are stored x10000; forex quote rows are
    bid OHLC, bid size, ask OHLC, ask size (midpoint returned); crypto trade rows are plain decimals."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if not names:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        text = archive.read(names[0]).decode("utf-8", errors="replace")
    raw = pd.read_csv(io.StringIO(text), header=None)
    dates = pd.to_datetime(raw[0].astype(str).str[:8], format="%Y%m%d")
    if security_type == "forex":
        bid = raw[[1, 2, 3, 4]].to_numpy(float)
        ask = raw[[6, 7, 8, 9]].to_numpy(float) if raw.shape[1] >= 10 else bid
        mid = (bid + ask) / 2.0
        frame = pd.DataFrame({"date": dates, "open": mid[:, 0], "high": mid[:, 1], "low": mid[:, 2], "close": mid[:, 3]})
        frame["volume"] = 0.0
        return frame
    frame = pd.DataFrame(
        {"date": dates, "open": raw[1].astype(float), "high": raw[2].astype(float), "low": raw[3].astype(float),
         "close": raw[4].astype(float), "volume": raw[5].astype(float) if raw.shape[1] > 5 else 0.0}
    )
    if security_type == "equity":
        for column in ("open", "high", "low", "close"):
            frame[column] = frame[column] / 10_000.0
    return frame


def _longest_flat_run(closes: np.ndarray) -> int:
    longest = current = 1 if len(closes) else 0
    for index in range(1, len(closes)):
        current = current + 1 if closes[index] == closes[index - 1] else 1
        longest = max(longest, current)
    return longest


def audit_series(frame: pd.DataFrame, asset_class: str, *, start: str | None = None, end: str | None = None) -> dict:
    """Coverage, outlier, OHLC and flat-run findings for one ticker's frame (read_lean_daily_zip output)."""
    data = frame.sort_values("date").drop_duplicates("date")
    if start:
        data = data[data["date"] >= pd.Timestamp(start)]
    if end:
        data = data[data["date"] <= pd.Timestamp(end)]
    if data.empty:
        return {"rows": 0, "problems": ["no rows in window"]}
    problems: list[str] = []
    first, last = data["date"].iloc[0], data["date"].iloc[-1]
    years = max((last - first).days / 365.25, 1e-9)
    present = set(data["date"].dt.normalize())
    if asset_class == "crypto":
        expected = pd.date_range(first, last, freq="D")
        missing = [day for day in expected if day not in present]
        missing_per_year = len(missing) / years
        if missing:
            problems.append(f"{len(missing)} missing calendar days")
    else:
        expected = pd.bdate_range(first, last)
        missing = [day for day in expected if day not in present]
        missing_per_year = len(missing) / years
        limit = MAX_MISSING_WEEKDAYS_PER_YEAR.get(asset_class, 12.0)
        if missing_per_year > limit:
            problems.append(f"{missing_per_year:.1f} missing weekdays/year (> {limit})")
    gaps = data["date"].diff().dt.days.dropna()
    largest_gap = int(gaps.max()) if len(gaps) else 0
    closes = data["close"].to_numpy(float)
    returns = closes[1:] / closes[:-1] - 1.0 if len(closes) > 1 else np.array([])
    threshold = OUTLIER_RETURN_BY_CLASS.get(asset_class, 0.25)
    outlier_index = np.nonzero(np.abs(returns) > threshold)[0]
    outliers = [
        {"date": data["date"].iloc[i + 1].date().isoformat(), "return": round(float(returns[i]), 4)} for i in outlier_index
    ]
    if outliers:
        problems.append(f"{len(outliers)} |1d return| > {threshold:.0%}")
    ohlc = data[["open", "high", "low", "close"]].to_numpy(float)
    nonpositive = int((ohlc <= 0).any(axis=1).sum())
    tolerance = 1e-9
    inconsistent = int(
        ((ohlc[:, 2] > ohlc[:, [0, 3]].min(axis=1) + tolerance) | (ohlc[:, 1] + tolerance < ohlc[:, [0, 3]].max(axis=1))).sum()
    )
    if nonpositive:
        problems.append(f"{nonpositive} rows with a non-positive price")
    if inconsistent:
        problems.append(f"{inconsistent} rows with low/high outside open/close")
    flat_run = _longest_flat_run(closes)
    if flat_run >= FLAT_RUN_FLAG and asset_class != "forex":
        problems.append(f"flat close run of {flat_run} bars")
    return {
        "rows": int(len(data)),
        "first": first.date().isoformat(),
        "last": last.date().isoformat(),
        "missing_per_year": round(float(missing_per_year), 2),
        "largest_gap_days": largest_gap,
        "outliers": outliers,
        "nonpositive_rows": nonpositive,
        "ohlc_inconsistent_rows": inconsistent,
        "longest_flat_run": int(flat_run),
        "problems": problems,
    }


def asset_zip_paths(asset: dict, data_root: Path) -> dict[str, Path]:
    """{'trade': path[, 'quote': path]} for a config universe asset (its `data_path` is relative to the repo root and
    starts with 'data/')."""
    relative = Path(asset["data_path"])
    trade = Path(data_root) / Path(*relative.parts[1:])
    paths = {"trade": trade}
    if asset.get("security_type") == "crypto" and trade.name.endswith("_trade.zip"):
        paths["quote"] = trade.with_name(trade.name.replace("_trade.zip", "_quote.zip"))
    return paths


def audit_universe(config: dict, data_root: Path, *, start: str | None = None, end: str | None = None) -> dict:
    """Audits every `phase1.universe.assets` entry under `data_root`. `end` defaults to none (whole file)."""
    data_root = Path(data_root)
    factor_dir = data_root / "equity" / "usa" / "factor_files"
    report: dict = {"data_root": str(data_root), "window": {"start": start, "end": end}, "assets": {}}
    flagged = []
    for asset in config["phase1"]["universe"]["assets"]:
        ticker = str(asset["ticker"])
        security_type = str(asset.get("security_type", "equity"))
        asset_class = str(asset.get("asset_class") or security_type)
        paths = asset_zip_paths(asset, data_root)
        entry: dict = {"security_type": security_type, "asset_class": asset_class}
        if not paths["trade"].exists():
            entry["problems"] = [f"missing zip {paths['trade']}"]
        else:
            frame = read_lean_daily_zip(paths["trade"], security_type)
            entry.update(audit_series(frame, asset_class, start=start, end=end))
            if "quote" in paths:
                if paths["quote"].exists():
                    quote = read_lean_daily_zip(paths["quote"], "forex")
                    quote_last = quote["date"].max().date().isoformat() if len(quote) else None
                    entry["quote_last"] = quote_last
                    if entry.get("last") and quote_last and quote_last < entry["last"]:
                        entry["problems"].append(f"quote zip ends {quote_last} before trade zip {entry['last']}")
                else:
                    entry["problems"].append("missing quote zip")
            if security_type == "equity":
                entry["factor_file"] = (factor_dir / f"{ticker.lower()}.csv").exists()
        if entry.get("problems"):
            flagged.append(ticker)
        report["assets"][ticker] = entry
    report["num_assets"] = len(report["assets"])
    report["flagged"] = flagged
    return report


def build_data_manifest(root: Path, *, subdirs: tuple[str, ...] = ("crypto", "equity", "forex", "reference")) -> dict:
    """{relative posix path: {"size", "sha256"}} for every file under root/<subdir>."""
    root = Path(root)
    manifest: dict[str, dict] = {}
    for subdir in subdirs:
        base = root / subdir
        if not base.exists():
            continue
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(block)
            manifest[path.relative_to(root).as_posix()] = {"size": path.stat().st_size, "sha256": digest.hexdigest()}
    return manifest


def compare_manifests(left: dict, right: dict) -> dict:
    """Files only on one side and files whose hash differs."""
    only_left = sorted(set(left) - set(right))
    only_right = sorted(set(right) - set(left))
    differing = sorted(path for path in set(left) & set(right) if left[path]["sha256"] != right[path]["sha256"])
    return {
        "only_left": only_left,
        "only_right": only_right,
        "differing": differing,
        "identical": not (only_left or only_right or differing),
    }
