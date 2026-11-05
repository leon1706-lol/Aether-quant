"""portfolio/target_weights.py: file loading, decisions and order deltas of the target-weights path."""

import hashlib

import pytest

from portfolio.target_weights import (
    FLAT_TICKER,
    TargetWeightsConfig,
    equity_fee_usd,
    load_weight_file,
    rebalance_deltas,
    resolve_target_weights_config,
    slippage_bps_for,
    sweep_reserve,
    weights_at_tick,
    write_weight_file,
)

CONFIG = TargetWeightsConfig(enabled=True, min_weight_change=0.01, min_trade_usd=100.0, forex_min_trade_usd=5000.0)


def test_disabled_by_default():
    assert resolve_target_weights_config(None).enabled is False
    assert resolve_target_weights_config({}).enabled is False


def test_resolve_falls_back_on_bad_numbers():
    config = resolve_target_weights_config({"enabled": True, "min_weight_change": "nope", "borrow_bps": float("nan")})
    assert config.enabled is True
    assert config.min_weight_change == TargetWeightsConfig().min_weight_change
    assert config.borrow_bps == TargetWeightsConfig().borrow_bps


def test_resolve_merges_class_slippage_over_defaults():
    config = resolve_target_weights_config({"slippage_bps_by_class": {"equity": 9}})
    assert slippage_bps_for("equity", config) == 9.0
    assert slippage_bps_for("crypto", config) == 10.0
    assert slippage_bps_for("unknown", config) == 0.0


def test_weight_file_round_trip_and_hash(tmp_path):
    path = tmp_path / "w.csv"
    sha = write_weight_file({"2024-01-03": {"SPY": 0.25, "TLT": -0.125}, "2024-01-02": {"SPY": 0.5}}, path)

    assert sha == hashlib.sha256(path.read_bytes()).hexdigest()
    assert load_weight_file(path, sha) == {"2024-01-02": {"SPY": 0.5}, "2024-01-03": {"SPY": 0.25, "TLT": -0.125}}


def test_same_weights_write_the_same_bytes(tmp_path):
    first = write_weight_file({"2024-01-02": {"A": 0.1, "B": 0.2}}, tmp_path / "a.csv")
    second = write_weight_file({"2024-01-02": {"B": 0.2, "A": 0.1}}, tmp_path / "b.csv")
    assert first == second


def test_a_flat_decision_survives_the_file_and_is_not_no_decision(tmp_path):
    path = tmp_path / "w.csv"
    write_weight_file({"2024-01-02": {}}, path)
    weights = load_weight_file(path)

    assert FLAT_TICKER in weights["2024-01-02"]
    assert weights_at_tick(weights, "2024-01-02") == {}
    assert weights_at_tick(weights, "2024-01-03") is None


def test_load_rejects_another_file_than_the_frozen_one(tmp_path):
    path = tmp_path / "w.csv"
    write_weight_file({"2024-01-02": {"SPY": 0.5}}, path)
    with pytest.raises(ValueError, match="sha256"):
        load_weight_file(path, "0" * 64)


def test_load_rejects_non_finite_weights_and_wrong_columns(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("date,ticker,weight\n2024-01-02,SPY,nan\n")
    with pytest.raises(ValueError, match="non-finite"):
        load_weight_file(bad)
    columns = tmp_path / "columns.csv"
    columns.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError, match="columns"):
        load_weight_file(columns)


def test_weights_at_tick_accepts_a_longer_date_string():
    assert weights_at_tick({"2024-01-02": {"SPY": 0.5}}, "2024-01-02T16:00:00") == {"SPY": 0.5}


def test_deltas_size_to_the_target_weight():
    assert rebalance_deltas({"SPY": 0.0}, {"SPY": 100.0}, 100_000.0, {"SPY": 0.5}, CONFIG) == [("SPY", 500.0)]


def test_a_ticker_the_target_omits_is_closed_in_full():
    assert rebalance_deltas({"SPY": 123.0}, {"SPY": 100.0}, 100_000.0, {}, CONFIG) == [("SPY", -123.0)]


def test_a_change_below_the_deadband_is_left_alone():
    assert rebalance_deltas({"SPY": 500.0}, {"SPY": 100.0}, 100_000.0, {"SPY": 0.505}, CONFIG) == []


def test_a_trade_below_the_minimum_is_left_alone_with_a_higher_floor_for_forex():
    config = TargetWeightsConfig(enabled=True, min_weight_change=0.0, min_trade_usd=100.0, forex_min_trade_usd=5000.0)
    assert rebalance_deltas({"A": 0.0}, {"A": 10.0}, 100_000.0, {"A": 0.0005}, config) == []
    classes = {"E": "forex"}
    assert rebalance_deltas({"E": 0.0}, {"E": 1.0}, 100_000.0, {"E": 0.04}, config, class_by_ticker=classes) == []
    assert rebalance_deltas({"E": 0.0}, {"E": 1.0}, 100_000.0, {"E": 0.06}, config, class_by_ticker=classes) == [("E", 6000.0)]


def test_a_missing_or_bad_price_is_never_traded_on_a_guess():
    assert rebalance_deltas({"A": 10.0}, {"A": float("nan")}, 100_000.0, {"A": 0.5}, CONFIG) == []
    assert rebalance_deltas({"A": 10.0}, {}, 100_000.0, {}, CONFIG) == []
    assert rebalance_deltas({"A": 10.0}, {"A": -1.0}, 100_000.0, {}, CONFIG) == []


def test_non_positive_nav_trades_nothing():
    assert rebalance_deltas({"A": 10.0}, {"A": 10.0}, 0.0, {"A": 0.5}, CONFIG) == []
    assert rebalance_deltas({"A": 10.0}, {"A": 10.0}, float("nan"), {"A": 0.5}, CONFIG) == []


def test_reductions_go_first_because_buying_power_does_not_net_unfilled_sells():
    deltas = rebalance_deltas(
        {"BUY": 0.0, "SELL": 100.0, "COVER": -100.0}, {"BUY": 10.0, "SELL": 10.0, "COVER": 10.0}, 10_000.0,
        {"BUY": 0.5, "SELL": 0.05, "COVER": -0.05}, CONFIG,
    )
    assert [ticker for ticker, _ in deltas][-1] == "BUY"


def test_lot_size_rounds_toward_zero():
    assert rebalance_deltas({"B": 0.0}, {"B": 3.0}, 100.0, {"B": 1.0}, TargetWeightsConfig(min_trade_usd=0.0), lot_size={"B": 0.5}) == [("B", 33.0)]
    assert rebalance_deltas({"S": 0.0}, {"S": 3.0}, 1000.0, {"S": -0.5}, TargetWeightsConfig(min_trade_usd=0.0)) == [("S", -166.0)]


def test_equity_fee_has_a_dollar_minimum_and_none_for_no_trade():
    assert equity_fee_usd(100_000.0, 1.5, 1.0) == pytest.approx(15.0)
    assert equity_fee_usd(100.0, 1.5, 1.0) == 1.0
    assert equity_fee_usd(0.0, 1.5, 1.0) == 0.0
    assert equity_fee_usd(float("nan"), 1.5, 1.0) == 0.0


def test_sweep_reserve_is_a_fixed_share_of_gross():
    reserve = sweep_reserve(TargetWeightsConfig(reserve_gross=0.3))
    assert reserve["long"] == pytest.approx(0.15)
    assert reserve["short"] == pytest.approx(0.15)
    assert reserve["margin"] == pytest.approx(0.15)
