"""Filing text as hashed word counts, and the dates around them (V6.6.4): the inputs of round 4E's q01, q02 and q06.

A 10-K or 10-Q is reduced to a sparse count of hashed words the moment it is read, and the text is dropped: nothing here stores a filing. The similarity of a filing to the same form a
year earlier is the cosine of their counts (Cohen, Malloy and Nguyen's "lazy prices", in a cheap form). An 8-K carrying Item 2.02 is an earnings release; its acceptance time dates the
announcement. Pure functions, stdlib only apart from the parsed submissions JSON they are handed.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

BUCKETS = 1 << 18
_TAG = re.compile(r"<[^>]*>")
_ENTITY = re.compile(r"&[#a-zA-Z0-9]+;")
_WORD = re.compile(r"[a-z]{3,}")
ANNUAL_FORMS = ("10-K", "10-K405", "10-KSB")
QUARTERLY_FORMS = ("10-Q",)
YEAR_DAYS = (330, 400)


def tokens(html: str) -> list[str]:
    """Lower-case words of three letters or more, with tags and entities removed."""
    text = _ENTITY.sub(" ", _TAG.sub(" ", html or ""))
    return _WORD.findall(text.lower())


def hashed_counts(words: Sequence[str], buckets: int = BUCKETS) -> dict[int, int]:
    """Word counts keyed by a stable hash (blake2b, so it doesn't change between runs or machines)."""
    counts: dict[int, int] = {}
    for word in words:
        key = int.from_bytes(hashlib.blake2b(word.encode("utf-8"), digest_size=4).digest(), "big") % buckets
        counts[key] = counts.get(key, 0) + 1
    return counts


def cosine(left: Mapping[int, int], right: Mapping[int, int]) -> float | None:
    """The cosine of two count vectors, or None when either is empty."""
    if not left or not right:
        return None
    small, large = (left, right) if len(left) <= len(right) else (right, left)
    dot = sum(count * large.get(key, 0) for key, count in small.items())
    norm = math.sqrt(sum(count * count for count in left.values())) * math.sqrt(sum(count * count for count in right.values()))
    return dot / norm if norm > 0.0 else None


def _rows_of(submissions: Mapping[str, Any]) -> list[dict]:
    recent = ((submissions or {}).get("filings") or {}).get("recent") or {}
    columns = {key: list(recent.get(key) or []) for key in ("accessionNumber", "filingDate", "acceptanceDateTime", "form", "primaryDocument", "items", "reportDate")}
    length = len(columns["accessionNumber"])
    return [{key: (values[position] if position < len(values) else "") for key, values in columns.items()} for position in range(length)]


def merge_pages(pages: Sequence[Mapping]) -> list[dict]:
    """Filing rows from the recent block and any older pages (SEC's `filings.files`), oldest first, one row per accession."""
    seen: dict[str, dict] = {}
    for page in pages:
        rows = _rows_of(page if "filings" in page else {"filings": {"recent": page}})
        for row in rows:
            seen.setdefault(row["accessionNumber"], row)
    return sorted(seen.values(), key=lambda row: (row["filingDate"], row["accessionNumber"]))


def earnings_rows(filings: Sequence[Mapping]) -> list[dict]:
    """8-Ks that carry Item 2.02 (results of operations): `accepted` is the acceptance timestamp, `filed` the filing date."""
    out = []
    for row in filings:
        if str(row.get("form")) != "8-K":
            continue
        if "2.02" not in {item.strip() for item in str(row.get("items") or "").split(",")}:
            continue
        out.append({"accepted": str(row.get("acceptanceDateTime") or row.get("filingDate")), "filed": str(row["filingDate"])})
    return sorted(out, key=lambda row: row["accepted"])


def _days(first: str, second: str) -> int:
    import datetime

    return (datetime.date.fromisoformat(second[:10]) - datetime.date.fromisoformat(first[:10])).days


def prior_year_pairs(filings: Sequence[Mapping]) -> list[tuple[Mapping, Mapping]]:
    """(this filing, the same form a year earlier) for each 10-K and 10-Q that has one, matched on the report date: 330 to 400 days apart, the nearest to a year. Never a later filing."""
    pairs = []
    for forms in (ANNUAL_FORMS, QUARTERLY_FORMS):
        group = [row for row in filings if str(row.get("form")) in forms and row.get("reportDate") and row.get("primaryDocument")]
        for row in group:
            candidates = [other for other in group if YEAR_DAYS[0] <= _days(str(other["reportDate"]), str(row["reportDate"])) <= YEAR_DAYS[1]]
            if candidates:
                pairs.append((row, min(candidates, key=lambda other: abs(_days(str(other["reportDate"]), str(row["reportDate"])) - 365))))
    return pairs


def similarity_rows(filings: Sequence[Mapping], counts_of: Callable[[Mapping[str, Any]], Mapping[str, int] | None]) -> list[dict]:
    """One row per filing that has a year-earlier twin: ticker-free `{form, period_end, filed, similarity}`. `counts_of(row)` returns that filing's hashed counts (or None when it can't be read)."""
    rows = []
    for current, earlier in prior_year_pairs(filings):
        now, then = counts_of(current), counts_of(earlier)
        value = cosine(now, then) if now and then else None
        if value is not None:
            rows.append({"form": str(current["form"]), "period_end": str(current["reportDate"]), "filed": str(current["filingDate"]), "similarity": float(value)})
    return sorted(rows, key=lambda row: row["filed"])
