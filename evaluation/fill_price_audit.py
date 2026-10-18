"""Fill price vs the bar's open, from a finished Lean run (V5.7.0, todo.md finding 6).

The V5.6.0 round measured a median 5 bps / p99 53 bps gap between a fill and the dataset's open and could not say how
much was execution cost and how much was the dataset reading different prices than Lean trades. This separates them:
every fill is compared with (a) the dataset's open for that ticker-date and (b) the open in the Lean data zip itself,
and the two references are compared with each other. A zip-vs-dataset gap is a data-parity defect (AGENTS rule 12); a
fill-vs-zip gap on MARKET orders is slippage; on LIMIT orders it is the limit offset by design.

Pure functions over parsed JSON/CSV rows plus one zip reader. stdlib only.
"""

from __future__ import annotations

import bisect
import csv
import io
import math
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

SECURITY_TYPE_NAMES = {1: "equity", 2: "option", 4: "forex", 5: "future", 7: "crypto"}
ORDER_TYPE_NAMES = {0: "market", 1: "limit"}
FILLED_STATUSES = {"filled", "partiallyfilled"}
# Equity fills land at the 09:30 New York open: 14:30 UTC (EST) or 13:30 UTC (EDT), so UTC-5 keeps them on that date.
EQUITY_DATE_SHIFT = timedelta(hours=5)
# Lean writes equity daily prices in deci-cents.
EQUITY_PRICE_SCALE = 1.0 / 10_000.0


def fills_from_run(run: dict) -> list[dict]:
    """One dict per filled order event: symbol, date, price, direction (+1 buy / -1 sell), asset class, order type."""
    orders = run.get("result", {}).get("orders", {})
    fills: list[dict] = []
    for event in run.get("order_events", []):
        if str(event.get("status", "")).lower() not in FILLED_STATUSES:
            continue
        try:
            price = float(event.get("fillPrice") or 0.0)
            quantity = abs(float(event.get("fillQuantity") or 0.0))
            when = datetime.fromtimestamp(float(event["time"]), tz=timezone.utc)
        except (TypeError, ValueError, KeyError):
            continue
        if price <= 0.0 or quantity <= 0.0:
            continue
        order = orders.get(str(event.get("orderId")), {})
        asset_class = SECURITY_TYPE_NAMES.get(int(order.get("securityType", 0) or 0), "other")
        local = when - EQUITY_DATE_SHIFT if asset_class == "equity" else when
        fills.append(
            {
                "symbol": str(event.get("symbolValue") or event.get("symbol", "")),
                "date": local.date().isoformat(),
                "price": price,
                "quantity": quantity,
                "direction": 1 if str(event.get("direction", "")).lower() == "buy" else -1,
                "asset_class": asset_class,
                "order_type": ORDER_TYPE_NAMES.get(int(order.get("type", 0) or 0), "other"),
            }
        )
    return fills


def lean_daily_zip_path(data_root: Path, ticker: str, asset_class: str) -> Path | None:
    name = ticker.lower()
    if asset_class == "equity":
        return Path(data_root) / "equity" / "usa" / "daily" / f"{name}.zip"
    if asset_class == "crypto":
        return Path(data_root) / "crypto" / "coinbase" / "daily" / f"{name}_trade.zip"
    if asset_class == "forex":
        return Path(data_root) / "forex" / "oanda" / "daily" / f"{name}.zip"
    return None


def read_zip_daily_opens(zip_path: Path, price_scale: float = 1.0) -> dict[str, float]:
    """{YYYY-MM-DD: open} from a Lean daily zip ("YYYYMMDD 00:00,open,high,low,close,..."). Missing file -> {}."""
    path = Path(zip_path)
    if not path.exists():
        return {}
    opens: dict[str, float] = {}
    with zipfile.ZipFile(path) as archive:
        for member in archive.namelist():
            for row in csv.reader(io.StringIO(archive.read(member).decode("utf-8", errors="replace"))):
                if len(row) < 2 or len(row[0]) < 8:
                    continue
                try:
                    opens[f"{row[0][:4]}-{row[0][4:6]}-{row[0][6:8]}"] = float(row[1]) * price_scale
                except ValueError:
                    continue
    return opens


def read_factor_file(path: Path) -> list[tuple[str, float, float]]:
    """Lean equity factor file rows `YYYYMMDD,price_factor,split_factor,reference_price` -> [(YYYY-MM-DD, price, split)],
    sorted by date. Missing file -> []."""
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(",")
        if len(parts) < 3 or len(parts[0]) < 8:
            continue
        try:
            rows.append((f"{parts[0][:4]}-{parts[0][4:6]}-{parts[0][6:8]}", float(parts[1]), float(parts[2])))
        except ValueError:
            continue
    return sorted(rows)


