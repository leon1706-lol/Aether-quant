"""Regenerates README.md's "Backtest Results" section from the most recent
real Lean backtest run under backtests/.

A static markdown file can't truly "live update," so this is the practical
substitute: `aq backtest` calls this module after a successful `lean
backtest .` run, and it rewrites a chart image plus a small stats table
in-place between two HTML comment markers in README.md, so the README stays
current with whatever backtest you last ran without any manual copy-pasting.

Data source: Lean's own backtest result JSON (`backtests/<run>/<id>.json`)
already contains everything needed, natively time-aligned, in one file - no
cross-file join needed:
- `statistics`: a flat dict of ready-to-use strings (Sharpe Ratio, Net
  Profit, Drawdown, ...).
- `charts["Strategy Equity"]["series"]["Equity"]["values"]`: the algorithm's
  own dated equity curve.
- `charts["Benchmark"]["series"]["Benchmark"]["values"]`: Lean's own
  benchmark series. `main.py`/`lean.json` never call `SetBenchmark(...)`, so
  this is Lean's documented default - SPY - already time-aligned with
  "Strategy Equity" in the same file.

Usage:
    python generate_backtest_report.py [--backtests-dir backtests] [--readme README.md] [--chart-path development/backtest_equity_chart.png]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT_DIR = Path(__file__).resolve().parent
BACKTESTS_DIR = ROOT_DIR / "backtests"
README_PATH = ROOT_DIR / "README.md"
CHART_PATH = ROOT_DIR / "development" / "backtest_equity_chart.png"

_RESULT_JSON_PATTERN = re.compile(r"^\d+\.json$")
BACKTEST_MARKER_START = "<!-- AQ:BACKTEST_START -->"
BACKTEST_MARKER_END = "<!-- AQ:BACKTEST_END -->"

_STAT_KEYS_FOR_TABLE = [
    "Sharpe Ratio",
    "Net Profit",
    "Compounding Annual Return",
    "Drawdown",
    "Total Orders",
    "Win Rate",
]


def _iter_backtest_result_jsons(backtests_dir: Path) -> Iterator[Path]:
    """Yields every backtest run's bare <digits>.json result file (never
    *-summary.json), newest folder first. Sorted by each folder's own mtime,
    not by name: the standard `lean backtest .` folders are named
    YYYY-MM-DD_HH-MM-SS (lexicographic == chronological), but this
    directory can also contain differently-named ad-hoc/manual run folders
    (e.g. `lean-local-test-N`) that would otherwise sort ahead of every
    real timestamped folder and get picked as "latest" by mistake."""
    if not backtests_dir.exists():
        return
    run_dirs = sorted(
        (d for d in backtests_dir.iterdir() if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    for run_dir in run_dirs:
        for candidate in sorted(run_dir.iterdir()):
            if candidate.is_file() and _RESULT_JSON_PATTERN.match(candidate.name):
                yield candidate
                break  # at most one result JSON per backtest folder


def find_latest_backtest_result_json(backtests_dir: Path = BACKTESTS_DIR) -> Path | None:
    """Returns the newest backtest run's result JSON that actually contains
    a populated Strategy Equity curve - skips runs that errored out before
    producing real results (Lean still writes a near-empty result JSON for
    those), so a crashed run never clobbers the README with empty data."""
    for candidate in _iter_backtest_result_jsons(backtests_dir):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        values = data.get("charts", {}).get("Strategy Equity", {}).get("series", {}).get("Equity", {}).get("values", [])
        if values:
            return candidate
    return None


def load_backtest_summary(result_json_path: Path) -> dict:
    """Parses a Lean backtest result JSON into a clean summary: the
    statistics dict, plus dated (timestamp, value) strategy/benchmark
    series."""
    data = json.loads(result_json_path.read_text(encoding="utf-8"))
    statistics = data.get("statistics", {})
    charts = data.get("charts", {})

    strategy_points = charts.get("Strategy Equity", {}).get("series", {}).get("Equity", {}).get("values", [])
    benchmark_points = charts.get("Benchmark", {}).get("series", {}).get("Benchmark", {}).get("values", [])

    # Equity points are [timestamp, open, high, low, close] with all four
    # OHLC values identical (an equity total, not a real price bar) -
    # benchmark points are plain [timestamp, price]. The last element is
    # the value we want in both cases.
    strategy_series = [(int(point[0]), float(point[-1])) for point in strategy_points]
    benchmark_series = [(int(point[0]), float(point[-1])) for point in benchmark_points]

    start_date = datetime.fromtimestamp(strategy_series[0][0], tz=timezone.utc) if strategy_series else None
    end_date = datetime.fromtimestamp(strategy_series[-1][0], tz=timezone.utc) if strategy_series else None

    return {
        "statistics": statistics,
        "strategy_series": strategy_series,
        "benchmark_series": benchmark_series,
        "start_date": start_date,
        "end_date": end_date,
        "result_json_path": result_json_path,
    }


def _rebase_to_100(series: list[tuple[int, float]]) -> list[tuple[int, float]]:
    """Both series need a common visual scale: strategy equity starts at
    the algorithm's starting cash (e.g. $100,000), the benchmark is a raw
    SPY price - neither is directly comparable to the other in absolute
    terms, so both are indexed to start at 100."""
    if not series:
        return []
    base = series[0][1]
    if base == 0:
        return [(timestamp, 100.0) for timestamp, _ in series]
    return [(timestamp, value / base * 100.0) for timestamp, value in series]


def generate_equity_chart(summary: dict, output_path: Path = CHART_PATH) -> None:
    """Renders the strategy-vs-benchmark equity chart as a PNG, embedded in
    README.md by update_readme_backtest_section()."""
    strategy = _rebase_to_100(summary["strategy_series"])
    benchmark = _rebase_to_100(summary["benchmark_series"])

    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(9, 4.5), dpi=150)
    if strategy:
        strategy_dates = [datetime.fromtimestamp(ts, tz=timezone.utc) for ts, _ in strategy]
        ax.plot(
            strategy_dates,
            [value for _, value in strategy],
            label="Aether Quant Strategy",
            color="#2E86AB",
            linewidth=1.6,
        )
    if benchmark:
        benchmark_dates = [datetime.fromtimestamp(ts, tz=timezone.utc) for ts, _ in benchmark]
        ax.plot(
            benchmark_dates,
            [value for _, value in benchmark],
            label="S&P 500 (SPY) Benchmark",
            color="#A23B72",
            linewidth=1.6,
            linestyle="--",
        )

    ax.set_title("Backtest Equity: Strategy vs. S&P 500 Benchmark (indexed to 100)")
    ax.set_ylabel("Indexed value (start = 100)")
    ax.legend(loc="best", frameon=False)
    ax.grid(True, alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)


def _build_stats_markdown(summary: dict, chart_relative_path: str) -> str:
    statistics = summary["statistics"]
    start_date, end_date = summary["start_date"], summary["end_date"]
    window = (
        f"{start_date.date().isoformat()} to {end_date.date().isoformat()}" if start_date and end_date else "unknown"
    )
    updated_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"![Backtest equity curve]({chart_relative_path})",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Backtest window | {window} |",
    ]
    for key in _STAT_KEYS_FOR_TABLE:
        if key in statistics:
            lines.append(f"| {key} | {statistics[key]} |")
    lines.append(f"| Last updated | {updated_at} (auto-generated by `aq backtest`) |")
    return "\n".join(lines)


def update_readme_backtest_section(
    summary: dict, readme_path: Path = README_PATH, chart_path: Path = CHART_PATH
) -> bool:
    """Atomically replaces the content between the AQ:BACKTEST markers in
    README.md with a fresh stats table + chart image reference. Returns
    False (never raises) if the README or its markers are missing - a
    report-generation bug must never break `aq backtest` itself."""
    if not readme_path.exists():
        return False
    text = readme_path.read_text(encoding="utf-8")
    if BACKTEST_MARKER_START not in text or BACKTEST_MARKER_END not in text:
        return False

    try:
        chart_relative_path = chart_path.relative_to(readme_path.resolve().parent).as_posix()
    except ValueError:
        chart_relative_path = chart_path.as_posix()

    stats_markdown = _build_stats_markdown(summary, chart_relative_path)
    pattern = re.compile(re.escape(BACKTEST_MARKER_START) + r".*?" + re.escape(BACKTEST_MARKER_END), re.DOTALL)
    replacement = f"{BACKTEST_MARKER_START}\n{stats_markdown}\n{BACKTEST_MARKER_END}"
    updated_text = pattern.sub(replacement, text, count=1)

    if updated_text == text:
        return False

    tmp_path = readme_path.with_suffix(readme_path.suffix + ".tmp")
    tmp_path.write_text(updated_text, encoding="utf-8")
    tmp_path.replace(readme_path)
    return True


def update_readme_from_latest_backtest(
    backtests_dir: Path = BACKTESTS_DIR,
    readme_path: Path = README_PATH,
    chart_path: Path = CHART_PATH,
) -> bool:
    """Top-level entrypoint `aq_cli.py::cmd_backtest` calls after a
    successful `lean backtest .` run. Callers should still wrap this in a
    try/except - a report-generation bug must never fail the backtest
    command itself."""
    result_json_path = find_latest_backtest_result_json(backtests_dir)
    if result_json_path is None:
        return False
    summary = load_backtest_summary(result_json_path)
    generate_equity_chart(summary, chart_path)
    return update_readme_backtest_section(summary, readme_path, chart_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate README.md's Backtest Results section from the latest Lean backtest run."
    )
    parser.add_argument("--backtests-dir", type=Path, default=BACKTESTS_DIR)
    parser.add_argument("--readme", type=Path, default=README_PATH)
    parser.add_argument("--chart-path", type=Path, default=CHART_PATH)
    args = parser.parse_args()

    updated = update_readme_from_latest_backtest(args.backtests_dir, args.readme, args.chart_path)
    if updated:
        print(f"Updated {args.readme} with the latest backtest results.")
        return 0
    print("No backtest results found (or README markers missing) - nothing updated.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
