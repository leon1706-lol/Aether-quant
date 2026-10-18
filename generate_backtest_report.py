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
  benchmark series, time-aligned with "Strategy Equity" in the same file.
  Since V6.0.0 `main.py` points it at the daily SPY subscription
  (`runtime.benchmark_ticker`); before that Lean used its internal hourly SPY
  feed, whose local zip ends 2021-03-31, so every later run carries a constant
  benchmark. For such a run the chart redraws SPY from the daily zip.

Usage:
    python generate_backtest_report.py [--backtests-dir backtests] [--backtest-dir backtests/<run>] [--readme README.md]
        [--chart-path development/backtest_equity_chart.png]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT_DIR = Path(__file__).resolve().parent
BACKTESTS_DIR = ROOT_DIR / "backtests"
README_PATH = ROOT_DIR / "README.md"
CHART_PATH = ROOT_DIR / "development" / "backtest_equity_chart.png"
DAILY_SPY_ZIP = ROOT_DIR / "data" / "equity" / "usa" / "daily" / "spy.zip"
LEAN_EQUITY_PRICE_SCALE = 10_000.0
# Lean stamps a daily chart point at New York midnight; UTC-4 maps every point to its own session date.
_NEW_YORK_OFFSET = timedelta(hours=4)

_RESULT_JSON_PATTERN = re.compile(r"^\d+\.json$")
BACKTEST_MARKER_START = "<!-- AQ:BACKTEST_START -->"
BACKTEST_MARKER_END = "<!-- AQ:BACKTEST_END -->"
FULL_STATS_MARKER_START = "<!-- AQ:BACKTEST_FULL_STATS_START -->"
FULL_STATS_MARKER_END = "<!-- AQ:BACKTEST_FULL_STATS_END -->"

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
        # equal mtimes (folders created within one filesystem tick) fall back to the name, chronological for Lean's folders
        key=lambda d: (d.stat().st_mtime, d.name),
        reverse=True,
    )
    for run_dir in run_dirs:
        for candidate in sorted(run_dir.iterdir()):
            if candidate.is_file() and _RESULT_JSON_PATTERN.match(candidate.name):
                yield candidate
                break  # at most one result JSON per backtest folder


PIN_PATH = ROOT_DIR / "ml" / "evaluation" / "readme_lean_run.json"


def pinned_run_dir(backtests_dir: Path = BACKTESTS_DIR, pin_path: Path | None = None) -> Path | None:
    """The run folder the README's Lean blocks were pinned to with `--backtest-dir` (V6.1.0): the newest run is not always the
    shipped configuration's (a rejected-config run can come last), and every block that reads "the Lean run" must read the same
    one. None when nothing is pinned, the pin names a missing folder, or `backtests_dir` is not the default one."""
    pin_path = pin_path or PIN_PATH
    if backtests_dir != BACKTESTS_DIR or not pin_path.exists():
        return None
    try:
        name = json.loads(pin_path.read_text(encoding="utf-8")).get("run")
    except (OSError, ValueError):
        return None
    candidate = backtests_dir / str(name) if name else None
    return candidate if candidate is not None and candidate.is_dir() else None


def set_pinned_run(run_dir: Path | None, pin_path: Path | None = None) -> None:
    """Pin the README's Lean blocks to `run_dir`, or clear the pin (`None`: a fresh `aq backtest` unpins)."""
    pin_path = pin_path or PIN_PATH
    if run_dir is None:
        pin_path.unlink(missing_ok=True)
        return
    pin_path.parent.mkdir(parents=True, exist_ok=True)
    pin_path.write_text(json.dumps({"run": Path(run_dir).name}), encoding="utf-8")


def find_latest_backtest_result_json(backtests_dir: Path = BACKTESTS_DIR) -> Path | None:
    """Returns the newest backtest run's result JSON that actually contains
    both a populated Strategy Equity curve AND a populated statistics
    block - skips runs that errored out or were interrupted before
    finishing (Lean can write a result JSON with a partially-populated
    equity curve but an empty `statistics` dict if the process didn't reach
    the end of the run), so an incomplete run never clobbers the README
    with a chart but no Sharpe/drawdown/etc. numbers."""
    pinned = pinned_run_dir(backtests_dir)
    if pinned is not None:
        pinned_result = _result_json_in(pinned)
        if pinned_result is not None:
            return pinned_result
    for candidate in _iter_backtest_result_jsons(backtests_dir):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        values = data.get("charts", {}).get("Strategy Equity", {}).get("series", {}).get("Equity", {}).get("values", [])
        statistics = data.get("statistics", {})
        if values and statistics:
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
    # a benchmark function answers 0.0 until the first price exists: such leading points cannot be rebased
    benchmark_series = [(int(point[0]), float(point[-1])) for point in benchmark_points if float(point[-1]) > 0.0]

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


