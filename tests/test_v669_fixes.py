"""V6.6.9 regressions that cross modules (#382 onward); a module's own cases live in its own test file."""

from __future__ import annotations

import json

import pandas as pd
import pytest

import train
from train import fit_and_apply_scaler, write_scaler_artifacts


def test_the_scaler_goes_where_the_module_constants_point_when_no_path_is_given(tmp_path, monkeypatch):
    """#382: the paths were bound as defaults at import, so moving the constants still wrote the real `ml/scaler_stats.json`."""
    moved = tmp_path / "ml"
    monkeypatch.setattr(train, "SCALER_PATH", moved / "scaler.pkl")
    monkeypatch.setattr(train, "SCALER_STATS_PATH", moved / "scaler_stats.json")
    dataset = pd.DataFrame({"ticker": ["A", "A", "B"], "split": ["train", "train", "train"], "feature": [10.0, 20.0, 30.0]})
    _, scaler, _ = fit_and_apply_scaler(dataset, ["feature"])
    write_scaler_artifacts(scaler, {"feature_names": ["feature"]}, clip_sigma=6.0)
    assert (moved / "scaler.pkl").exists()
    stats = json.loads((moved / "scaler_stats.json").read_text(encoding="utf-8"))
    assert stats["clip_sigma"] == 6.0 and stats["feature_names"] == ["feature"]


# --- #384: a forex name on the target-weights path -------------------------------------------------------------------------


def test_the_classes_a_weight_file_holds_that_the_disabled_sweep_would_close_are_named():
    from risk.asset_class_router import target_path_class_conflicts

    classes = {"AAA": "equity", "EURUSD": "forex", "BTCUSD": "crypto"}
    held = ["AAA", "EURUSD", "BTCUSD", "UNKNOWN"]
    off = {"futures_enabled": False, "options_enabled": False}
    assert target_path_class_conflicts(held, classes, forex_enabled=False, **off) == ["forex"]
    assert target_path_class_conflicts(held, classes, forex_enabled=True, **off) == []
    assert target_path_class_conflicts(["AAA"], classes, forex_enabled=False, **off) == []


def test_drop_class_weights_removes_only_the_named_classes_and_copies_the_rows():
    from portfolio.target_weights import drop_class_weights

    rows = {"2024-01-02": {"AAA": 0.1, "EURUSD": 0.03}, "2024-01-03": {"EURUSD": -0.03}}
    classes = {"AAA": "equity", "EURUSD": "forex"}
    assert drop_class_weights(rows, classes, ["forex"]) == {"2024-01-02": {"AAA": 0.1}, "2024-01-03": {}}
    kept = drop_class_weights(rows, classes, [])
    assert kept == rows and kept["2024-01-02"] is not rows["2024-01-02"]


def test_the_engine_does_not_hold_a_class_the_config_disables():
    import numpy as np

    from evaluation.target_weights_engine import MarketPanel, simulate_target_weights
    from portfolio.target_weights import TargetWeightsConfig

    free = TargetWeightsConfig(
        enabled=True, min_weight_change=0.0, min_trade_usd=0.0, forex_min_trade_usd=0.0, equity_fee_bps=0.0, equity_min_fee_usd=0.0,
        slippage_bps_by_class={"equity": 0.0, "bond": 0.0, "forex": 0.0, "crypto": 0.0}, financing_enabled=False,
    )
    dates = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]
    closes = np.array([[10.0], [10.0], [11.0], [12.1]])
    panel = MarketPanel(dates, ["EURUSD"], closes.copy(), closes, {"EURUSD": "forex"}, set(dates))
    weights = {"2024-01-01": {"EURUSD": 1.0}}

    def run(disabled):
        return simulate_target_weights(weights, panel, free, start=dates[0], end=dates[-1], fee_fn=lambda *args: 0.0, disabled_classes=disabled)

    held = run(frozenset())
    dropped = run(frozenset({"forex"}))
    assert held["fills"] > 0 and dropped["fills"] == 0
    assert dropped["nav"].iloc[-1] == 100_000.0


