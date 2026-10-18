"""evaluation/lean_statistics.py (V6.2.0): Lean's Sharpe / Sortino / PSR reproduced from a result's equity curve."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone

import pytest

from evaluation.lean_statistics import (
    average_risk_free_rate,
    lean_statistics,
    load_backtest_series,
    load_interest_rate_changes,
    rate_on,
    statistics_table,
    with_extra_daily_returns,
)


def _rates(tmp_path):
    path = tmp_path / "interest-rate.csv"
    path.write_text("DATE,PCREDIT8\n2020-01-01,2.0\n2020-01-03,4.0\n", encoding="utf-8")
    return path


def test_the_rate_fills_forward_and_is_averaged_over_every_sample(tmp_path):
    changes = load_interest_rate_changes(_rates(tmp_path))
    assert changes == [(date(2020, 1, 1), 0.02), (date(2020, 1, 3), 0.04)]
    assert rate_on(date(2020, 1, 2), changes) == 0.02 and rate_on(date(2030, 1, 1), changes) == 0.04
    assert rate_on(date(2019, 1, 1), changes) == 0.02  # before the file: its first row, as Lean's provider
    # two samples on the first day weigh twice (Lean averages over the equity points, not the days)
    days = [date(2020, 1, 1), date(2020, 1, 1), date(2020, 1, 3)]
    assert average_risk_free_rate(days, changes) == pytest.approx((0.02 + 0.02 + 0.04) / 3)


def test_sharpe_is_compounded_mean_minus_rate_over_sample_std_times_root_n():
    performance = [0.001, -0.002, 0.003, 0.0, 0.002, -0.001]
    days = [date(2024, 1, 1)] * 3
    changes = [(date(2000, 1, 1), 0.03)]
    stats = lean_statistics(performance, days, trading_days_per_year=252, rate_changes=changes)
    mean = sum(performance) / 6
    sd = math.sqrt(sum((v - mean) ** 2 for v in performance) / 5 * 252)
    assert stats["annual_return"] == pytest.approx((1 + mean) ** 252 - 1)
    assert stats["sharpe_ratio"] == pytest.approx(((1 + mean) ** 252 - 1 - 0.03) / sd)
    downside = [-0.002, -0.001]
    dmean = sum(downside) / 2
    dsd = math.sqrt(sum((v - dmean) ** 2 for v in downside) / 1 * 252)
    assert stats["sortino_ratio"] == pytest.approx(((1 + mean) ** 252 - 1 - 0.03) / dsd)
    assert 0.0 <= stats["probabilistic_sharpe_ratio"] <= 1.0
    more = lean_statistics(performance, days, trading_days_per_year=365, rate_changes=changes)
    assert more["annual_standard_deviation"] == pytest.approx(sd * math.sqrt(365 / 252))


def test_a_flat_series_gives_zero_like_lean_and_extra_returns_add_by_date():
    flat = lean_statistics([0.0] * 10, [date(2024, 1, 1)], trading_days_per_year=252, rate_changes=[(date(2000, 1, 1), 0.05)])
    assert flat["sharpe_ratio"] == 0.0 and flat["sortino_ratio"] == 0.0
    days = [date(2024, 1, 1), date(2024, 1, 2)]
    assert with_extra_daily_returns([0.01, 0.02], days, {date(2024, 1, 2): 0.001}) == [0.01, pytest.approx(0.021)]


def test_a_result_file_drops_the_first_two_return_points_and_keeps_every_equity_sample(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    stamps = [(start + timedelta(days=i)).timestamp() for i in range(6)]
    result = {
        "charts": {"Strategy Equity": {"series": {
            "Return": {"values": [[s, v] for s, v in zip(stamps, [0.0, 0.5, 0.1, -0.2, 0.3, 0.1])]},
            "Equity": {"values": [[s, 1, 1, 1, 1] for s in stamps] + [[stamps[-1], 1, 1, 1, 1]]},
        }}},
        "algorithmConfiguration": {"tradingDaysPerYear": 365},
        "statistics": {"Sharpe Ratio": "1.0"},
    }
    path = tmp_path / "1.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    series = load_backtest_series(path)
    assert series["performance"] == pytest.approx([0.001, -0.002, 0.003, 0.001])
    assert len(series["equity_dates"]) == 7 and series["trading_days_per_year"] == 365
    table = statistics_table(path, {"file": _rates(tmp_path)}, (252,))
    assert table["lean_printed"]["Sharpe Ratio"] == "1.0" and "file/252" in table["replica"]
