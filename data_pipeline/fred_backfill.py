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
import bisect
import csv
import json
import logging
import urllib.error
import urllib.request
from datetime import date, timedelta
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

# Phase 4.12 (development/Problems.md #71): the alternative-data trio
# feeding features/alt_data_features.py. Chosen from a wider candidate list
# (VIX/VXV/NFCI/STLFSI4/UMCSENT/TEDRATE/SOFR/BAMLH0A0HYM2/DTWEXBGS) after
# live-fetching each one and checking (a) real coverage across
# phase1.universe.common_window (2014-12-01..2021-03-31) and (b)
# collinearity against the 8 existing bond_* features and against each
# other. STLFSI4/NFCI-level/BAA10Y overlap too much (rho 0.67-0.88) to add
# both; UMCSENT/TEDRATE/SOFR fail on coverage or lag; BAMLH0A0HYM2 has NO
# usable history before 2023-07-25 through FRED's keyless endpoint (ICE
# BofA series are license-restricted beyond a short trailing window) - do
# not re-add it without a paid FRED API key.
DEFAULT_ALT_DATA_REFERENCE_SERIES = {
    "implied_volatility_vix": "VIXCLS",
    "implied_volatility_3m": "VXVCLS",
    "financial_conditions_nfci": "NFCI",
}

# Days to subtract from the decision date before doing the as-of lookup
# (see series_value_asof()) - i.e. how many days after a series' own date
# column the observation is actually PUBLISHED. VIX/VXV are same-day CBOE
# closes (0 lag, identical convention to the Treasury/BAA10Y series
# above). NFCI observations are Friday-dated but released the FOLLOWING
# Wednesday (+5 calendar days); 7 is a deliberately conservative superset
# that survives a holiday-shifted release. Verified this session: every
# cached NFCI row falls on a Friday.
ALT_DATA_PUBLICATION_LAG_DAYS = {
    "implied_volatility_vix": 0,
    "implied_volatility_3m": 0,
    "financial_conditions_nfci": 7,
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


def series_value_asof(rows: list[dict], current_date, publication_lag_days: int = 0) -> float | None:
    """Most recent observation whose value was PUBLISHED on or before
    current_date - the shared, publication-lag-aware as-of lookup for
    BOTH train.py::build_alt_data_features_by_date() and
    main.py::_build_alt_data_payload(), so the lookahead rule below cannot
    drift between the two callers the way build_bond_features_by_date()'s
    inline _series_asof_lookup() and main.py::_fred_series_asof() already
    have (both correct for a same-day series, since publication_lag_days
    is implicitly 0 there - but that helper has no lag parameter at all,
    so it must never be reused for a lagged series).

    The lookahead this guards against: FRED dates every observation by its
    REFERENCE period, not its release date. DGS10's 2020-03-16 row is that
    day's close, known that evening (lag 0, safe). NFCI's 2020-03-20 row
    is the week ENDING Friday 2020-03-20, not released until Wednesday
    2020-03-25 (lag ~5-7 days) - a bare bisect_right(dates, current_date)
    would hand a 2020-03-23 decision a number that did not exist for two
    more days. effective_date = current_date - publication_lag_days
    reproduces the exact bisect every existing 0-lag caller already does
    when publication_lag_days=0 (see
    test_series_value_asof_zero_lag_matches_existing_bisect_behavior).

    `rows` is one series' [{"date": date, "value": float}, ...] - the same
    per-series list load_cached_fred_series() returns. Returns None (never
    raises) if `rows` is empty or every observation postdates
    effective_date."""
    if not rows:
        return None
    target = current_date.date() if hasattr(current_date, "date") else current_date
    effective_date = target - timedelta(days=publication_lag_days)
    ordered = sorted(rows, key=lambda row: row["date"])
    dates = [row["date"] for row in ordered]
    values = [row["value"] for row in ordered]
    position = bisect.bisect_right(dates, effective_date)
    if position == 0:
        return None
    return values[position - 1]


def series_change_asof(
    rows: list[dict],
    current_date,
    publication_lag_days: int = 0,
    periods_back: int = 4,
) -> float | None:
    """value_asof(current_date) minus the observation `periods_back`
    OBSERVATIONS (not calendar days) earlier in the same series - e.g.
    periods_back=4 on a weekly series is a 4-week change. Both endpoints
    are read from the same lag-adjusted, sorted index position, so the
    change inherits series_value_asof()'s publication guard by
    construction - there is no code path where the more-recent endpoint is
    unpublished as of current_date.

    Returns None (never 0.0 - a missing change must not look like "no
    change") when `rows` is empty, current_date predates every
    observation, or fewer than periods_back+1 observations precede
    effective_date."""
    if not rows:
        return None
    target = current_date.date() if hasattr(current_date, "date") else current_date
    effective_date = target - timedelta(days=publication_lag_days)
    ordered = sorted(rows, key=lambda row: row["date"])
    dates = [row["date"] for row in ordered]
    values = [row["value"] for row in ordered]
    position = bisect.bisect_right(dates, effective_date)
    prior_index = position - 1 - periods_back
    if position == 0 or prior_index < 0:
        return None
    return values[position - 1] - values[prior_index]


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


def alt_data_reference_series(config: dict) -> dict[str, str]:
    """Phase 4.12 (development/Problems.md #71) sibling of
    bond_reference_series(): config["phase1"]["features"]["alt_data_reference_series"],
    falling back to DEFAULT_ALT_DATA_REFERENCE_SERIES."""
    return {
        **DEFAULT_ALT_DATA_REFERENCE_SERIES,
        **config.get("phase1", {}).get("features", {}).get("alt_data_reference_series", {}),
    }


def reference_series(config: dict, group: str = "all") -> dict[str, str]:
    """Merged view over bond_reference_series()/alt_data_reference_series()
    for the CLI's --group flag. group="bond" or "alt" returns just that
    one map unchanged (bond_reference_series() itself is deliberately left
    untouched by this addition - see test_bond_reference_series_unchanged_by_alt_addition);
    "all" (default) merges both, alt_data keys taking precedence only in
    the pathological case of an actual name collision (none exist today -
    the two dicts' keys are disjoint by construction)."""
    if group == "bond":
        return bond_reference_series(config)
    if group == "alt":
        return alt_data_reference_series(config)
    return {**bond_reference_series(config), **alt_data_reference_series(config)}


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
    parser.add_argument("--series", nargs="*", default=None, help="Restrict to these series keys (default: all of --group's reference series)")
    parser.add_argument(
        "--group",
        choices=["bond", "alt", "all"],
        default="all",
        help="Which reference-series map to fetch: bond (phase1.features.bond_reference_series), "
        "alt (phase1.features.alt_data_reference_series, Problems.md #71), or all (default, both merged)",
    )
    parser.add_argument("--start", default="1990-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--apply", action="store_true", help="Actually write the local cache (default: dry run, report only)")
    parser.add_argument("--config-path", type=Path, default=CONFIG_PATH)
    parser.add_argument("--cache-dir", type=Path, default=FRED_SERIES_CACHE_DIR)
    args = parser.parse_args()

    with args.config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    series_map = reference_series(config, args.group)
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