def test_a_forex_name_under_the_minimum_trade_never_opens(monkeypatch):
    """Audit item 4: forex_min_trade_usd is $5,000, so a 3% name cap on $100,000 ($3,000) could never trade; the model book's cap is 6%."""
    from portfolio.target_weights import TargetWeightsConfig, rebalance_deltas

    config = TargetWeightsConfig(enabled=True, min_weight_change=0.0)
    kwargs = {"held_units": {}, "usd_per_unit": {"EURUSD": 1.0}, "nav": 100_000.0, "config": config, "class_by_ticker": {"EURUSD": "forex"}}
    assert rebalance_deltas(target={"EURUSD": 0.03}, **kwargs) == []
    assert rebalance_deltas(target={"EURUSD": 0.06}, **kwargs) == [("EURUSD", 6000.0)]


def test_the_main_sweep_drops_a_disabled_class_from_every_row():
    import sys
    import types

    stub = types.ModuleType("AlgorithmImports")
    stub.QCAlgorithm = type("QCAlgorithm", (), {})
    stub.Slice = object
    import datetime

    stub.time = datetime.time
    stub.Exception = type("ClrException", (Exception,), {})
    patcher = pytest.MonkeyPatch()
    patcher.setitem(sys.modules, "AlgorithmImports", stub)
    patcher.delitem(sys.modules, "main", raising=False)
    try:
        import main

        algorithm = object.__new__(main.AetherQuantAlgorithm)
        algorithm._target_weights = {"2024-01-02": {"AAA": 0.1, "EURUSD": 0.06}}
        algorithm._target_class_by_ticker = {"AAA": "equity", "EURUSD": "forex"}
        algorithm.futures_risk_enabled = algorithm.options_risk_enabled = False
        algorithm.forex_risk_enabled = False
        algorithm.messages = []
        algorithm.Debug = algorithm.messages.append
        algorithm._drop_disabled_class_weights()
        assert algorithm._target_weights == {"2024-01-02": {"AAA": 0.1}}
        assert "forex" in algorithm.messages[0]
        algorithm._target_weights = {"2024-01-02": {"EURUSD": 0.06}}
        algorithm.forex_risk_enabled = True
        algorithm._drop_disabled_class_weights()
        assert algorithm._target_weights == {"2024-01-02": {"EURUSD": 0.06}} and len(algorithm.messages) == 1
    finally:
        sys.modules.pop("main", None)
        patcher.undo()


# --- #383: the offline HRP twin samples one close per equity session ---------------------------------------------------------


def test_the_hrp_twin_samples_each_name_once_per_session_and_a_crypto_name_reads_the_bar_before(monkeypatch):
    import evaluation.live_parity as live_parity

    seen = {}
    monkeypatch.setattr(live_parity, "apply_hrp_weights", lambda allocations, returns, gross_exposure, linkage_method: seen.update(returns=returns, linkage=linkage_method) or {"EQ": 0.5, "BTC": 0.5})
    frame = pd.DataFrame({
        "ticker": ["EQ"] * 4 + ["BTC"] * 7,
        "date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"] + [f"2024-01-0{day}" for day in range(1, 8)],
        "close": [10.0, 11.0, 12.1, 13.31] + [100.0, 110.0, 99.0, 99.0, 99.0, 120.0, 130.0],
    })
    sessions = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]
    fn = live_parity.build_hrp_raw_weights_fn(frame, window_bars=4, session_dates=sessions, next_bar_tickers=["BTC"], linkage_method="single")
    fn({"EQ": object(), "BTC": object()}, "2024-01-04")
    assert seen["linkage"] == "single"
    assert seen["returns"]["EQ"] == pytest.approx([0.1, 0.1, 0.1])
    # BTC at session s is the close dated before s: nan, 100, 110, 99 -> two usable returns, 0.1 and -0.1
    assert seen["returns"]["BTC"] == pytest.approx([0.1, -0.1])
    older = live_parity.build_hrp_raw_weights_fn(frame, window_bars=4)
    older({"EQ": object(), "BTC": object()}, "2024-01-04")
    assert len(seen["returns"]["BTC"]) == 3  # the pre-V6.6.9 sampling: the last four bars of its own calendar
