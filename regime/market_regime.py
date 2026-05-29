"""Quantitative market-regime detection for Aether Quant V2."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass


TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class MarketRegimeVector:
    primary_regime: str
    trend_regime: str
    volatility_regime: str
    risk_regime: str
    trend_score: float
    rolling_volatility: float
    annualized_volatility: float
    drawdown: float
    average_correlation: float
    risk_score: float
    confidence: float
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _finite_float(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _normalize_drawdown(value: object) -> float:
    drawdown = _finite_float(value)
    if drawdown < 0.0:
        return abs(drawdown)
    return max(0.0, drawdown)


def classify_trend_regime(
    momentum_5d: float,
    momentum_20d: float,
    bullish_threshold: float = 0.02,
    bearish_threshold: float = -0.02,
) -> tuple[str, float]:
    trend_score = 0.35 * _finite_float(momentum_5d) + 0.65 * _finite_float(momentum_20d)
    if trend_score >= bullish_threshold:
        return "bullish", trend_score
    if trend_score <= bearish_threshold:
        return "bearish", trend_score
    return "sideways", trend_score


def classify_volatility_state(
    rolling_volatility: float,
    low_volatility_threshold: float = 0.01,
    high_volatility_threshold: float = 0.03,
) -> str:
    volatility = abs(_finite_float(rolling_volatility))
    if volatility >= high_volatility_threshold:
        return "high_volatility"
    if volatility <= low_volatility_threshold:
        return "low_volatility"
    return "normal_volatility"


def classify_risk_regime(
    trend_regime: str,
    volatility_regime: str,
    drawdown: float,
    average_correlation: float = 0.0,
    risk_off_drawdown_threshold: float = 0.08,
    risk_on_drawdown_threshold: float = 0.03,
    high_correlation_threshold: float = 0.75,
) -> tuple[str, float]:
    normalized_drawdown = _normalize_drawdown(drawdown)
    correlation = max(-1.0, min(_finite_float(average_correlation), 1.0))

    risk_score = 0.0
    risk_score += {"bullish": 0.45, "sideways": 0.0, "bearish": -0.45}.get(trend_regime, 0.0)
    risk_score += {"low_volatility": 0.25, "normal_volatility": 0.0, "high_volatility": -0.25}.get(volatility_regime, 0.0)

    if normalized_drawdown >= risk_off_drawdown_threshold:
        risk_score -= 0.35
    elif normalized_drawdown <= risk_on_drawdown_threshold:
        risk_score += 0.15

    if correlation >= high_correlation_threshold and volatility_regime == "high_volatility":
        risk_score -= 0.10

    risk_score = max(-1.0, min(risk_score, 1.0))

    if trend_regime == "bearish" and volatility_regime == "high_volatility":
        return "risk_off", risk_score
    if normalized_drawdown >= risk_off_drawdown_threshold and volatility_regime != "low_volatility":
        return "risk_off", risk_score
    if trend_regime == "bullish" and volatility_regime != "high_volatility" and normalized_drawdown <= risk_on_drawdown_threshold:
        return "risk_on", risk_score
    if risk_score >= 0.25:
        return "risk_on", risk_score
    if risk_score <= -0.25:
        return "risk_off", risk_score
    return "risk_neutral", risk_score


def build_market_regime_vector(
    features: dict,
    portfolio_drawdown: float = 0.0,
    average_correlation: float = 0.0,
    bullish_threshold: float = 0.02,
    bearish_threshold: float = -0.02,
    low_volatility_threshold: float = 0.01,
    high_volatility_threshold: float = 0.03,
    risk_off_drawdown_threshold: float = 0.08,
    risk_on_drawdown_threshold: float = 0.03,
    high_correlation_threshold: float = 0.75,
) -> MarketRegimeVector:
    momentum_5d = _finite_float(features.get("momentum_5d", features.get("close_to_close_return_5d", 0.0)))
    momentum_20d = _finite_float(features.get("momentum_20d", features.get("close_to_close_return_20d", 0.0)))
    rolling_volatility = abs(_finite_float(features.get("rolling_volatility_20d", features.get("rolling_volatility_5d", 0.0))))
    feature_drawdown = features.get("drawdown_20d", features.get("max_drawdown_20d", portfolio_drawdown))
    drawdown = max(_normalize_drawdown(feature_drawdown), _normalize_drawdown(portfolio_drawdown))
    correlation = max(-1.0, min(_finite_float(features.get("average_correlation", average_correlation)), 1.0))

    trend_regime, trend_score = classify_trend_regime(
        momentum_5d,
        momentum_20d,
        bullish_threshold=bullish_threshold,
        bearish_threshold=bearish_threshold,
    )
    volatility_regime = classify_volatility_state(
        rolling_volatility,
        low_volatility_threshold=low_volatility_threshold,
        high_volatility_threshold=high_volatility_threshold,
    )
    risk_regime, risk_score = classify_risk_regime(
        trend_regime,
        volatility_regime,
        drawdown,
        average_correlation=correlation,
        risk_off_drawdown_threshold=risk_off_drawdown_threshold,
        risk_on_drawdown_threshold=risk_on_drawdown_threshold,
        high_correlation_threshold=high_correlation_threshold,
    )

    if risk_regime == "risk_off":
        primary_regime = f"{trend_regime}_risk_off"
    elif trend_regime == "sideways":
        primary_regime = f"sideways_{volatility_regime}"
    else:
        primary_regime = f"{trend_regime}_{volatility_regime}"

    trend_confidence = min(abs(trend_score) / max(abs(bullish_threshold), abs(bearish_threshold), 1e-9), 1.0)
    volatility_confidence = 1.0 if volatility_regime != "normal_volatility" else 0.45
    risk_confidence = min(abs(risk_score), 1.0)
    confidence = max(0.0, min((trend_confidence + volatility_confidence + risk_confidence) / 3.0, 1.0))

    reasons = [
        f"trend={trend_regime}",
        f"volatility={volatility_regime}",
        f"risk={risk_regime}",
    ]
    if drawdown >= risk_off_drawdown_threshold:
        reasons.append("drawdown_pressure")
    if correlation >= high_correlation_threshold and volatility_regime == "high_volatility":
        reasons.append("correlated_high_volatility")

    return MarketRegimeVector(
        primary_regime=primary_regime,
        trend_regime=trend_regime,
        volatility_regime=volatility_regime,
        risk_regime=risk_regime,
        trend_score=trend_score,
        rolling_volatility=rolling_volatility,
        annualized_volatility=rolling_volatility * math.sqrt(TRADING_DAYS_PER_YEAR),
        drawdown=drawdown,
        average_correlation=correlation,
        risk_score=risk_score,
        confidence=confidence,
        reasons=reasons,
    )
