"""README "Backtest Statistics" blocks (V6.3.0), rendered from `ml/evaluation/backtest_statistics.json`
(`evaluation/backtest_statistics.py`, written by `aq evaluate --backtest-stats` / `--lean-report` and after `aq backtest`).

One compact table per section, a "Strategy" column next to the portfolio (the run without its T-bill sweep), and one
footer line naming the run. `generate_evaluation_report.update_readme_evaluation_sections` writes every block, so any
`aq evaluate` re-renders them from the saved JSON."""

from __future__ import annotations

import json
from pathlib import Path

SECTIONS = ("general", "performance", "runs", "shortfall", "efficiency", "classification", "attribution", "benchmarks")
MARKERS = {
    section: (f"<!-- AQ:BTSTATS_{section.upper()}_START -->", f"<!-- AQ:BTSTATS_{section.upper()}_END -->")
    for section in SECTIONS
}
STATISTICS_FILE = "backtest_statistics.json"
ALPHA_FILE = "alpha_proof.json"
PIN_FILE = "readme_lean_run.json"
ALPHA_MARKERS = ("<!-- AQ:ALPHA_START -->", "<!-- AQ:ALPHA_END -->")
STATUS_MARKERS = ("<!-- AQ:STATUS_START -->", "<!-- AQ:STATUS_END -->")
PERIOD_LABELS = {"full": "Whole run", "backtest": "First half", "holdout": "Second half"}

# Every Lean `statistics` key has one home in the new sections (tests/test_readme_statistics.py checks a real run).
LEAN_STAT_SECTION = {
    "Start Equity": "general", "End Equity": "general", "Total Orders": "general", "Estimated Strategy Capacity": "general",
    "Lowest Capacity Asset": "general", "Portfolio Turnover": "general",
    "Net Profit": "performance", "Compounding Annual Return": "performance", "Win Rate": "performance",
    "Loss Rate": "performance", "Average Win": "performance", "Average Loss": "performance",
    "Profit-Loss Ratio": "performance", "Expectancy": "performance",
    "Drawdown": "runs", "Drawdown Recovery": "runs",
    "Total Fees": "shortfall",
    "Sharpe Ratio": "efficiency", "Sortino Ratio": "efficiency", "Probabilistic Sharpe Ratio": "efficiency",
    "Information Ratio": "efficiency", "Tracking Error": "efficiency", "Treynor Ratio": "efficiency",
    "Alpha": "efficiency", "Beta": "efficiency", "Annual Standard Deviation": "efficiency", "Annual Variance": "efficiency",
}

_NOT_RUN = "_Not computed yet: `aq evaluate --backtest-stats` (runs after every `aq backtest`)._"


def _format(value, fmt: str) -> str:
    if value is None:
        return "n/a"
    if fmt == "text":
        return str(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if fmt == "usd":
        return f"${number:,.0f}"
    if fmt == "usd_signed":
        return f"{'+' if number >= 0 else '-'}${abs(number):,.0f}"
    if fmt == "pct":
        return f"{number:.2%}"
    if fmt == "pct_signed":
        return f"{number:+.2%}"
    if fmt == "pct_raw":
        return f"{number:.3f}%"
    if fmt == "bps":
        return f"{number:+.1f} bps" if number < 0 else f"{number:.1f} bps"
    if fmt == "x":
        return f"{number:.2f}x"
    if fmt == "int":
        return f"{number:,.0f}"
    decimals = {"num1": 1, "num2": 2, "num3": 3, "num4": 4}.get(fmt, 3)
    return f"{number:.{decimals}f}"


def _footer(stats: dict) -> str:
    return f"_Run `{stats.get('run', 'n/a')}` · computed {stats.get('computed_at', 'n/a')}_"


def _metric_table(rows: list[dict], stats: dict) -> str:
    has_strategy = any(row.get("strategy") is not None for row in rows)
    has_note = any(row.get("reason") for row in rows)
    header = ["Metric", "Portfolio"] + (["Strategy"] if has_strategy else []) + (["Note"] if has_note else [])
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for row in rows:
        portfolio = row.get("portfolio")
        # a bet-level metric exists for the strategy only (buying T-bills is not a bet)
        portfolio_cell = "—" if portfolio is None and row.get("strategy") is not None else _format(portfolio, row.get("format", "num"))
        cells = [row["metric"], portfolio_cell]
        if has_strategy:
            strategy = row.get("strategy")
            cells.append(_format(strategy, row.get("format", "num")) if strategy is not None else "")
        if has_note:
            cells.append(row.get("reason") or "")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines + ["", _footer(stats)])


