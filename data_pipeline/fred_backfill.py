"""FRED (Federal Reserve Economic Data) historical series backfill.

Powers features/bond_features.py's real yield-curve/credit-spread signals -
distinct from macro_features.py's existing yield_curve_slope_proxy/
credit_spread_proxy, which derive a *proxy* from bond-ETF price momentum.
This module fetches the *actual* Treasury yield/credit-spread series FRED
publishes, no API key required (FRED's public graph CSV endpoint), stdlib
only (urllib.request - no new runtime dependency, unlike yfinance_backfill's
deferred `import yfinance`).

Same two-safety-boundary shape as yfinance_backfill.py:
1. Writing the local cache is gated by --apply (default: dry run only).
2. Never touches config.json - this module's only output is
   data/reference/fred_series/*.csv, read back by
   load_cached_fred_series() at train/backtest time (Lean backtests are
   date-bounded and must never make a live HTTP call mid-run).

Usage:
    python -m data_pipeline.fred_backfill [--series DGS10 DGS2] [--apply]
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
FRED_SERIES_CACHE_DIR = ROOT / "data" / "reference" / "fred_series"

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

DEFAULT_BOND_REFERENCE_SERIES = {
    "treasury_3mo": "DGS3MO",
    "treasury_2yr": "DGS2",
    "treasury_5yr": "DGS5",
    "treasury_10yr": "DGS10",
    "treasury_30yr": "DGS30",
    "credit_spread_baa10y": "BAA10Y",
}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def parse_fred_csv(text: str, series_id: str, start: str, end: str) -> list[dict]:
    """Parses FRED's two-column CSV. The date column header has varied
    across FRED API versions ("DATE" historically, "observation_date" as
    of this module's writing) - read positionally (fieldnames[0]/[1])
    rather than by a hardcoded name so a future FRED header rename doesn't
    silently zero out every row. FRED marks holiday/no-observation rows
    with either an empty string or a literal "." in the value column -
    both are dropped, not coerced to 0.0 (a missing yield observation must
    never look like "yield is exactly 0%"). Clipped to [start, end]
    inclusive. Never raises on malformed rows - skips them, matching
    fetch_yahoo_ohlcv()'s "never abort the whole fetch over one bad row"
    convention."""
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)

    rows: list[dict] = []
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames or len(reader.fieldnames) < 2:
        return rows
    date_column, value_column = reader.fieldnames[0], reader.fieldnames[1]
    for record in reader:
        raw_date = record.get(date_column)
        raw_value = record.get(value_column)
        if not raw_date or raw_value is None or raw_value.strip() in ("", "."):
            continue
        try:
            row_date = date.fromisoformat(raw_date.strip())
            value = float(raw_value.strip())
        except ValueError:
            continue
        if row_date < start_date or row_date > end_date:
            continue
        rows.append({"date": row_date, "value": value})
    return rows


def rows_to_cache_csv(rows: list[dict]) -> str:
    """date.isoformat(),value - one row per line, sorted by date. Mirrors
    yfinance_backfill.rows_to_lean_csv()'s "pure formatting, sorted" shape."""
    ordered = sorted(rows, key=lambda row: row["date"])
    lines = [f"{row['date'].isoformat()},{row['value']}" for row in ordered]
    return "\n".join(lines) + ("\n" if lines else "")


def cache_csv_to_rows(text: str) -> list[dict]:
    """Inverse of rows_to_cache_csv() - reads the local cache format back."""
    rows: list[dict] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        raw_date, raw_value = line.split(",")
        rows.append({"date": date.fromisoformat(raw_date), "value": float(raw_value)})
    return rows


# ---------------------------------------------------------------------------
# The only function that performs network I/O.
# ---------------------------------------------------------------------------


def fetch_fred_series(series_id: str, start: str, end: str) -> list[dict]:
    """GET FRED's public graph CSV endpoint for series_id, clipped to
    [start, end]. Returns [] on any HTTP/parse failure - never raises, so
    one bad/renamed series id never aborts a multi-series backfill run,
    matching fetch_yahoo_ohlcv()'s convention exactly."""
    url = FRED_CSV_URL.format(series_id=series_id)
    try:
        # FRED returns an empty body to urllib's default "Python-urllib/x.y"
        # User-Agent - a browser-like one is required to get real data back.
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (AetherQuant fred_backfill.py)"})
        with urllib.request.urlopen(request, timeout=15) as response:
            text = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("fetch_fred_series(%s): fetch failed — %s", series_id, exc)
        return []

    rows = parse_fred_csv(text, series_id, start, end)
    if not rows:
        logger.warning("fetch_fred_series(%s): no data returned for %s..%s", series_id, start, end)
    return rows


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def bond_reference_series(config: dict) -> dict[str, str]:
    """config["phase1"]["features"]["bond_reference_series"], falling back
    to DEFAULT_BOND_REFERENCE_SERIES so this module works standalone even
    against an older config.json."""
    return {
        **DEFAULT_BOND_REFERENCE_SERIES,
        **config.get("phase1", {}).get("features", {}).get("bond_reference_series", {}),
    }


def fetch_all_bond_reference_series(config: dict, start: str, end: str) -> dict[str, list[dict]]:
    """One independent fetch per series - a single bad/rate-limited FRED
    series never aborts the others, same convention as
    yfinance_backfill.run_backfill()'s per-asset loop."""
    return {
        series_key: fetch_fred_series(series_id, start, end)
        for series_key, series_id in bond_reference_series(config).items()
    }


def write_fred_series_cache(cache_dir: Path, series_key: str, rows: list[dict]) -> None:
    """Writes data/reference/fred_series/{series_key}.csv - a local,
    offline-readable cache (never committed as real market data the way
    Lean zips are; refreshed by re-running this module with --apply)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    output_path = cache_dir / f"{series_key}.csv"
    output_path.write_text(rows_to_cache_csv(rows), encoding="utf-8")


def load_cached_fred_series(cache_dir: Path = FRED_SERIES_CACHE_DIR) -> dict[str, list[dict]]:
    """Reads back whatever *.csv files exist under cache_dir. Returns {} if
    the directory doesn't exist yet (fresh clone, backfill never run) -
    every caller of this (train.py/main.py) must treat a missing/empty
    series as "neutral-default the corresponding bond feature", never a
    crash, same as macro_features.py's own missing-reference convention."""
    if not cache_dir.exists():
        return {}
    series: dict[str, list[dict]] = {}
    for path in sorted(cache_dir.glob("*.csv")):
        try:
            series[path.stem] = cache_csv_to_rows(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            logger.warning("load_cached_fred_series(%s): unreadable cache file — %s", path, exc)
    return series


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
    parser = argparse.ArgumentParser(
        description="Aether Quant FRED historical series backfill - offline/manual only, "
        "no API key required, never run inside Lean or a Docker worker."
    )
    parser.add_argument("--series", nargs="*", default=None, help="Restrict to these series keys (default: all of phase1.features.bond_reference_series)")
    parser.add_argument("--start", default="1990-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--apply", action="store_true", help="Actually write the local cache (default: dry run, report only)")
    parser.add_argument("--config-path", type=Path, default=CONFIG_PATH)
    parser.add_argument("--cache-dir", type=Path, default=FRED_SERIES_CACHE_DIR)
    args = parser.parse_args()

    with args.config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    series_map = bond_reference_series(config)
    if args.series:
        series_map = {key: value for key, value in series_map.items() if key in args.series}

    print(f"{'APPLY' if args.apply else 'DRY RUN'} — fetching {len(series_map)} FRED series ({args.start}..{args.end}):\n")
    for series_key, series_id in series_map.items():
        rows = fetch_fred_series(series_id, args.start, args.end)
        if args.apply and rows:
            write_fred_series_cache(args.cache_dir, series_key, rows)
            action = "written"
        elif not rows:
            action = "no_data_returned"
        else:
            action = "dry_run"
        print(f"- {series_key} ({series_id}): {action}, rows_fetched={len(rows)}")

    if not args.apply:
        print("\nDry run only — no cache files were written. Re-run with --apply to write the cache.")


if __name__ == "__main__":
    main()