def benchmark_is_flat(series: list[tuple[int, float]]) -> bool:
    """True when Lean's benchmark carries at most one distinct value (a stale benchmark feed, see the module doc)."""
    return len({value for _, value in series}) <= 1


def read_daily_closes(zip_path: Path) -> list[tuple[str, float]]:
    """(YYYYMMDD, close) per bar of a Lean daily equity zip, prices unscaled."""
    with zipfile.ZipFile(zip_path) as archive:
        member = next(name for name in archive.namelist() if name.endswith(".csv"))
        rows = archive.read(member).decode("utf-8").splitlines()
    closes = []
    for row in rows:
        fields = row.split(",")
        if len(fields) >= 5:
            closes.append((fields[0][:8], float(fields[4]) / LEAN_EQUITY_PRICE_SCALE))
    return closes


def daily_benchmark_series(strategy_series: list[tuple[int, float]], closes: list[tuple[str, float]]) -> list[tuple[int, float]]:
    """The benchmark at each strategy timestamp: the last daily close on or before that point's session date."""
    import bisect

    dates = [day for day, _ in closes]
    series = []
    for timestamp, _ in strategy_series:
        session = (datetime.fromtimestamp(timestamp, tz=timezone.utc) - _NEW_YORK_OFFSET).strftime("%Y%m%d")
        index = bisect.bisect_right(dates, session) - 1
        if index >= 0:
            series.append((timestamp, closes[index][1]))
    return series


def with_daily_benchmark_fallback(summary: dict, spy_zip: Path | None = None) -> dict:
    """Replace a flat Lean benchmark with SPY from the daily zip; flags the summary so the chart says so."""
    spy_zip = spy_zip or DAILY_SPY_ZIP
    if not benchmark_is_flat(summary["benchmark_series"]) or not summary["strategy_series"] or not spy_zip.is_file():
        return summary
    rebuilt = daily_benchmark_series(summary["strategy_series"], read_daily_closes(spy_zip))
    if not rebuilt:
        return summary
    return dict(summary, benchmark_series=rebuilt, benchmark_source="daily_zip")


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
            label=(
                "S&P 500 (SPY, daily file; Lean's benchmark feed was stale)"
                if summary.get("benchmark_source") == "daily_zip"
                else "S&P 500 (SPY) Benchmark"
            ),
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


def _build_full_stats_markdown(summary: dict) -> str:
    """Every statistic Lean's own backtest result reports, not just the
    curated highlights in the compact table above it - Sharpe/Sortino/
    Probabilistic Sharpe, Alpha/Beta, Information/Treynor Ratio, fees,
    estimated strategy capacity, and everything else Lean computes."""
    statistics = summary["statistics"]
    if not statistics:
        return "_No statistics available in this backtest result._"

    lines = []
    if summary.get("benchmark_source") == "daily_zip":
        lines += [
            "_Lean's benchmark feed was stale for this run (a constant series), so its Alpha, Beta, Information Ratio, "
            "Tracking Error and Treynor Ratio are meaningless; the chart redraws SPY from the daily file._",
            "",
        ]
    lines += ["| Metric | Value |", "|---|---|"]
    for key, value in statistics.items():
        lines.append(f"| {key} | {value} |")
    return "\n".join(lines)


def _replace_between_markers(text: str, start_marker: str, end_marker: str, body: str) -> str | None:
    """Shared atomic marker-replace helper. Returns the updated text, or
    None if the markers aren't present or nothing changed."""
    if start_marker not in text or end_marker not in text:
        return None
    pattern = re.compile(re.escape(start_marker) + r".*?" + re.escape(end_marker), re.DOTALL)
    replacement = f"{start_marker}\n{body}\n{end_marker}"
    updated_text = pattern.sub(replacement, text, count=1)
    return updated_text if updated_text != text else None


def _atomic_write(path: Path, text: str) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


HISTORY_MARKER_START = "<!-- AQ:BACKTEST_HISTORY_START -->"
HISTORY_MARKER_END = "<!-- AQ:BACKTEST_HISTORY_END -->"
HISTORY_LIMIT = 10


