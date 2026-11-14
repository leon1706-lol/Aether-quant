"""Stand-ins for the as-live harness the research scripts (scripts/v6xx_research.py and friends) drive (V6.6.6, #359).

The real harness simulates the book over years of data. These keep its public surface - frames, asset classes, `as_live`, `gate_for`,
`v610_mechanisms` - and answer from small synthetic numbers, so a script's stages, report and adoption logic run for real."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import numpy as np
import pandas as pd

LEGACY_COLUMN = "legacy_probability"
DATES = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2024-01-02", periods=30)]
EQUITY = [f"EQ{n}" for n in range(6)]
CRYPTO = ["BTCUSD", "LTCUSD", "ETHUSD"]
FOREX = ["EURUSD"]
TICKERS = EQUITY + CRYPTO + FOREX


def make_frame(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for day in DATES:
        for ticker in TICKERS:
            score = float(rng.uniform())
            rows.append({
                "date": day, "ticker": ticker, "live_rank_score": score, "target_rank_20d": float(np.clip(score + rng.normal(0, 0.2), 0, 1)),
                "target_return_20d": float(rng.normal(0, 0.05)), "target_return_1d": float(rng.normal(0, 0.01)), "target_direction_20d": float(rng.integers(0, 2)),
                LEGACY_COLUMN: float(rng.uniform(0.3, 0.7)), "regime_trend_bullish": 1.0, "regime_trend_bearish": 0.0, "close": 10.0 + float(rng.normal()),
            })
    return pd.DataFrame(rows)


def make_result(phase: int = 0, seed: int = 0) -> SimpleNamespace:
    rng = np.random.default_rng(seed + phase)
    returns = [float(value) for value in rng.normal(0.0004, 0.01, len(DATES))]
    return SimpleNamespace(
        per_date=list(DATES), per_date_net_return=returns, per_date_component_returns={"legacy": {day: 0.0001 for day in DATES}},
        kill_switch_locked_date_list=DATES[3:6], rebalance_log=[{"date": day, "engaged": index % 2 == 0} for index, day in enumerate(DATES[::5])],
        weights_log=[{ticker: 0.05 for ticker in EQUITY[:2]} for _ in DATES], mean_gross_exposure=0.4,
    )


class FakeHarness:
    def __init__(self, split=None, *, seed: int = 0, **kwargs):
        self.split = split
        self.kwargs = kwargs
        self.frame = make_frame(seed)
        self.lagged_frame = self.frame.copy()
        self.rank_groups: dict = {}
        self.asset_class_by_ticker = {**{t: "equity" for t in EQUITY}, **{t: "crypto" for t in CRYPTO}, **{t: "forex" for t in FOREX}}
        self.metadata = {t: {"asset_class": kind, "trading_eligible": True} for t, kind in self.asset_class_by_ticker.items()}
        self.late_bar_tickers = set(CRYPTO)
        self.ic_config = {"horizon_days": 20, "rolling_window_days": 40, "min_names_per_date": 3}
        self._states = {"a": lambda key: {"events": []}}
        self._gates: dict = {}
        self._mechanisms: dict = {}
        self.original_scores = self.frame["live_rank_score"].to_numpy().copy()
        self.topology_inputs_fn = None
        self.calls: list[dict] = []

    def as_live(self, **kwargs):
        self.calls.append(kwargs)
        return make_result(int(kwargs.get("phase", 0) or 0))

    def v610_mechanisms(self, config, **kwargs):
        return {}

    def gate_for(self, frame, **kwargs):
        return lambda date: {"engaged": hash(date) % 2 == 0}


def install(monkeypatch) -> SimpleNamespace:
    """`as_live_levers` and `lean_calibration` as the research scripts import them (by bare name), backed by `FakeHarness`."""
    seen = SimpleNamespace(harnesses=[])

    def harness_factory(split, **kwargs):
        harness = FakeHarness(split, **kwargs)
        seen.harnesses.append(harness)
        return harness

    def summarize(result):
        returns = np.asarray(result.per_date_net_return, dtype=float)
        std = float(returns.std(ddof=1))
        return {"net_sharpe": float(returns.mean() / std * np.sqrt(252)) if std else 0.0, "net_max_drawdown": -0.05, "net_total_return": float(returns.sum()),
                "annualized_turnover": 3.0, "cost_drag_annual_bps": 40.0}

    levers = types.ModuleType("as_live_levers")
    levers.AsLiveHarness = harness_factory
    levers.LEGACY_PROBABILITY_COLUMN = LEGACY_COLUMN
    levers.summarize = summarize
    calibration = types.ModuleType("lean_calibration")
    calibration.ANALYZER_INCLUDE = ("a",)
    calibration.calibrated_overrides = lambda harness, phase=0: {"phase": phase}
    calibration.topology_inputs_fn_for = lambda harness, config: None
    calibration.use_topology = lambda harness, fn: None
    monkeypatch.setitem(sys.modules, "as_live_levers", levers)
    monkeypatch.setitem(sys.modules, "lean_calibration", calibration)
    return seen