def apply_factor_rows(opens: dict[str, float], factors: list[tuple[str, float, float]]) -> dict[str, float]:
    """Lean's DataNormalizationMode.Adjusted (and train.apply_split_adjustments): each open times price_factor x
    split_factor of the first factor row dated on or AFTER it; dates after every row stay unadjusted."""
    if not factors:
        return dict(opens)
    dates = [row[0] for row in factors]
    adjusted = {}
    for date, value in opens.items():
        position = bisect.bisect_left(dates, date)
        factor = factors[position][1] * factors[position][2] if position < len(factors) else 1.0
        adjusted[date] = value * factor
    return adjusted


def _quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return math.nan
    position = q * (len(sorted_values) - 1)
    low, high = int(math.floor(position)), int(math.ceil(position))
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


def _distribution(values: list[float]) -> dict:
    ordered = sorted(values)
    absolute = sorted(abs(value) for value in values)
    if not ordered:
        return {"n": 0}
    return {
        "n": len(ordered),
        "median_signed_bps": round(_quantile(ordered, 0.5), 3),
        "mean_signed_bps": round(sum(ordered) / len(ordered), 3),
        "median_abs_bps": round(_quantile(absolute, 0.5), 3),
        "p90_abs_bps": round(_quantile(absolute, 0.9), 3),
        "p99_abs_bps": round(_quantile(absolute, 0.99), 3),
        "max_abs_bps": round(absolute[-1], 3),
    }


def fill_vs_reference(fills: list[dict], references: dict[tuple[str, str], float]) -> dict:
    """Per (asset class, order type): distribution of the signed cost in bps against `references[(symbol, date)]`.
    Positive = the fill was worse than the reference (paid more on a buy, received less on a sell)."""
    grouped: dict[str, list[float]] = defaultdict(list)
    missing = 0
    for fill in fills:
        reference = references.get((fill["symbol"], fill["date"]))
        if reference is None or reference <= 0.0:
            missing += 1
            continue
        cost_bps = fill["direction"] * (fill["price"] - reference) / reference * 1e4
        grouped[f"{fill['asset_class']}/{fill['order_type']}"].append(cost_bps)
        grouped[f"{fill['asset_class']}/all"].append(cost_bps)
    return {"groups": {key: _distribution(values) for key, values in sorted(grouped.items())}, "fills_without_reference": missing}


def reference_gap(
    dataset_opens: dict[tuple[str, str], float], zip_opens: dict[tuple[str, str], float]
) -> dict:
    """Dataset open vs Lean-zip open over the ticker-dates both have: a non-zero gap means the dataset reads different
    prices than Lean trades (adjustment source), independent of any execution cost."""
    gaps = [
        (dataset_opens[key] - zip_opens[key]) / zip_opens[key] * 1e4
        for key in dataset_opens.keys() & zip_opens.keys()
        if zip_opens[key] > 0.0
    ]
    return _distribution(gaps)


def zip_opens_for_fills(fills: list[dict], data_root: Path) -> dict[tuple[str, str], float]:
    """{(symbol, date): open} from the Lean data zips of every traded symbol; equity opens adjusted like the engine."""
    zip_opens: dict[tuple[str, str], float] = {}
    for symbol, asset_class in sorted({(fill["symbol"], fill["asset_class"]) for fill in fills}):
        path = lean_daily_zip_path(data_root, symbol, asset_class)
        if path is None:
            continue
        scale = EQUITY_PRICE_SCALE if asset_class == "equity" else 1.0
        opens = read_zip_daily_opens(path, scale)
        if asset_class == "equity":
            # the engine trades Adjusted prices: apply the factor file the same way the dataset builder does
            opens = apply_factor_rows(opens, read_factor_file(Path(data_root) / "equity" / "usa" / "factor_files" / f"{symbol.lower()}.csv"))
        for date, value in opens.items():
            zip_opens[(symbol, date)] = value
    return zip_opens


def audit_fills(
    run: dict,
    dataset_opens: dict[tuple[str, str], float],
    data_root: Path,
) -> dict:
    """The whole audit: fills against the dataset open and against the Lean zip open, plus the dataset-vs-zip gap on the
    traded ticker-dates."""
    fills = fills_from_run(run)
    zip_opens = zip_opens_for_fills(fills, data_root)
    traded_keys = {(fill["symbol"], fill["date"]) for fill in fills}
    traded_dataset = {key: value for key, value in dataset_opens.items() if key in traded_keys}
    traded_zip = {key: value for key, value in zip_opens.items() if key in traded_keys}
    return {
        "num_fills": len(fills),
        "fill_vs_dataset_open": fill_vs_reference(fills, dataset_opens),
        "fill_vs_zip_open": fill_vs_reference(fills, zip_opens),
        "dataset_open_vs_zip_open_on_traded_dates": reference_gap(traded_dataset, traded_zip),
        "notes": [
            "cost > 0 means worse than the reference open; limit fills differ from the open by the limit offset by design.",
            "equity fills are dated by the New York session (UTC-5); crypto/forex by their UTC date.",
        ],
    }
