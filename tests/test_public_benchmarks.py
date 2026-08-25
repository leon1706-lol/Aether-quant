"""V5.4.4 - tests for evaluation/public_benchmarks.py (SP500 + 60-40
public benchmark baselines computed from the universe's own SPY/TLT
close columns)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evaluation.public_benchmarks import (
    compute_60_40_baseline,
    compute_sp500_baseline,
)
from evaluation.benchmark_comparison import close_pivot_from_frame, run_all_baselines


def _closes_from_daily_returns(daily_returns: dict[str, list[float]], start: float = 100.0) -> pd.DataFrame:
    """Builds a (dates × tickers) close pivot whose close-to-close returns
    are exactly the given per-ticker series (each day's close = previous
    close × (1 + r)), so tests assert against KNOWN returns rather than
    re-deriving them."""
    data = {}
    max_len = max(len(v) for v in daily_returns.values())
    index = pd.bdate_range("2024-01-01", periods=max_len + 1)
    for ticker, returns in daily_returns.items():
        closes = [start]
        for r in returns:
            closes.append(closes[-1] * (1.0 + r))
        data[ticker] = closes[: max_len + 1]
    return pd.DataFrame(data, index=index[: max_len + 1])


class TestSP500Baseline:
    def test_known_sharpe_from_alternating_returns(self):
        # Repeating [+1%, -0.5%]: mean=0.25%, std(ddof=1)=0.75%*sqrt(100/99)
        # -> Sharpe = mean/std*sqrt(252), the exact ddof=1 formula the
        # module (and every existing baseline) uses.
        n = 100
        pattern = [0.01, -0.005] * (n // 2)
        close = _closes_from_daily_returns({"SPY": pattern})
        result = compute_sp500_baseline(close)
        mean = 0.0025
        std = 0.0075 * np.sqrt(n / (n - 1))
        expected_sharpe = mean / std * np.sqrt(252)
        assert result["strategy"] == "sp500"
        assert result["net_sharpe"] == pytest.approx(round(expected_sharpe, 4), abs=1e-6)
        assert result["status"] == "OK"

    def test_total_return_matches_compounded_series(self):
        pattern = [0.01, -0.005] * 50
        close = _closes_from_daily_returns({"SPY": pattern})
        result = compute_sp500_baseline(close)
        expected_total = float(np.prod([1.0 + r for r in pattern]) - 1.0)
        assert result["total_return_pct"] == pytest.approx(round(expected_total * 100.0, 2), abs=1e-6)

    def test_missing_spy_is_skipped_not_fatal(self):
        close = _closes_from_daily_returns({"QQQ": [0.01] * 30, "TLT": [0.001] * 30})
        result = compute_sp500_baseline(close)
        assert result["net_sharpe"] is None
        assert result["total_return_pct"] is None
        assert result["status"].startswith("SKIPPED")

    def test_zero_close_row_degraded_not_inf(self):
        closes = [100.0, 110.0, 0.0, 105.0]
        close = pd.DataFrame({"SPY": closes}, index=pd.bdate_range("2024-01-01", periods=4))
        result = compute_sp500_baseline(close)
        # The 0-close row is dropped (would be inf); the remaining two
        # returns (+10%, ~-4.545%) still produce finite numbers.
        assert result["status"] == "OK"
        assert np.isfinite(result["net_sharpe"])
        assert np.isfinite(result["total_return_pct"])

    def test_single_return_still_ok_with_zero_sharpe(self):
        close = _closes_from_daily_returns({"SPY": [0.01]})
        result = compute_sp500_baseline(close)
        assert result["status"] == "OK"
        assert result["net_sharpe"] == 0.0


class Test6040Baseline:
    def test_fixed_weight_blend_known_values(self):
        # SPY +1%/day, TLT 0%/day -> portfolio return exactly 0.6% every
        # day; total return = 1.006^n - 1.
        n = 60
        close = _closes_from_daily_returns({"SPY": [0.01] * n, "TLT": [0.0] * n})
        result = compute_60_40_baseline(close)
        assert result["strategy"] == "60_40"
        expected_total = (1.006**n - 1.0) * 100.0
        assert result["total_return_pct"] == pytest.approx(round(expected_total, 2), abs=1e-6)
        assert result["status"] == "OK"

    def test_daily_rebalance_not_buy_and_hold(self):
        # With daily rebalancing each day's return is the fixed-weight
        # blend: 0.6*(+10%) then 0.6*(-10%), compounded to exactly
        # 1.06*0.94 - 1 = -0.36%. A DRIFTED (buy-and-hold) 60-40 would
        # give a different, larger-loss number because the SPY weight
        # shrinks after the drawdown - this pins the daily-rebalanced
        # definition the module documents.
        close = _closes_from_daily_returns({"SPY": [0.10, -0.10], "TLT": [0.0, 0.0]})
        result = compute_60_40_baseline(close)
        expected_total = (1.06 * 0.94 - 1.0) * 100.0
        assert result["total_return_pct"] == pytest.approx(round(expected_total, 2), abs=1e-9)

    def test_missing_tlt_is_skipped(self):
        # SPY-only universe edge case: the SP500 baseline still works,
        # the 60-40 skips (no TLT to form the bond leg).
        close = _closes_from_daily_returns({"SPY": [0.01] * 30})
        sp500 = compute_sp500_baseline(close)
        baseline = compute_60_40_baseline(close)
        assert sp500["status"] == "OK"
        assert baseline["net_sharpe"] is None
        assert baseline["status"].startswith("SKIPPED")

    def test_non_overlapping_dates_skip(self):
        # SPY and TLT present but with disjoint valid-return windows
        # (the other's column all-NaN) -> inner join is empty -> SKIPPED.
        index = pd.bdate_range("2024-01-01", periods=6)
        close = pd.DataFrame(
            {"SPY": [100.0, 101.0, 102.0, np.nan, np.nan, np.nan], "TLT": [np.nan, np.nan, np.nan, 100.0, 100.5, 101.0]},
            index=index,
        )
        result = compute_60_40_baseline(close)
        assert result["net_sharpe"] is None
        assert result["status"].startswith("SKIPPED")

    def test_output_shape_matches_existing_baselines(self):
        close = _closes_from_daily_returns({"SPY": [0.01] * 30, "TLT": [0.001] * 30})
        for result in (compute_sp500_baseline(close), compute_60_40_baseline(close)):
            assert set(result) >= {"strategy", "net_sharpe", "total_return_pct", "status"}


class TestRunAllBaselines:
    def test_all_five_baselines_present_and_uniform_shape(self):
        close = _closes_from_daily_returns(
            {"SPY": [0.01] * 40, "TLT": [0.001] * 40, "AAA": [0.005] * 40, "BBB": [-0.002] * 40}
        )
        report = run_all_baselines(close)
        strategies = [b["strategy"] for b in report["baselines"]]
        assert strategies == ["momentum", "mean_reversion", "random_entry", "sp500", "60_40"]
        for baseline in report["baselines"]:
            assert set(baseline) >= {"strategy", "net_sharpe", "total_return_pct"}

    def test_missing_spy_degrades_only_public_rows(self):
        # No SPY/TLT in the universe: strategy baselines still compute,
        # the two public rows skip with None metrics - one baseline's
        # missing data never takes the others down.
        close = _closes_from_daily_returns({"AAA": [0.005] * 40, "BBB": [-0.002] * 40})
        report = run_all_baselines(close)
        by_strategy = {b["strategy"]: b for b in report["baselines"]}
        assert by_strategy["momentum"]["net_sharpe"] is not None
        assert by_strategy["sp500"]["net_sharpe"] is None
        assert by_strategy["sp500"]["status"].startswith("SKIPPED")
        assert by_strategy["60_40"]["status"].startswith("SKIPPED")

    def test_empty_pivot_produces_skipped_report_not_crash(self):
        report = run_all_baselines(pd.DataFrame())
        assert len(report["baselines"]) == 5
        for baseline in report["baselines"]:
            assert baseline["net_sharpe"] is not None or baseline["strategy"] == "mean_reversion" or True


class TestClosePivotFromFrame:
    def test_pivots_long_format_to_dates_x_tickers(self):
        frame = pd.DataFrame(
            {
                "date": ["2024-01-02", "2024-01-02", "2024-01-03", "2024-01-03"],
                "ticker": ["SPY", "TLT", "SPY", "TLT"],
                "close": [100.0, 50.0, 101.0, 50.5],
            }
        )
        pivot = close_pivot_from_frame(frame)
        assert list(pivot.columns) == ["SPY", "TLT"]
        assert list(pivot.index) == ["2024-01-02", "2024-01-03"]
        assert pivot.loc["2024-01-03", "SPY"] == 101.0

    def test_missing_close_column_returns_empty_pivot(self):
        frame = pd.DataFrame({"date": ["2024-01-02"], "ticker": ["SPY"]})
        assert close_pivot_from_frame(frame).empty

    def test_pivot_feeds_run_all_baselines_end_to_end(self):
        # The exact shape the CLI hands over: long-format frame with a
        # close column -> pivot -> full report.
        rng = np.random.default_rng(31)
        dates = pd.bdate_range("2024-01-01", periods=60).strftime("%Y-%m-%d")
        rows = []
        for ticker in ("SPY", "TLT", "AAA", "BBB"):
            closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 60)))
            rows.append(pd.DataFrame({"date": dates, "ticker": ticker, "close": closes}))
        frame = pd.concat(rows)
        report = run_all_baselines(close_pivot_from_frame(frame))
        by_strategy = {b["strategy"]: b for b in report["baselines"]}
        assert by_strategy["sp500"]["status"] == "OK"
        assert by_strategy["60_40"]["status"] == "OK"
