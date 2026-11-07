"""Tests for evaluation/readme_statistics.py (V6.3.0): the Backtest Statistics blocks render from the saved JSON, degrade
to a not-run line without it, and every statistic Lean prints has one home among the new sections."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.readme_statistics import (
    ALPHA_MARKERS,
    LEAN_STAT_SECTION,
    MARKERS,
    SECTIONS,
    STATUS_MARKERS,
    _format,
    build_alpha_block,
    build_backtest_statistics_blocks,
    build_status_block,
)

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
            "benchmarks": [{"series": "SPY", "total_return": 0.1, "annual_return": 0.1, "volatility": 0.15, "sharpe": 0.8, "max_drawdown": 0.2}],
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


def test_every_marker_appears_once_across_the_readme_and_the_research_archive():
    text = (ROOT / "README.md").read_text(encoding="utf-8") + (ROOT / "development" / "research_results.md").read_text(encoding="utf-8")
    for start, end in (*MARKERS.values(), ALPHA_MARKERS, STATUS_MARKERS):
        assert text.count(start) == 1 and text.count(end) == 1


def test_the_readme_shows_only_the_shipped_book():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for retired in ("AQ:EVAL_START", "AQ:WALKFORWARD_START", "AQ:ASLIVE_START", "AQ:RESEARCH_START", "AQ:BTSTATS_CLASSIFICATION_START", "AQ:BACKTEST_HISTORY_START"):
        assert retired not in text


def _alpha() -> dict:
    period = {"n": 700, "start": "2023-07-02", "end": "2025-06-30", "sharpe": 1.15, "sharpe_ci95": [-0.48, 2.73], "dsr": 0.23, "dsr_trials": 192,
              "alpha": {"alpha_annual": -0.007, "t_hac": -0.18}}
    return {"run": "run_a", "computed_at": "2026-11-07 10:00 UTC", "benchmarks": ["SPY", "BTCUSD"],
            "periods": {"full": period, "backtest": period, "holdout": {"n": 0}},
            "r_alpha1": {"verdict": "not demonstrated", "failed": ["deflated Sharpe < 0.95"]}}


def test_alpha_block_renders_periods_and_the_verdict_and_skips_an_empty_period(tmp_path):
    (tmp_path / "alpha_proof.json").write_text(json.dumps(_alpha()), encoding="utf-8")
    block = build_alpha_block(tmp_path)
    assert "| Whole run | 2023-07-02 to 2025-06-30 | 1.15 | -0.48 to 2.73 | -0.70% | -0.18 | 23.00% |" in block
    assert "Second half" not in block and "not demonstrated" in block and "deflated Sharpe < 0.95" in block and "192 ledger trials" in block


def test_alpha_block_adds_the_pinned_long_run_only_when_its_report_exists(tmp_path):
    (tmp_path / "alpha_proof.json").write_text(json.dumps(_alpha()), encoding="utf-8")
    (tmp_path / "readme_lean_run.json").write_text(json.dumps({"run": "run_a", "long_run": "run_long"}), encoding="utf-8")
    assert "Long run" not in build_alpha_block(tmp_path)
    (tmp_path / "alpha_proof_run_long.json").write_text(json.dumps(_alpha()), encoding="utf-8")
    assert "Long run, same rule" in build_alpha_block(tmp_path)


def test_status_and_alpha_blocks_degrade_without_their_files(tmp_path):
    assert "aq evaluate --alpha-proof" in build_alpha_block(tmp_path)
    assert "aq evaluate --backtest-stats" in build_status_block(tmp_path)


def test_status_block_reads_the_headline_from_the_statistics_and_the_alpha_report(tmp_path):
    stats = {"run": "run_a", "status": "OK", "computed_at": "now", "sections": {
        "general": [{"metric": "Time range", "portfolio": "2023-07-01 to 2026-11-02"}],
        "efficiency": [{"metric": "Annualized Sharpe ratio (Lean: risk-free rate subtracted)", "portfolio": 0.633},
                       {"metric": "Annualized Sharpe ratio (no risk-free rate)", "strategy": 0.72}],
        "performance": [{"metric": "Net profit (Lean)", "portfolio": 33.85}],
        "runs": [{"metric": "Maximum drawdown", "portfolio": 0.0783}],
    }}
    (tmp_path / "backtest_statistics.json").write_text(json.dumps(stats), encoding="utf-8")
    (tmp_path / "alpha_proof.json").write_text(json.dumps(_alpha()), encoding="utf-8")
    block = build_status_block(tmp_path)
    assert "| 0.63 | 33.850% | 7.83% | 0.72 | -0.18 | 23.00% |" in block and "2023-07-01 to 2026-11-02" in block