def _classification_table(rows: list[dict], stats: dict) -> str:
    lines = ["| Source | Calls | Accuracy | Precision | Recall | F1 | Neg. log-loss |", "|---|---|---|---|---|---|---|"]
    for row in rows:
        loss = row.get("neg_log_loss")
        lines.append(
            f"| {row['source']} | {row.get('n', 0):,} | {_format(row.get('accuracy'), 'pct')} | {_format(row.get('precision'), 'pct')} | "
            f"{_format(row.get('recall'), 'pct')} | {_format(row.get('f1'), 'num3')} | "
            f"{_format(loss, 'num3') if loss is not None else 'n/a (' + (row.get('reason') or 'no probabilities') + ')'} |"
        )
    if not any(row["source"].startswith("Offline") for row in rows):
        lines += ["", "_Offline rows appear after `aq evaluate --classification` (part of `--all`)._"]
    return "\n".join(lines + ["", _footer(stats)])


def _attribution_table(attribution: dict, stats: dict) -> str:
    lines = [
        "| Class | Net PnL | Return on AUM (annual) | Volatility (annual) | Sharpe | Max drawdown (on AUM) | Risk share | Fees |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in attribution.get("classes", []):
        lines.append(
            f"| {row['class']} | {_format(row.get('net_pnl'), 'usd_signed')} | {_format(row.get('annual_return_on_aum'), 'pct_signed')} | "
            f"{_format(row.get('annual_volatility'), 'pct')} | {_format(row.get('sharpe'), 'num2')} | "
            f"{_format(row.get('max_drawdown_on_aum'), 'pct')} | {_format(row.get('risk_share'), 'pct')} | {_format(row.get('fees'), 'usd')} |"
        )
    unattributed = attribution.get("unattributed_pnl")
    if unattributed is not None and abs(float(unattributed)) >= 1.0:
        lines.append(f"| unattributed (Lean minus rebuilt) | {_format(unattributed, 'usd_signed')} | | | | | | |")
    components = attribution.get("components") or []
    if components:
        lines += ["", "| Component | Net PnL | Fees | Fills |", "|---|---|---|---|"]
        for row in components:
            lines.append(f"| {row['component']} | {_format(row.get('net_pnl'), 'usd_signed')} | {_format(row.get('fees'), 'usd')} | {row.get('fills', 0)} |")
    return "\n".join(lines + ["", _footer(stats)])


def _benchmark_table(rows: list[dict], stats: dict) -> str:
    lines = ["| Series | Total return | Annual return | Volatility | Sharpe | Max drawdown |", "|---|---|---|---|---|---|"]
    for row in rows:
        lines.append(
            f"| {row['series']} | {_format(row.get('total_return'), 'pct_signed')} | {_format(row.get('annual_return'), 'pct_signed')} | "
            f"{_format(row.get('volatility'), 'pct')} | {_format(row.get('sharpe'), 'num2')} | {_format(row.get('max_drawdown'), 'pct')} |"
        )
    return "\n".join(lines + ["", _footer(stats)[:-1] + " · same sessions to the last equity close, no risk-free rate_"])


def _load(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _alpha_rows(report: dict, periods: dict[str, str]) -> list[str]:
    rows = []
    for key, label in periods.items():
        part = (report.get("periods") or {}).get(key) or {}
        if not part.get("n"):
            continue
        ci = part.get("sharpe_ci95") or [None, None]
        alpha = part.get("alpha") or {}
        rows.append(
            f"| {label} | {part.get('start', '?')} to {part.get('end', '?')} | {_format(part.get('sharpe'), 'num2')} | "
            f"{_format(ci[0], 'num2')} to {_format(ci[1], 'num2')} | {_format(alpha.get('alpha_annual'), 'pct_signed')} | "
            f"{_format(alpha.get('t_hac'), 'num2')} | {_format(part.get('dsr'), 'pct')} |"
        )
    return rows


def build_alpha_block(evaluation_dir: Path) -> str:
    """The strategy without its T-bill sweep, per period, against SPY / AGG / BTC; a pinned long run adds one row."""
    evaluation_dir = Path(evaluation_dir)
    report = _load(evaluation_dir / ALPHA_FILE)
    if not report or not report.get("periods"):
        return "_Not computed yet: `aq evaluate --alpha-proof` (part of `--lean-report`)._"
    rows = _alpha_rows(report, PERIOD_LABELS)
    long_run = (_load(evaluation_dir / PIN_FILE) or {}).get("long_run")
    long_report = _load(evaluation_dir / f"alpha_proof_{long_run}.json") if long_run else None
    if long_report:
        rows += _alpha_rows(long_report, {"full": "Long run, same rule"})
    verdict = report.get("r_alpha1") or {}
    reasons = "; ".join(verdict.get("failed") or [])
    trials = ((report.get("periods") or {}).get("full") or {}).get("dsr_trials", "n/a")
    aligned = (((report.get("periods") or {}).get("full") or {}).get("alpha_session_aligned") or {}).get("t_hac")
    note = [f"_With SPY and AGG read a session late, as the crypto series is, the full-window alpha t is {_format(aligned, 'num2')} (#330). R-ALPHA1 reads the figure in the table._", ""] if aligned is not None else []
    return "\n".join([
        "| Period | Dates | Sharpe | 95% interval | Alpha per year | Alpha t | Deflated Sharpe |", "|---|---|---|---|---|---|---|", *rows, "",
        f"**Proof of alpha (R-ALPHA1): {verdict.get('verdict', 'n/a')}**" + (f" ({reasons})." if reasons else "."),
        "", *note,
        f"_Run `{report.get('run', 'n/a')}` · computed {report.get('computed_at', 'n/a')} · alpha against "
        f"{' / '.join(report.get('benchmarks') or [])} with a Newey-West t · deflated over {trials} ledger trials_",
    ])


def build_status_block(evaluation_dir: Path) -> str:
    """The headline table at the top of the README."""
    evaluation_dir = Path(evaluation_dir)
    stats = _load(evaluation_dir / STATISTICS_FILE)
    if not stats or stats.get("status") != "OK":
        return _NOT_RUN
    sections = stats.get("sections", {})
    rows = {row["metric"]: row for name in ("efficiency", "performance", "runs") for row in sections.get(name) or []}
    full = ((_load(evaluation_dir / ALPHA_FILE) or {}).get("periods") or {}).get("full") or {}
    general = {row["metric"]: row for row in sections.get("general") or []}
    time_range = (general.get("Time range") or {}).get("portfolio", "n/a")

    def value(metric: str, column: str, fmt: str) -> str:
        return _format((rows.get(metric) or {}).get(column), fmt)

    return "\n".join([
        "| Lean Sharpe | Net profit | Max drawdown | Sharpe without T-bill carry | Alpha t | Deflated Sharpe |", "|---|---|---|---|---|---|",
        f"| {value('Annualized Sharpe ratio (Lean: risk-free rate subtracted)', 'portfolio', 'num2')} | {value('Net profit (Lean)', 'portfolio', 'pct_raw')} | "
        f"{value('Maximum drawdown', 'portfolio', 'pct')} | {value('Annualized Sharpe ratio (no risk-free rate)', 'strategy', 'num2')} | "
        f"{_format((full.get('alpha') or {}).get('t_hac'), 'num2')} | {_format(full.get('dsr'), 'pct')} |",
        "",
        f"_Lean run `{stats.get('run', 'n/a')}`, {time_range}, computed {stats.get('computed_at', 'n/a')}. Details: [Backtest Statistics](#backtest-statistics)._",
    ])


def build_backtest_statistics_blocks(evaluation_dir: Path) -> dict[str, str]:
    """{section: markdown body} for every Backtest Statistics block; each degrades to a not-run line without the JSON."""
    path = Path(evaluation_dir) / STATISTICS_FILE
    try:
        stats = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, ValueError):
        stats = None
    if not stats or stats.get("status") != "OK":
        return {section: _NOT_RUN for section in SECTIONS}
    sections = stats.get("sections", {})
    blocks = {}
    for section in SECTIONS:
        content = sections.get(section)
        if content is None:
            blocks[section] = _NOT_RUN
        elif section == "classification":
            blocks[section] = _classification_table(content, stats)
        elif section == "attribution":
            blocks[section] = _attribution_table(content, stats)
        elif section == "benchmarks":
            blocks[section] = _benchmark_table(content, stats)
        else:
            blocks[section] = _metric_table(content, stats)
    return blocks
