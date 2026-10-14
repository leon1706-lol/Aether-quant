"""V5.8.0 (Problems.md #172): the models read a drawdown-free regime vector, exactly as the training dataset builds it.

The dataset has no account state, so its regime features always use portfolio_drawdown=0.0; live fed the real drawdown,
and an 8% drawdown moved the top/bottom-6 of the blended score by a third. `build_model_input_regime_vector` is the one
definition both sides call; risk decisions keep the real-drawdown vector."""

from __future__ import annotations

import datetime
import sys
import types

import pandas as pd
import pytest

from regime import build_market_regime_vector, build_model_input_regime_vector

CASES = [
    {"momentum_5d": 0.03, "momentum_20d": 0.06, "rolling_volatility_5d": 0.012, "rolling_volatility_20d": 0.012},
    {"momentum_5d": -0.04, "momentum_20d": -0.07, "rolling_volatility_5d": 0.04, "rolling_volatility_20d": 0.035},
    {"momentum_5d": 0.004, "momentum_20d": -0.003, "rolling_volatility_5d": 0.02, "rolling_volatility_20d": 0.02},
    {"momentum_5d": -0.01, "momentum_20d": -0.05, "rolling_volatility_5d": 0.05, "rolling_volatility_20d": 0.04},
]


def test_the_model_vector_ignores_portfolio_drawdown_and_the_risk_vector_does_not():
    features = CASES[1]
    model = build_model_input_regime_vector(features, average_correlation=0.8)
    pinned = build_market_regime_vector(features, portfolio_drawdown=0.0, average_correlation=0.8)
    stressed = build_market_regime_vector(features, portfolio_drawdown=-0.08, average_correlation=0.8)
    assert model.to_dict() == pinned.to_dict()
    assert stressed.risk_score != model.risk_score or stressed.risk_regime != model.risk_regime


@pytest.mark.parametrize("features", CASES)
@pytest.mark.parametrize("correlation", [0.0, 0.5, 0.9])
def test_dataset_encoding_equals_the_model_vector(features, correlation):
    import train

    row = pd.Series({**features, "topology_correlation_strength": correlation})
    encoded = train._encode_regime_row(row)
    vector = build_model_input_regime_vector(features, average_correlation=correlation)
    assert encoded["regime_signal_risk_score"] == vector.risk_score
    assert encoded["regime_signal_confidence"] == vector.confidence
    assert encoded["regime_signal_trend_score"] == vector.trend_score
    assert encoded[f"regime_risk_{vector.risk_regime.split('_', 1)[1]}"] == 1.0


@pytest.fixture(scope="module")
def main_module():
    stub = types.ModuleType("AlgorithmImports")
    stub.QCAlgorithm = type("QCAlgorithm", (), {})
    stub.Slice = object
    stub.time = datetime.time
    patcher = pytest.MonkeyPatch()
    patcher.setitem(sys.modules, "AlgorithmImports", stub)
    patcher.delitem(sys.modules, "main", raising=False)
    import main  # noqa: PLC0415

    yield main
    sys.modules.pop("main", None)
    patcher.undo()


def _algorithm(main_module, drawdown):
    algorithm = object.__new__(main_module.AetherQuantAlgorithm)
    for name, value in dict(
        current_total_drawdown=drawdown, runtime_mode="backtest", bypass_regime_drawdown_gate=False,
        bypass_safety_gates=False, regime_risk_off_drawdown_threshold=0.08, regime_risk_on_drawdown_threshold=0.03,
        regime_bullish_threshold=0.02, regime_bearish_threshold=-0.02, low_volatility_threshold=0.01,
        high_volatility_threshold=0.03, regime_high_correlation_threshold=0.75,
    ).items():
        setattr(algorithm, name, value)
    return algorithm


def test_live_model_regime_is_the_dataset_vector_whatever_the_account_drawdown(main_module):
    features = CASES[3]
    expected = build_model_input_regime_vector(features, average_correlation=0.6).to_dict()
    for drawdown in (0.0, -0.02, -0.05, -0.12):
        algorithm = _algorithm(main_module, drawdown)
        assert algorithm._build_model_regime_payload(features, average_correlation=0.6) == expected


def test_live_risk_regime_still_sees_the_real_drawdown(main_module):
    features = CASES[3]
    calm = _algorithm(main_module, 0.0)._build_regime_payload(features, average_correlation=0.6)
    stressed = _algorithm(main_module, -0.12)._build_regime_payload(features, average_correlation=0.6)
    assert stressed["risk_regime"] == "risk_off" and stressed["risk_score"] != calm["risk_score"]
