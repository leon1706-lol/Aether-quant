import pandas as pd

from evaluation.limit_fill_simulator import simulate_limit_fills, sweep_limit_fill_offsets


def _row(ticker, date, close, high, low, security_type="equity", spread=0.01):
    return {
        "ticker": ticker,
        "date": date,
        "close": close,
        "high": high,
        "low": low,
        "security_type": security_type,
        "liquidity_spread_proxy": spread,
    }


def test_simulate_limit_fills_buy_fills_when_low_crosses_limit():
    # reference_price=100, spread_fraction=0.01, offset_multiplier=1.0 ->
    # buy_limit = 100 - 100*0.01/2 = 99.5. Next bar's low (99.0) crosses it.
    rows = [
        _row("A", "2020-01-01", close=100.0, high=101.0, low=99.8),
        _row("A", "2020-01-02", close=100.0, high=101.0, low=99.0),
        _row("A", "2020-01-03", close=100.0, high=101.0, low=99.0),
        _row("A", "2020-01-04", close=100.0, high=101.0, low=99.0),
    ]
    dataset = pd.DataFrame(rows)

    result = simulate_limit_fills(dataset, unfilled_timeout_bars=2)

    buy_records = [r for r in result["by_side"]["buy"].items()]
    assert result["by_side"]["buy"]["num_signals"] >= 1
    assert result["by_side"]["buy"]["fill_rate"] == 1.0
    assert buy_records  # sanity - dict is non-empty


def test_simulate_limit_fills_never_fills_when_price_never_crosses():
    rows = [
        _row("A", "2020-01-01", close=100.0, high=100.2, low=99.9),
        _row("A", "2020-01-02", close=100.0, high=100.2, low=99.9),
        _row("A", "2020-01-03", close=100.0, high=100.2, low=99.9),
    ]
    dataset = pd.DataFrame(rows)

    result = simulate_limit_fills(dataset, unfilled_timeout_bars=1)

    assert result["overall"]["fill_rate"] == 0.0
    assert result["overall"]["timeout_rate"] == 1.0
    assert result["overall"]["mean_bars_to_fill"] is None


def test_simulate_limit_fills_sell_side_uses_high():
    # sell_limit = 100 + 100*0.01/2 = 100.5. Next bar's high (101.0) crosses it.
    rows = [
        _row("A", "2020-01-01", close=100.0, high=100.2, low=99.9),
        _row("A", "2020-01-02", close=100.0, high=101.0, low=99.9),
        _row("A", "2020-01-03", close=100.0, high=101.0, low=99.9),
    ]
    dataset = pd.DataFrame(rows)

    result = simulate_limit_fills(dataset, unfilled_timeout_bars=1)

    assert result["by_side"]["sell"]["fill_rate"] == 1.0


def test_simulate_limit_fills_excludes_end_of_data_rows_from_denominator():
    # 3 rows, unfilled_timeout_bars=2 - only row 0 has 2 full rows remaining
    # (rows 1, 2 are too close to the end and must be excluded entirely,
    # not counted as timeouts).
    rows = [
        _row("A", "2020-01-01", close=100.0, high=100.2, low=99.9),
        _row("A", "2020-01-02", close=100.0, high=100.2, low=99.9),
        _row("A", "2020-01-03", close=100.0, high=100.2, low=99.9),
    ]
    dataset = pd.DataFrame(rows)

    result = simulate_limit_fills(dataset, unfilled_timeout_bars=2)

    # 1 eligible row x 2 sides (buy+sell) = 2 signals, not 6.
    assert result["overall"]["num_signals"] == 2


def test_simulate_limit_fills_breaks_out_by_asset_class():
    rows = [
        _row("A", "2020-01-01", close=100.0, high=100.2, low=99.0, security_type="equity"),
        _row("A", "2020-01-02", close=100.0, high=100.2, low=99.0, security_type="equity"),
        _row("B", "2020-01-01", close=50.0, high=50.1, low=49.9, security_type="bond"),
        _row("B", "2020-01-02", close=50.0, high=50.1, low=49.9, security_type="bond"),
    ]
    dataset = pd.DataFrame(rows)

    result = simulate_limit_fills(dataset, unfilled_timeout_bars=1)

    assert set(result["by_asset_class"].keys()) == {"equity", "bond"}


def test_simulate_limit_fills_empty_dataset_returns_zero_stats():
    dataset = pd.DataFrame(columns=["ticker", "date", "close", "high", "low", "security_type", "liquidity_spread_proxy"])

    result = simulate_limit_fills(dataset, unfilled_timeout_bars=3)

    assert result["overall"] == {"num_signals": 0, "fill_rate": 0.0, "timeout_rate": 0.0, "mean_bars_to_fill": None}


def test_simulate_limit_fills_sanity_against_real_order_events():
    """Directional (not numeric) cross-check against the real, already-
    verified order-events evidence (development/Problems.md #34/#96): 45
    real backtests show fills vastly outnumbering timeout-cancels (e.g.
    644 submitted / 620 filled / 23 cancelPending in one run - fills are
    the overwhelming majority outcome). This simulator fires a signal on
    EVERY row (not just real book-selected/order-triggering ones), so an
    exact numeric match isn't expected or meaningful - but the same
    directional pattern (most simulated limit orders fill, not time out)
    should hold, or the simulator's pricing/scan logic would be
    structurally wrong, not just differently-scoped."""
    import pandas as pd

    dataset_path = "ml/datasets/backtest_dataset.csv"
    try:
        dataset = pd.read_csv(dataset_path)
    except FileNotFoundError:
        import pytest

        pytest.skip(f"{dataset_path} not present in this environment")
        return

    sample = dataset[dataset["ticker"].isin(["AAPL", "SPY", "TLT", "GLD", "HYG"])].reset_index(drop=True)
    if sample.empty:
        import pytest

        pytest.skip("none of the sample tickers are present in this dataset")
        return

    result = simulate_limit_fills(sample, unfilled_timeout_bars=3, offset_multiplier=1.0)

    assert result["overall"]["num_signals"] > 0
    # Fills should be the overwhelming majority outcome, matching the real
    # order-events evidence's own directional pattern - not a tight bound,
    # just ruling out a structurally-broken simulator (e.g. inverted
    # buy/sell crossing logic) that would show fill_rate near 0.
    assert result["overall"]["fill_rate"] > 0.5


def test_sweep_limit_fill_offsets_returns_one_result_per_multiplier():
    rows = [
        _row("A", "2020-01-01", close=100.0, high=100.2, low=99.0),
        _row("A", "2020-01-02", close=100.0, high=100.2, low=99.0),
    ]
    dataset = pd.DataFrame(rows)

    result = sweep_limit_fill_offsets(dataset, unfilled_timeout_bars=1, offset_multipliers=[0.5, 1.0, 2.0])

    assert set(result.keys()) == {"0.5", "1.0", "2.0"}
    for multiplier_result in result.values():
        assert "overall" in multiplier_result
