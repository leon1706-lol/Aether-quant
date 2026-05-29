from regime import (
    build_market_regime_vector,
    classify_risk_regime,
    classify_trend_regime,
    classify_volatility_state,
)


def test_classify_trend_regime_detects_bullish_bearish_and_sideways():
    assert classify_trend_regime(0.03, 0.05)[0] == "bullish"
    assert classify_trend_regime(-0.03, -0.05)[0] == "bearish"
    assert classify_trend_regime(0.005, -0.005)[0] == "sideways"


def test_classify_volatility_state_uses_daily_thresholds():
    assert classify_volatility_state(0.005) == "low_volatility"
    assert classify_volatility_state(0.02) == "normal_volatility"
    assert classify_volatility_state(0.05) == "high_volatility"


def test_classify_risk_regime_moves_bearish_high_volatility_to_risk_off():
    risk_regime, risk_score = classify_risk_regime(
        "bearish",
        "high_volatility",
        drawdown=0.10,
        average_correlation=0.80,
    )

    assert risk_regime == "risk_off"
    assert risk_score < 0.0


def test_market_regime_vector_builds_risk_on_bullish_state():
    vector = build_market_regime_vector(
        {
            "momentum_5d": 0.03,
            "momentum_20d": 0.06,
            "rolling_volatility_20d": 0.012,
        },
        portfolio_drawdown=-0.01,
    )

    assert vector.trend_regime == "bullish"
    assert vector.volatility_regime == "normal_volatility"
    assert vector.risk_regime == "risk_on"
    assert vector.primary_regime == "bullish_normal_volatility"
    assert vector.confidence > 0.0


def test_market_regime_vector_builds_sideways_state_from_flat_momentum():
    vector = build_market_regime_vector(
        {
            "momentum_5d": 0.002,
            "momentum_20d": -0.001,
            "rolling_volatility_20d": 0.006,
        },
    )

    assert vector.trend_regime == "sideways"
    assert vector.volatility_regime == "low_volatility"
    assert vector.primary_regime == "sideways_low_volatility"


def test_market_regime_vector_handles_bad_numeric_inputs_safely():
    vector = build_market_regime_vector(
        {
            "momentum_5d": "not-a-number",
            "momentum_20d": None,
            "rolling_volatility_20d": float("nan"),
        },
        portfolio_drawdown=float("nan"),
    )

    assert vector.trend_regime == "sideways"
    assert vector.rolling_volatility == 0.0
    assert vector.drawdown == 0.0
