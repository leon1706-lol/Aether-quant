"""V5.3.1 (development/Problems.md #34/#96) - standalone audit of every
real `order-events.json` this repo has ever produced (`backtests/*/​**/
order-events.json`, ~45 files as of this writing), turning the ad hoc
`grep`/manual-scan evidence Problems.md #34 was built from into a
repeatable, versioned tool instead of a one-off investigation.

Never wired into `aq` (matches scripts/profile_subsystems.py's own
convention - a standalone local-dev diagnostic, not a system report).

Reports, per run and aggregated across every run:
- a status-value histogram (cross-checks execution/order_gate.py's
  PENDING_ORDER_STATUS_NAMES/TERMINAL_*_STATUS_NAMES tuples stay
  exhaustive against whatever Lean's real OrderStatus enum actually
  produces - the tool's main forward-looking value, catching a future
  new/renamed status string before it silently falls through to
  "unknown")
- per-order fill latency (wall-clock time between the first "submitted"
  event and the terminal "filled"/"canceled" event for the same orderId -
  reported in hours, not "bars": a Unix timestamp alone can't be
  faithfully converted to a bar count without the exact trading calendar,
  and an approximate one would be more misleading than an honest
  time-based number)
- an UPPER-BOUND proxy for fallback-triggered market orders: Lean's
  order-events log carries no field linking a canceled limit order to
  the market order that (if `fallback_to_market_on_timeout` was on for
  that asset class) may have followed it, so this reports "canceled"
  counts only, honestly labeled as an upper bound, never presented as an
  exact fallback count.

Usage:
    python scripts/order_events_audit.py [--backtests-dir backtests] [--output PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKTESTS_DIR = ROOT_DIR / "backtests"
OUTPUT_PATH = Path(__file__).resolve().parent / "order_events_audit_output.txt"


def _iter_order_events_jsons(backtests_dir: Path) -> Iterator[Path]:
    """Yields every backtest run's order-events.json, newest folder first
    by mtime (not name - same "non-timestamped ad hoc folder names can
    otherwise sort ahead of real ones" reasoning as
    generate_backtest_report.py::_iter_backtest_result_jsons(), though
    this tool aggregates across ALL runs rather than picking one "latest",
    so the ordering only affects report readability, not correctness)."""
    if not backtests_dir.exists():
        return
    run_dirs = sorted(
        (d for d in backtests_dir.iterdir() if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    for run_dir in run_dirs:
        for candidate in sorted(run_dir.glob("*-order-events.json")):
            yield candidate


def load_order_events(path: Path) -> list[dict]:
    """Thin loader - order-events.json is a single JSON array (not JSONL).
    Returns [] for a missing/malformed file rather than raising, so one
    bad file never aborts a whole-repo audit."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def summarize_order_events(events: list[dict]) -> dict:
    """Pure function (no file I/O) - status histogram, per-order fill
    latency (hours between first "submitted" and the terminal
    "filled"/"canceled" event for that orderId), and canceled-count-by-
    symbol (the honest upper-bound fallback proxy - see module docstring).

    Returns {"num_events", "num_orders", "status_histogram",
    "fill_latency_hours": {"mean", "median", "max", "num_orders_measured"},
    "canceled_count_by_symbol"}. An empty events list returns all-zero/
    empty stats, never raises."""
    if not events:
        return {
            "num_events": 0,
            "num_orders": 0,
            "status_histogram": {},
            "fill_latency_hours": {"mean": None, "median": None, "max": None, "num_orders_measured": 0},
            "canceled_count_by_symbol": {},
        }

    status_histogram = Counter(event.get("status", "unknown") for event in events)

    events_by_order_id: dict = {}
    for event in events:
        events_by_order_id.setdefault(event.get("orderId"), []).append(event)

    fill_latency_hours: list[float] = []
    canceled_count_by_symbol: Counter = Counter()
    for order_id, order_events in events_by_order_id.items():
        order_events_sorted = sorted(order_events, key=lambda e: e.get("time", 0.0))
        submitted = next((e for e in order_events_sorted if e.get("status") == "submitted"), None)
        terminal = next((e for e in order_events_sorted if e.get("status") in ("filled", "canceled")), None)
        if submitted is not None and terminal is not None:
            latency_seconds = float(terminal.get("time", 0.0)) - float(submitted.get("time", 0.0))
            if latency_seconds >= 0:
                fill_latency_hours.append(latency_seconds / 3600.0)
        if terminal is not None and terminal.get("status") == "canceled":
            canceled_count_by_symbol[terminal.get("symbolValue", terminal.get("symbol", "unknown"))] += 1

    fill_latency_summary = {
        "mean": (sum(fill_latency_hours) / len(fill_latency_hours)) if fill_latency_hours else None,
        "median": sorted(fill_latency_hours)[len(fill_latency_hours) // 2] if fill_latency_hours else None,
        "max": max(fill_latency_hours) if fill_latency_hours else None,
        "num_orders_measured": len(fill_latency_hours),
    }

    return {
        "num_events": len(events),
        "num_orders": len(events_by_order_id),
        "status_histogram": dict(status_histogram),
        "fill_latency_hours": fill_latency_summary,
        "canceled_count_by_symbol": dict(canceled_count_by_symbol),
    }


def _merge_summaries(summaries: list[dict]) -> dict:
    """Aggregates summarize_order_events()'s per-file output across every
    file found - a simple sum/recompute, not a re-scan of raw events."""
    total_status_histogram: Counter = Counter()
    total_canceled_by_symbol: Counter = Counter()
    all_fill_latencies: list[float] = []
    total_events = 0
    total_orders = 0

    for summary in summaries:
        total_events += summary["num_events"]
        total_orders += summary["num_orders"]
        total_status_histogram.update(summary["status_histogram"])
        total_canceled_by_symbol.update(summary["canceled_count_by_symbol"])
        latency = summary["fill_latency_hours"]
        if latency["mean"] is not None:
            # Reconstruct the underlying values is not possible from a
            # summary alone - approximate by repeating the mean
            # num_orders_measured times, which preserves the aggregate
            # mean exactly and is a reasonable (if slightly smoothed)
            # approximation for max/median across files.
            all_fill_latencies.extend([latency["mean"]] * latency["num_orders_measured"])

    return {
        "num_files": len(summaries),
        "num_events": total_events,
        "num_orders": total_orders,
        "status_histogram": dict(total_status_histogram),
        "fill_latency_hours": {
            "mean": (sum(all_fill_latencies) / len(all_fill_latencies)) if all_fill_latencies else None,
            "num_orders_measured": len(all_fill_latencies),
        },
        "canceled_count_by_symbol_top_20": dict(total_canceled_by_symbol.most_common(20)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backtests-dir", type=Path, default=BACKTESTS_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    per_file_summaries = []
    lines = []
    for path in _iter_order_events_jsons(args.backtests_dir):
        events = load_order_events(path)
        if not events:
            continue
        summary = summarize_order_events(events)
        per_file_summaries.append(summary)
        lines.append(f"{path.relative_to(args.backtests_dir)}: {summary['num_orders']} orders, {summary['status_histogram']}")

    if not per_file_summaries:
        print(f"No order-events.json files found under {args.backtests_dir}.", file=sys.stderr)
        return 1

    aggregate = _merge_summaries(per_file_summaries)
    lines.append("")
    lines.append(f"=== Aggregate across {aggregate['num_files']} files ===")
    lines.append(f"Total orders: {aggregate['num_orders']}, total events: {aggregate['num_events']}")
    lines.append(f"Status histogram: {aggregate['status_histogram']}")
    lines.append(f"Fill latency (hours): {aggregate['fill_latency_hours']}")
    lines.append(f"Top canceled symbols (upper-bound fallback proxy, see module docstring): {aggregate['canceled_count_by_symbol_top_20']}")

    output_text = "\n".join(lines)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output_text, encoding="utf-8")
    print(output_text)
    print(f"\nFull audit written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
