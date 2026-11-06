"""Everything non-price the wide root holds (V6.6.0): EDGAR fundamentals and sectors, splits, insider trades, short volume, factor returns.

Runs on the PC only. SEC refuses a client with no contact, and the contact comes from AQ_SEC_CONTACT for this process alone: it is never
written anywhere, and the run ends by checking that. Each part resumes or skips if its output exists.

    AQ_SEC_CONTACT=... python scripts/build_wide_info.py [--parts fundamentals splits insiders short factors]
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time as _time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_pipeline import edgar_facts, factor_library, finra_short_volume, net_retry, sec_form345  # noqa: E402
from data_pipeline.edgar_facts import CONTACT_ENV  # noqa: E402

WIDE = ROOT / "data_wide"
REFERENCE = WIDE / "reference"
CACHE = WIDE / "_cache"
ALL_PARTS = ("fundamentals", "splits", "insiders", "short", "factors")


def member_tickers(root: Path = WIDE) -> list[str]:
    manifest = json.loads((root / "wide_manifest.json").read_text(encoding="utf-8"))
    return sorted(ticker for ticker, entry in manifest["tickers"].items() if entry.get("member"))


def sec_headers() -> dict[str, str]:
    contact = os.environ.get(CONTACT_ENV, "").strip()
    if not contact:
        raise SystemExit(f"{CONTACT_ENV} is not set: SEC refuses a client with no contact")
    return {"User-Agent": f"AetherQuantResearch/6.6 {contact}", "Accept-Encoding": "gzip"}


def build_fundamentals(tickers: list[str]) -> dict:
    rows, sectors, missing = edgar_facts.fetch_fundamentals(tickers, cache_dir=CACHE / "edgar")
    edgar_facts.write_fundamentals(rows, REFERENCE / "edgar_fundamentals.csv.gz")
    (REFERENCE / "sectors.json").write_text(json.dumps(dict(sorted(sectors.items())), indent=1), encoding="utf-8", newline="\n")
    eps = edgar_facts.collect_cached_eps(tickers, CACHE / "edgar")
    pd.DataFrame(eps, columns=["ticker", "period_start", "period_end", "filed", "eps"]).to_csv(REFERENCE / "edgar_eps.csv.gz", index=False, lineterminator="\n", compression="gzip")
    return {"fundamental_rows": len(rows), "tickers_with_sector": len(sectors), "no_sec_data": sorted(missing)}


def build_splits(tickers: list[str]) -> dict:
    rows, failed = edgar_facts.fetch_splits_tolerant(tickers)
    pd.DataFrame(rows, columns=["ticker", "date", "ratio"]).to_csv(REFERENCE / "equity_splits.csv", index=False, lineterminator="\n")
    return {"split_rows": len(rows), "split_lookup_failed": sorted(failed)}


def _sec_get_bytes(headers: dict[str, str]):
    import requests

    def get(url: str) -> bytes | None:
        response = net_retry.fetch(url, get=requests.get, headers=headers, timeout=180.0)
        return None if response is None else response.content

    return get


def build_insiders(tickers: list[str]) -> dict:
    get = _sec_get_bytes(sec_headers())
    wanted = set(tickers)
    pieces = []
    (CACHE / "form345").mkdir(parents=True, exist_ok=True)
    for year, quarter in sec_form345.quarters(2006, 2026, 3):
        cached = CACHE / "form345" / f"{year}q{quarter}.csv.gz"
        if cached.exists():
            saved = pd.read_csv(cached, dtype=str)
            if not saved.empty:
                pieces.append(saved)
                continue
        frame = sec_form345.fetch_trades([(year, quarter)], get, wanted)
        if frame.empty:
            # A quarter of S&P 500 issuers always has trades: an empty one is a failure to read, and a cached empty would hide it for good.
            print(f"form345 {year}q{quarter}: no trades, not cached", flush=True)
            continue
        frame.to_csv(cached, index=False, lineterminator="\n", compression="gzip")
        pieces.append(frame.astype(str))
        print(f"form345 {year}q{quarter}: {len(frame)} trades", flush=True)
        _time.sleep(0.2)
    trades = pd.concat(pieces, ignore_index=True)
    trades.to_csv(REFERENCE / "insider_trades.csv.gz", index=False, lineterminator="\n", compression="gzip")
    return {"insider_trades": len(trades)}


def build_short(tickers: list[str]) -> dict:
    import requests

    session = requests.Session()
    session.headers["User-Agent"] = "AetherQuantResearch/6.6 (github.com/leon1706-lol/Aether-quant)"

    def get_text(url: str) -> str | None:
        # A date with no file is a 403 here, not a 404. Anything else is a failed fetch: it waits, or stops the run.
        response = net_retry.fetch(url, get=session.get, absent_codes=(403, 404), timeout=60.0)
        return None if response is None else response.text

    cache = CACHE / "finra"
    cache.mkdir(parents=True, exist_ok=True)
    pieces = []
    for month in pd.period_range("2018-08", "2026-11", freq="M"):
        cached = cache / f"{month}.parquet"
        if cached.exists():
            pieces.append(pd.read_parquet(cached))
            continue
        days = [day.strftime("%Y-%m-%d") for day in pd.bdate_range(month.start_time, min(month.end_time, pd.Timestamp("2026-11-02")))]
        frame = finra_short_volume.fetch_ratios(days, get_text, tickers)
        if frame.empty:
            print(f"finra {month}: no files, not cached", flush=True)
            continue
        frame.astype("float32").to_parquet(cached)
        pieces.append(frame)
        print(f"finra {month}: {len(frame)} days", flush=True)
    ratios = pd.concat(pieces).sort_index()
    if ratios.empty:
        raise SystemExit("no short-volume file read at all: this is a failure, not an absence")
    ratios.astype("float32").to_parquet(REFERENCE / "short_ratio.parquet")
    return {"short_ratio_days": len(ratios), "short_ratio_first": str(ratios.index.min()), "short_ratio_last": str(ratios.index.max())}


def build_factors() -> dict:
    import requests

    def get(url: str) -> bytes:
        response = requests.get(url, timeout=180, headers={"User-Agent": "AetherQuantResearch/6.6 (github.com/leon1706-lol/Aether-quant)"})
        response.raise_for_status()
        return response.content

    frame = factor_library.fetch_factors(get)
    frame.to_parquet(REFERENCE / "factors_daily.parquet")
    return {"factors": list(frame.columns), "factors_first": str(frame.index.min()), "factors_last": {column: str(frame[column].dropna().index.max()) for column in frame.columns}}


def contact_leaks(root: Path, contact: str) -> list[str]:
    """Files under the root holding the contact, gzip included. An address must never be stored, by this script or a library it called."""
    if not contact:
        return []
    needle = contact.encode("utf-8")
    hits = []
    for path in root.rglob("*"):
        if not path.is_file() or path.stat().st_size > 200_000_000:
            continue
        try:
            payload = path.read_bytes()
            if path.suffix == ".gz":
                payload = gzip.decompress(payload)
        except OSError:
            continue
        if needle in payload:
            hits.append(str(path))
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--parts", nargs="+", default=list(ALL_PARTS), choices=ALL_PARTS)
    args = parser.parse_args()
    REFERENCE.mkdir(parents=True, exist_ok=True)
    tickers = member_tickers()
    report_path = REFERENCE / "wide_info_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    builders = {
        "fundamentals": lambda: build_fundamentals(tickers), "splits": lambda: build_splits(tickers), "insiders": lambda: build_insiders(tickers),
        "short": lambda: build_short(tickers), "factors": build_factors,
    }
    for part in args.parts:
        try:
            report[part] = builders[part]()
        except net_retry.NetworkOutage as error:
            print(f"{part}: stopped by a network outage, rerun to resume: {error}", file=sys.stderr, flush=True)
            return 3
        report_path.write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
        print(part, json.dumps({key: value for key, value in report[part].items() if not isinstance(value, list)}), flush=True)
    leaks = contact_leaks(WIDE / "reference", os.environ.get(CONTACT_ENV, "").strip()) + contact_leaks(CACHE, os.environ.get(CONTACT_ENV, "").strip())
    if leaks:
        print(f"CONTACT FOUND IN {len(leaks)} FILE(S): remove before anything else", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