def build_history_markdown(backtests_dir: Path = BACKTESTS_DIR, limit: int = HISTORY_LIMIT) -> str:
    """One row per finished Lean run, newest first: the README's main table shows only the latest run, so two runs on
    different windows (the backtest window, then backtest + holdout) would otherwise overwrite each other."""
    rows: list[str] = []
    for candidate in _iter_backtest_result_jsons(backtests_dir):
        if len(rows) >= limit:
            break
        try:
            summary = load_backtest_summary(candidate)
        except (OSError, ValueError, IndexError):
            continue
        statistics = summary["statistics"]
        if not summary["strategy_series"] or not statistics:
            continue
        start, end = summary["start_date"], summary["end_date"]
        window = f"{start.date().isoformat()} to {end.date().isoformat()}" if start and end else "unknown"
        rows.append(
            f"| `{candidate.parent.name}` | {window} | {statistics.get('Sharpe Ratio', 'n/a')} | "
            f"{statistics.get('Net Profit', 'n/a')} | {statistics.get('Drawdown', 'n/a')} | {statistics.get('Total Orders', 'n/a')} |"
        )
    if not rows:
        return "_No finished Lean run yet._"
    return "\n".join(["| Run | Window | Sharpe | Net profit | Drawdown | Orders |", "|---|---|---|---|---|---|", *rows])


def update_readme_backtest_section(
    summary: dict, readme_path: Path = README_PATH, chart_path: Path = CHART_PATH, history_markdown: str | None = None
) -> bool:
    """Atomically replaces the content between the AQ:BACKTEST markers in
    README.md with a fresh stats table + chart image reference, and the
    content between the AQ:BACKTEST_FULL_STATS markers with every statistic
    Lean's result reports. Returns False (never raises) if the README or
    its markers are missing - a report-generation bug must never break
    `aq backtest` itself."""
    if not readme_path.exists():
        return False
    text = readme_path.read_text(encoding="utf-8")

    try:
        chart_relative_path = chart_path.relative_to(readme_path.resolve().parent).as_posix()
    except ValueError:
        chart_relative_path = chart_path.as_posix()

    updated_text = _replace_between_markers(
        text, BACKTEST_MARKER_START, BACKTEST_MARKER_END, _build_stats_markdown(summary, chart_relative_path)
    )
    if updated_text is None:
        return False
    text = updated_text

    full_stats_text = _replace_between_markers(
        text, FULL_STATS_MARKER_START, FULL_STATS_MARKER_END, _build_full_stats_markdown(summary)
    )
    if full_stats_text is not None:
        text = full_stats_text

    if history_markdown is not None:
        history_text = _replace_between_markers(text, HISTORY_MARKER_START, HISTORY_MARKER_END, history_markdown)
        if history_text is not None:
            text = history_text

    _atomic_write(readme_path, text)
    return True


def _result_json_in(run_dir: Path) -> Path | None:
    return next((path for path in sorted(Path(run_dir).iterdir()) if _RESULT_JSON_PATTERN.match(path.name)), None)


def update_readme_from_latest_backtest(
    backtests_dir: Path = BACKTESTS_DIR,
    readme_path: Path = README_PATH,
    chart_path: Path = CHART_PATH,
    backtest_dir: Path | None = None,
) -> bool:
    """Top-level entrypoint `aq_cli.py::cmd_backtest` calls after a
    successful `lean backtest .` run. Callers should still wrap this in a
    try/except - a report-generation bug must never fail the backtest
    command itself."""
    if backtests_dir == BACKTESTS_DIR and readme_path == README_PATH:
        set_pinned_run(backtest_dir)  # an explicit run pins every Lean block to it; the default (a fresh run) unpins
    result_json_path = find_latest_backtest_result_json(backtests_dir) if backtest_dir is None else _result_json_in(backtest_dir)
    if result_json_path is None:
        return False
    summary = with_daily_benchmark_fallback(load_backtest_summary(result_json_path))
    generate_equity_chart(summary, chart_path)
    return update_readme_backtest_section(summary, readme_path, chart_path, build_history_markdown(backtests_dir))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate README.md's Backtest Results section from the latest Lean backtest run."
    )
    parser.add_argument("--backtests-dir", type=Path, default=BACKTESTS_DIR)
    parser.add_argument("--readme", type=Path, default=README_PATH)
    parser.add_argument("--chart-path", type=Path, default=CHART_PATH)
    parser.add_argument("--backtest-dir", type=Path, default=None, help="render this run instead of the newest one")
    args = parser.parse_args()

    updated = update_readme_from_latest_backtest(args.backtests_dir, args.readme, args.chart_path, args.backtest_dir)
    if updated:
        print(f"Updated {args.readme} with the latest backtest results.")
        return 0
    print("No backtest results found (or README markers missing) - nothing updated.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
