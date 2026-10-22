"""V6.4.0 (lead L12): the paper-period checklist, the reference bands and the band check."""

from __future__ import annotations

import pytest

from evaluation.paper_protocol import (
    METRICS, MIN_REBALANCES, WARMUP_REASON, band_check, daily_table, live_rebalances, metrics_for_window, reference_bands,
)

DAYS = [f"2024-02-{day:02d}" for day in range(1, 21)]


def _entry(pnl=0.0, fee=0.0, position=0.0, fills=0, notional=0.0):
    return {"pnl": pnl, "fee": fee, "position": position, "fills": fills, "limit_fills": 0, "notional": notional}


def _table():
    ticker_pnl = {}
    for index, day in enumerate(DAYS):
        entries = {"AAA": _entry(pnl=2.0 if index % 2 == 0 else -1.0, fee=0.1 if index % 5 == 0 else 0.0, position=10.0,
                                 fills=1 if index % 5 == 0 else 0, notional=1000.0 if index % 5 == 0 else 0.0),
                   "BIL": _entry(pnl=0.5, position=20.0)}
        ticker_pnl[day] = entries
    nav = {day: 10_000.0 for day in DAYS}
    closes = {"AAA": {day: 100.0 for day in DAYS}, "BIL": {day: 50.0 for day in DAYS}}
    return daily_table(ticker_pnl, nav, closes, {t: sorted(s) for t, s in closes.items()}, {"BIL"})


def _rebalances():
    return [{"date": DAYS[index], "allocations": {"AAA": {"role": "long"}} if index not in (5, 15) else {},
             "gate_veto_reason": None if index not in (5, 15) else "rolling_ic_below_floor"} for index in (0, 5, 10, 15)]


def test_daily_table_separates_the_sweep_and_marks_exposure():
    table = _table()
    first = table[DAYS[0]]
    assert first["strategy_pnl"] == pytest.approx((2.0 - 0.1) / 10_000.0)
    assert first["sweep_pnl"] == pytest.approx(0.5 / 10_000.0)
    assert first["exposure"] == pytest.approx(10 * 100.0 / 10_000.0)  # the sweep's 1,000 of BIL is not strategy exposure
    assert first["fills"] == 1 and first["notional"] == 1000.0


def test_metrics_for_window_counts_vetoes_and_ignores_warmup_records():
    history = _rebalances() + [{"date": "2024-01-01", "allocations": {}, "gate_veto_reason": WARMUP_REASON}]
    rebalances = live_rebalances(history)
    assert len(rebalances) == 4
    metrics = metrics_for_window(_table(), rebalances, {DAYS[0]: [1.0, 3.0], DAYS[5]: [5.0]})
    assert metrics["rebalances"] == 4 and metrics["trading_days"] == 20
    assert metrics["veto_rate"] == pytest.approx(0.5)
    assert metrics["fills_per_rebalance"] == pytest.approx(1.0)
    assert metrics["median_slippage_bps"] == pytest.approx(3.0)
    assert metrics["fee_bps_per_turnover"] == pytest.approx(4 * 0.1 / 4000.0 * 1e4)
    assert metrics["daily_hit_ratio"] == pytest.approx(0.5)
    assert set(METRICS) <= set(metrics)


def test_a_window_without_days_has_no_metrics():
    metrics = metrics_for_window(_table(), _rebalances(), {}, "2025-01-01", None)
    assert metrics["trading_days"] == 0 and metrics["veto_rate"] is None


def test_reference_bands_cover_every_contiguous_window():
    rebalances = _rebalances()
    bands = reference_bands(_table(), rebalances, {}, window_rebalances=2)
    assert bands["windows"] == 3 and bands["window_rebalances"] == 2
    veto = bands["bands"]["veto_rate"]
    assert veto["low"] <= 0.5 <= veto["high"]


def test_band_check_flags_outside_metrics_and_the_minimum():
    bands = {"bands": {"veto_rate": {"low": 0.2, "high": 0.6, "windows": 5},
                       "strategy_gross_exposure": {"low": 0.0, "high": 0.2, "windows": 5}}}
    verdict = band_check({"veto_rate": 0.9, "strategy_gross_exposure": 0.1, "rebalances": 4, "trading_days": 30}, bands)
    assert verdict["inside"] is False and verdict["outside"] == ["veto_rate"]
    assert verdict["minimum_met"] is False
    unjudged = next(row for row in verdict["rows"] if row["metric"] == "fills_per_rebalance")
    assert unjudged["inside"] is None
    ok = band_check({"veto_rate": 0.3, "strategy_gross_exposure": 0.1, "rebalances": MIN_REBALANCES, "trading_days": 120}, bands)
    assert ok["inside"] is True and ok["minimum_met"] is True


def test_a_metric_the_run_could_not_compute_is_outside_its_band():
    bands = {"bands": {"veto_rate": {"low": 0.0, "high": 1.0, "windows": 3}}}
    assert band_check({"veto_rate": None, "rebalances": 10, "trading_days": 200}, bands)["outside"] == ["veto_rate"]
