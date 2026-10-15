"""scripts/crypto_fee_research.py (V6.0.0, rule R-CRYPTO): the component P&L and the decision, pure."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("crypto_fee_research", ROOT / "scripts" / "crypto_fee_research.py")
research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research)


def test_component_net_charges_fees_on_weight_changes_and_earns_on_the_previous_weights():
    frame = pd.DataFrame({"date": ["d0", "d1", "d2", "d0", "d1", "d2"], "ticker": ["BTC"] * 3 + ["AAA"] * 3,
                          "target_return_1d": [0.0, 0.10, -0.05, 0.0, 0.5, 0.5]})
    result = SimpleNamespace(per_date=["d0", "d1", "d2"], weights_log=[{"BTC": 0.0, "AAA": 0.2}, {"BTC": 0.10, "AAA": 0.2}, {"AAA": 0.2}])
    out = research.component_net(result, frame, {"BTC"}, 80.0)
    assert out["gross"] == pytest.approx(0.0 * 0.10 + 0.10 * -0.05)  # d1 earns the d0 weight (0), d2 the d1 weight
    assert out["fees"] == pytest.approx((0.10 + 0.10) * 80.0 / 1e4)  # in at d1, out at d2
    assert out["net"] == pytest.approx(out["gross"] - out["fees"])


def test_fee_per_side_follows_the_route_and_fill_rates():
    assert research.fee_per_side(True, False, 1.0, 1.0) == pytest.approx(70.0)
    assert research.fee_per_side(True, True, 1.0, 1.0) == pytest.approx(60.0)
    assert research.fee_per_side(True, True, 1.0, 0.5) == pytest.approx((60.0 + 70.0) / 2)
    assert research.fee_per_side(False, False, 1.0, 1.0) == pytest.approx(80.0)


def _row(validation_net, backtest_sharpe):
    return {"validation": {"crypto_net": validation_net, "total_sharpe": 0.0}, "backtest": {"crypto_net": 0.0, "total_sharpe": backtest_sharpe}}


def test_r_crypto_picks_the_best_validation_net_inside_the_constraints_else_keeps_c0():
    results = {"C0": _row(-0.010, 0.50), "C1": _row(-0.006, 0.49), "C2": _row(-0.004, 0.40), "C3": _row(-0.008, 0.50)}
    decision = research.decide(results, {"C1": 0.95, "C2": 0.95})
    assert decision["winner"] == "C3" or decision["winner"] == "C1"
    assert decision["winner"] == "C1"  # C2 loses 0.10 of total-book Sharpe; C1 has the best remaining validation net
    assert research.decide(results, {"C1": 0.80, "C2": 0.95})["winner"] == "C3"  # C1 fails the 85% fill-rate clause
    worse = {"C0": _row(-0.001, 0.5), "C1": _row(-0.002, 0.5), "C3": _row(-0.003, 0.5)}
    assert research.decide(worse, {"C1": 0.99})["winner"] == "C0"
