"""Tests for evaluation/readme_statistics.py (V6.3.0): the Backtest Statistics blocks render from the saved JSON, degrade
to a not-run line without it, and every statistic Lean prints has one home among the new sections."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.readme_statistics import LEAN_STAT_SECTION, MARKERS, SECTIONS, _format, build_backtest_statistics_blocks

ROOT = Path(__file__).resolve().parents[1]

# The 27 keys of Lean's `statistics` block (QuantConnect Lean, every result JSON since the V5 runs).
LEAN_STATISTICS_KEYS = [
    "Total Orders", "Average Win", "Average Loss", "Compounding Annual Return", "Drawdown", "Expectancy", "Start Equity",
    "End Equity", "Net Profit", "Sharpe Ratio", "Sortino Ratio", "Probabilistic Sharpe Ratio", "Loss Rate", "Win Rate",
    "Profit-Loss Ratio", "Alpha", "Beta", "Annual Standard Deviation", "Annual Variance", "Information Ratio",
    "Tracking Error", "Treynor Ratio", "Total Fees", "Estimated Strategy Capacity", "Lowest Capacity Asset",
    "Portfolio Turnover", "Drawdown Recovery",
]


def _stats() -> dict:
    row = {"metric": "PnL", "portfolio": 16847.7, "strategy": 6148.4, "format": "usd_signed", "reason": None}
    return {
        "run": "2026-10-17_21-39-55", "status": "OK", "computed_at": "2026-10-18 12:00 UTC",
        "sections": {
            "general": [{"metric": "Average AUM", "portfolio": 107181.0, "strategy": None, "format": "usd", "reason": None}],
            "performance": [row],
            "runs": [{"metric": "HHI of positive returns", "portfolio": 0.0033, "strategy": 0.0038, "format": "num3", "reason": None}],
            "shortfall": [{"metric": "Broker fees per turnover", "portfolio": 4.2, "strategy": 7.9, "format": "bps", "reason": "note"}],
            "efficiency": [{"metric": "Deflated Sharpe ratio", "portfolio": None, "strategy": None, "format": "pct", "reason": "fewer than 2 registered trials"}],
            "classification": [{"source": "Lean book calls", "n": 430, "accuracy": 0.514, "precision": 0.565, "recall": 0.51,
                                "f1": 0.537, "neg_log_loss": None, "reason": "no probability is logged per book call"}],
            "attribution": {"classes": [{"class": "equity", "net_pnl": 6348.5, "annual_return_on_aum": 0.018,
                                         "annual_volatility": 0.032, "sharpe": 0.56, "max_drawdown_on_aum": 0.07,
                                         "risk_share": 0.99, "fees": 960.2}],
                            "unattributed_pnl": 0.0, "components": [{"component": "main_book", "net_pnl": 1039.1, "fees": 179.6, "fills": 178}]},
        },
    }


def test_every_lean_statistic_has_a_section():
    assert set(LEAN_STATISTICS_KEYS) <= set(LEAN_STAT_SECTION)
    assert set(LEAN_STAT_SECTION.values()) <= set(SECTIONS)


def test_blocks_render_tables_with_a_strategy_column_and_footer(tmp_path):
    (tmp_path / "backtest_statistics.json").write_text(json.dumps(_stats()), encoding="utf-8")
    blocks = build_backtest_statistics_blocks(tmp_path)
    assert set(blocks) == set(SECTIONS)
    assert "| Metric | Portfolio | Strategy |" in blocks["performance"]
    assert "| PnL | +$16,848 | +$6,148 |" in blocks["performance"]
    assert "| Metric | Portfolio |" in blocks["general"] and "Strategy" not in blocks["general"].splitlines()[0]
    assert blocks["shortfall"].splitlines()[0] == "| Metric | Portfolio | Strategy | Note |"
    assert "n/a" in blocks["efficiency"] and "fewer than 2 registered trials" in blocks["efficiency"]
    assert "n/a (no probability is logged per book call)" in blocks["classification"]
    assert "| equity | +$6,348 |" in blocks["attribution"] and "| main_book |" in blocks["attribution"]
    for body in blocks.values():
        assert "2026-10-17_21-39-55" in body and "2026-10-18 12:00 UTC" in body


def test_blocks_degrade_without_the_json(tmp_path):
    blocks = build_backtest_statistics_blocks(tmp_path)
    assert all("aq evaluate --backtest-stats" in body for body in blocks.values())


def test_number_formats():
    assert _format(None, "pct") == "n/a"
    assert _format(0.04896, "pct_signed") == "+4.90%"
    assert _format(-3135.6, "usd_signed") == "-$3,136"
    assert _format(-2.82, "bps") == "-2.8 bps"
    assert _format(8.1677, "x") == "8.17x"
    assert _format(4.257, "pct_raw") == "4.257%"
    assert _format("496.04:00:00", "text") == "496.04:00:00"


def test_readme_carries_every_marker_once():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for start, end in MARKERS.values():
        assert text.count(start) == 1 and text.count(end) == 1
