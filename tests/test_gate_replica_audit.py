"""evaluation/gate_replica_audit.py (V6.4.4, R-CAL5): trade classification on both sides and the profile comparison."""

from __future__ import annotations

from dataclasses import dataclass

from evaluation.gate_replica_audit import compare_profiles, lean_trades, offline_trades, trade_profile


@dataclass(frozen=True)
class _Fill:
    date: str
    ticker: str
    quantity: float


def test_lean_fills_aggregate_per_day_and_classify_against_the_position():
    fills = [_Fill("2024-01-02", "aapl", 10), _Fill("2024-01-02", "AAPL", 5), _Fill("2024-01-05", "AAPL", 3),
             _Fill("2024-01-08", "AAPL", -18), _Fill("2024-01-09", "AAPL", -5), _Fill("2024-01-10", "AAPL", 2),
             _Fill("2024-01-10", "BIL", 100)]
    trades = lean_trades(fills, {"AAPL"})
    assert [(t["date"], t["kind"]) for t in trades] == [
        ("2024-01-02", "entry"), ("2024-01-05", "resize"), ("2024-01-08", "exit"), ("2024-01-09", "entry"),
        ("2024-01-10", "resize")]


def test_offline_weights_classify_entries_exits_flips_and_resizes():
    dates = ["d1", "d2", "d3", "d4"]
    weights = [{"A": 0.1}, {"A": 0.2, "B": -0.1}, {"A": -0.1, "B": -0.1}, {}]
    kinds = [(t["date"], t["ticker"], t["kind"]) for t in offline_trades(dates, weights)]
    assert kinds == [("d1", "A", "entry"), ("d2", "A", "resize"), ("d2", "B", "entry"), ("d3", "A", "flip"),
                     ("d4", "A", "exit"), ("d4", "B", "exit")]


def test_profile_counts_a_next_open_fill_as_on_the_rebalance_with_a_lag():
    sessions = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    trades = [{"date": "2024-01-03", "ticker": "A", "kind": "entry"}, {"date": "2024-01-05", "ticker": "A", "kind": "exit"}]
    strict = trade_profile(trades, ["2024-01-02"], sessions)
    lagged = trade_profile(trades, ["2024-01-02"], sessions, lag_sessions=1)
    assert strict["off_rebalance"]["entry"] == 1 and lagged["off_rebalance"]["entry"] == 0
    assert lagged["off_rebalance"]["exit"] == 1 and lagged["median_sessions_between_trades"] == 2


def test_compare_ranks_kinds_by_count_gap():
    lean = {"counts": {"entry": 10, "exit": 10, "flip": 0, "resize": 1}, "off_rebalance": {"entry": 5, "exit": 4, "flip": 0, "resize": 1},
            "median_sessions_between_trades": 30, "share_within_5_sessions": 0.1}
    offline = {"counts": {"entry": 8, "exit": 9, "flip": 0, "resize": 20}, "off_rebalance": {"entry": 1, "exit": 4, "flip": 0, "resize": 15},
               "median_sessions_between_trades": 20, "share_within_5_sessions": 0.2}
    out = compare_profiles(lean, offline)
    assert out["ranked"][0] == "counts.resize" and out["rows"]["counts.resize"]["abs_gap"] == 19
    assert abs(sum(row["gap_share"] for row in out["rows"].values()) - 1.0) < 1e-12
