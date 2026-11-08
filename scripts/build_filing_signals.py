"""Earnings-announcement dates and 10-K / 10-Q similarity for round 4E (V6.6.4): the inputs of q01, q02 and q06.

Runs on the PC only. SEC refuses a client with no contact, and the contact comes from AQ_SEC_CONTACT for this process alone: it is never written anywhere, and the run ends by searching
every file it wrote for it. A filing is read once and reduced to hashed word counts; no filing text is stored. Each ticker's rows are cached as it finishes, so a reaped or interrupted run
resumes where it stopped.

    AQ_SEC_CONTACT=... python scripts/build_filing_signals.py [--scope selection|full] [--limit N]

`--scope selection` (the default) takes side-A names only and nothing filed after 2018-12-31, which is all cell S reads. `--scope full` adds side B and runs to 2026-11-02, and is run only
for a candidate that has been frozen (the holdouts need those years).
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time as _time
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_pipeline import filing_text, net_retry  # noqa: E402
from data_pipeline.edgar_facts import CONTACT_ENV, SUBMISSIONS_URL, TICKERS_URL  # noqa: E402

WIDE = ROOT / "data_wide"
REFERENCE = WIDE / "reference"
CACHE = WIDE / "_cache" / "filings"
DOCUMENT_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
OLDER_PAGE_URL = "https://data.sec.gov/submissions/{name}"
SELECTION_WINDOW = ("2009-01-01", "2018-12-31")
FULL_WINDOW = ("2009-01-01", "2026-11-02")
PAUSE_SECONDS = 0.13  # under SEC's 10 requests a second
MAX_DOCUMENT_BYTES = 40_000_000


def sec_headers() -> dict[str, str]:
    contact = os.environ.get(CONTACT_ENV, "").strip()
    if not contact:
        raise SystemExit(f"{CONTACT_ENV} is not set: SEC refuses a client with no contact")
    return {"User-Agent": f"AetherQuantResearch/6.6 {contact}", "Accept-Encoding": "gzip"}


def names_in_scope(scope: str) -> list[str]:
    """Member tickers of the wide root; side A only for a selection run."""
    from evaluation.research_cells import name_side
    from evaluation.wide_context import project_tickers

    manifest = json.loads((WIDE / "wide_manifest.json").read_text(encoding="utf-8"))
    members = sorted(ticker for ticker, entry in manifest["tickers"].items() if entry.get("member"))
    if scope == "full":
        return members
    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    project = project_tickers(base, "equity")
    return [ticker for ticker in members if name_side(ticker, project) == "A"]


class Fetcher:
    def __init__(self, headers: dict[str, str]) -> None:
        import requests

        self.session = requests.Session()
        self.session.headers.update(headers)
        self.requests = 0

    def get(self, url: str):
        response = net_retry.fetch(url, get=self.session.get, timeout=120.0)
        self.requests += 1
        _time.sleep(PAUSE_SECONDS)
        return response

    def json(self, url: str) -> dict | None:
        response = self.get(url)
        return None if response is None else response.json()

    def counts(self, cik: int, row: dict) -> dict[int, int] | None:
        url = DOCUMENT_URL.format(cik=cik, accession=str(row["accessionNumber"]).replace("-", ""), document=row["primaryDocument"])
        response = self.get(url)
        if response is None or len(response.content) > MAX_DOCUMENT_BYTES:
            return None
        return filing_text.hashed_counts(filing_text.tokens(response.content.decode("utf-8", errors="replace"))) or None


def build_ticker(fetcher: Fetcher, cik: int, window: tuple[str, str]) -> dict:
    submissions = fetcher.json(SUBMISSIONS_URL.format(cik=cik)) or {}
    pages = [submissions]
    for entry in (submissions.get("filings") or {}).get("files") or []:
        if str(entry.get("filingTo", "9999")) >= window[0]:
            page = fetcher.json(OLDER_PAGE_URL.format(name=entry["name"]))
            if page:
                pages.append(page)
    filings = [row for row in filing_text.merge_pages(pages) if row["filingDate"] <= window[1]]
    earnings = [row for row in filing_text.earnings_rows(filings) if row["filed"] >= window[0]]
    in_window = [row for row in filings if row["filingDate"] >= window[0]]
    cache: dict[str, dict[int, int] | None] = {}

    def counts_of(row: dict):
        key = str(row["accessionNumber"])
        if key not in cache:
            cache[key] = fetcher.counts(cik, row)
        return cache[key]

    wanted = [(current, earlier) for current, earlier in filing_text.prior_year_pairs(filings) if current["filingDate"] >= window[0] and current in in_window]
    similarity = []
    for current, earlier in wanted:
        now, then = counts_of(current), counts_of(earlier)
        value = filing_text.cosine(now, then) if now and then else None
        if value is not None:
            similarity.append({"form": str(current["form"]), "period_end": str(current["reportDate"]), "filed": str(current["filingDate"]), "similarity": float(value)})
    return {"earnings": earnings, "similarity": sorted(similarity, key=lambda row: row["filed"])}


def write_outputs(cache_dir: Path, scope: str) -> dict:
    earnings, similarity = [], []
    for path in sorted(cache_dir.glob("*.json")):
        ticker = path.stem.upper()
        saved = json.loads(path.read_text(encoding="utf-8"))
        earnings += [{"ticker": ticker, **row} for row in saved["earnings"]]
        similarity += [{"ticker": ticker, **row} for row in saved["similarity"]]
    REFERENCE.mkdir(parents=True, exist_ok=True)
    earn_frame = pd.DataFrame(earnings, columns=["ticker", "accepted", "filed"])
    sim_frame = pd.DataFrame(similarity, columns=["ticker", "form", "period_end", "filed", "similarity"])
    earn_frame.to_csv(REFERENCE / "earnings_dates.csv.gz", index=False, lineterminator="\n", compression="gzip")
    sim_frame.to_csv(REFERENCE / "filing_similarity.csv.gz", index=False, lineterminator="\n", compression="gzip")
    by_year_names = lambda frame: {str(year): int(count) for year, count in frame.assign(year=frame["filed"].str[:4]).groupby("year")["ticker"].nunique().items()}  # noqa: E731
    report = {
        "scope": scope, "tickers_cached": len(list(cache_dir.glob("*.json"))), "earnings_rows": len(earn_frame), "similarity_rows": len(sim_frame),
        "names_with_earnings_by_year": by_year_names(earn_frame), "names_with_similarity_by_year": by_year_names(sim_frame),
    }
    (REFERENCE / "filing_signals_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    return report


def assert_contact_not_written() -> None:
    """The run ends by searching what it wrote for the contact, as build_wide_info.py does."""
    contact = os.environ.get(CONTACT_ENV, "").strip()
    if not contact:
        return
    needle = contact.encode("utf-8")
    paths = [REFERENCE / "earnings_dates.csv.gz", REFERENCE / "filing_similarity.csv.gz", REFERENCE / "filing_signals_report.json", *CACHE.glob("*.json")]
    for path in paths:
        if not path.exists():
            continue
        data = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
        if needle in data:
            raise SystemExit(f"the SEC contact was found in {path}: delete the output and report this")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scope", choices=["selection", "full"], default="selection")
    parser.add_argument("--limit", type=int, default=None, help="only the first N tickers (a trial run)")
    args = parser.parse_args(argv)
    headers = sec_headers()
    window = SELECTION_WINDOW if args.scope == "selection" else FULL_WINDOW
    cache_dir = CACHE / args.scope
    cache_dir.mkdir(parents=True, exist_ok=True)
    fetcher = Fetcher(headers)
    directory = fetcher.json(TICKERS_URL) or {}
    cik_by_ticker = {str(item["ticker"]).upper().replace("-", "."): int(item["cik_str"]) for item in directory.values()}
    tickers = names_in_scope(args.scope)[: args.limit]
    missing = Counter()
    for position, ticker in enumerate(tickers, 1):
        cached = cache_dir / f"{ticker.lower()}.json"
        if cached.exists():
            continue
        cik = cik_by_ticker.get(ticker.upper())
        if cik is None:
            missing["no_cik"] += 1
            cached.write_text(json.dumps({"earnings": [], "similarity": []}), encoding="utf-8", newline="\n")
            continue
        try:
            saved = build_ticker(fetcher, cik, window)
        except net_retry.NetworkOutage as error:
            print(f"stopped at {ticker}: {error}. Everything cached is kept; run again to resume.", flush=True)
            return 2
        except Exception as error:  # one failed company must not lose the others; it is retried on the next run
            print(f"{ticker}: {type(error).__name__}", flush=True)
            missing["failed"] += 1
            continue
        cached.write_text(json.dumps(saved, separators=(",", ":")), encoding="utf-8", newline="\n")
        print(f"[{position}/{len(tickers)}] {ticker}: {len(saved['earnings'])} announcements, {len(saved['similarity'])} similarities", flush=True)
    report = write_outputs(cache_dir, args.scope)
    report["not_found_or_failed"] = dict(missing)
    (REFERENCE / "filing_signals_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8", newline="\n")
    assert_contact_not_written()
    print(json.dumps({key: report[key] for key in ("scope", "tickers_cached", "earnings_rows", "similarity_rows", "not_found_or_failed")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
