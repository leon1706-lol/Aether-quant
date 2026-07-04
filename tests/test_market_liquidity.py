import pytest

from liquidity import build_liquidity_decision, estimate_high_low_spread


def _decision(
    close=100.0,
    volume=1_000_000.0,
    target_weight=0.10,
    portfolio_value=100_000.0,
    annualized_volatility=0.20,
    security_type="equity",
    **kwargs,
):
    return build_liquidity_decision(
        close=close,
        volume=volume,
        target_weight=target_weight,
        portfolio_value=portfolio_value,
        annualized_volatility=annualized_volatility,
        security_type=security_type,
        **kwargs,
    )


def test_liquid_large_cap_equity_allows_trade():
    # SPY-like: $100 * 80M shares = $8B daily dollar volume, $10k order
    decision = _decision(close=300.0, volume=80_000_000, target_weight=0.10, portfolio_value=100_000.0)
    assert decision.liquidity_risk == "normal"
    assert decision.recommended_action == "allow"
    assert decision.daily_dollar_volume == 300.0 * 80_000_000
    assert decision.order_value == 10_000.0
    assert decision.participation_rate < 0.0001


def test_zero_volume_blocks_trade():
    decision = _decision(volume=0.0, target_weight=0.15)
    assert decision.liquidity_risk == "blocked"
    assert decision.recommended_action == "block"
    assert decision.adjusted_target_weight == 0.0
    assert any("zero_volume" in r for r in decision.reasons)


def test_below_ddv_floor_blocks_trade():
    # $50 * 1000 shares = $50k DDV < $100k floor
    decision = _decision(close=50.0, volume=1_000, target_weight=0.10)
    assert decision.liquidity_risk == "blocked"
    assert decision.recommended_action == "block"
    assert any("daily_dollar_volume_below_floor" in r for r in decision.reasons)


def test_thin_market_downgrades_to_simulate():
    # $10 * 200k shares = $2M DDV, $10k order → 0.5% participation (> 0.2% thin threshold)
    decision = _decision(close=10.0, volume=200_000, target_weight=0.10, portfolio_value=100_000.0)
    assert decision.liquidity_risk == "thin"
    assert decision.recommended_action == "simulate_instead"
    assert decision.adjusted_target_weight == 0.10


def test_high_impact_reduces_size():
    # $5 * 100k shares = $500k DDV, $20k order → 4% participation (> 1% high_impact threshold)
    decision = _decision(
        close=5.0, volume=100_000, target_weight=0.20, portfolio_value=100_000.0,
        high_impact_size_factor=0.5,
    )
    assert decision.liquidity_risk == "high_impact"
    assert decision.recommended_action == "reduce_size"
    assert decision.adjusted_target_weight == pytest.approx(0.10, abs=1e-9)


def test_zero_target_weight_always_allows():
    decision = _decision(volume=0.0, target_weight=0.0)
    assert decision.liquidity_risk == "normal"
    assert decision.recommended_action == "allow"
    assert decision.order_value == 0.0


def test_crypto_uses_higher_spread_proxy():
    eq = _decision(security_type="equity")
    crypto = _decision(security_type="crypto")
    assert crypto.spread_proxy > eq.spread_proxy
    assert eq.spread_proxy == 0.0005
    assert crypto.spread_proxy == 0.0020


def test_round_trip_cost_includes_slippage_and_spread():
    decision = _decision(close=100.0, volume=1_000_000, target_weight=0.10, portfolio_value=100_000.0,
                         annualized_volatility=0.20)
    assert decision.estimated_round_trip_cost == pytest.approx(
        decision.estimated_slippage + decision.spread_proxy, abs=1e-12
    )


def test_determinism():
    kwargs = dict(close=50.0, volume=500_000, target_weight=0.12, portfolio_value=100_000.0,
                  annualized_volatility=0.30, security_type="equity")
    assert build_liquidity_decision(**kwargs).to_dict() == build_liquidity_decision(**kwargs).to_dict()


# ---------------------------------------------------------------------------
# estimate_high_low_spread — Corwin & Schultz (2012), V2-23.1
# ---------------------------------------------------------------------------


def test_estimate_high_low_spread_matches_reference_calculation():
    # Independently computed reference value for this exact 2-bar window.
    spread = estimate_high_low_spread([102.0, 103.0], [98.0, 97.0])
    assert spread == pytest.approx(0.029236361356314623, abs=1e-12)


def test_estimate_high_low_spread_zero_when_prices_are_flat():
    assert estimate_high_low_spread([100.0, 100.0], [100.0, 100.0]) == 0.0


def test_estimate_high_low_spread_narrower_range_gives_smaller_spread():
    wide = estimate_high_low_spread([102.0, 103.0], [98.0, 97.0])
    narrow = estimate_high_low_spread([101.0, 101.5], [99.0, 98.5])
    assert narrow < wide


def test_estimate_high_low_spread_averages_multiple_windows():
    highs = [102.0, 103.0, 101.5]
    lows = [98.0, 97.0, 98.5]
    window_a = estimate_high_low_spread(highs[:2], lows[:2])
    window_b = estimate_high_low_spread(highs[1:], lows[1:])
    combined = estimate_high_low_spread(highs, lows)
    assert combined == pytest.approx((window_a + window_b) / 2, abs=1e-12)


def test_estimate_high_low_spread_returns_none_for_insufficient_bars():
    assert estimate_high_low_spread([100.0], [99.0]) is None
    assert estimate_high_low_spread([], []) is None


def test_estimate_high_low_spread_returns_none_for_mismatched_lengths():
    assert estimate_high_low_spread([100.0, 101.0], [99.0]) is None


def test_estimate_high_low_spread_skips_invalid_bars():
    # First window (bars 0-1) has high < low (bad data) and is skipped
    # entirely; second window (bars 1-2) is valid, so the result reflects
    # only the valid window rather than returning None outright.
    highs = [98.0, 103.0, 104.0]
    lows = [102.0, 97.0, 96.0]
    spread = estimate_high_low_spread(highs, lows)
    assert spread is not None
    assert spread == pytest.approx(estimate_high_low_spread(highs[1:], lows[1:]), abs=1e-12)


def test_estimate_high_low_spread_returns_none_when_all_windows_invalid():
    assert estimate_high_low_spread([0.0, -5.0], [1.0, 2.0]) is None


# ---------------------------------------------------------------------------
# build_liquidity_decision — dynamic_spread wiring
# ---------------------------------------------------------------------------


def test_build_liquidity_decision_uses_dynamic_spread_when_provided():
    decision = _decision(security_type="equity", dynamic_spread=0.0123)
    assert decision.spread_proxy == 0.0123


def test_build_liquidity_decision_falls_back_to_static_table_when_dynamic_spread_none():
    decision = _decision(security_type="crypto", dynamic_spread=None)
    assert decision.spread_proxy == 0.0020


