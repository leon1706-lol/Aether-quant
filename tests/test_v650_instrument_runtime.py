"""scripts/v650_instrument.py's runtime (V6.6.6, #359): the plumbing weights, the run configs, the engine comparison against a finished Lean run and the
order comparison, on a small synthetic market panel."""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd
import pytest

from script_loader import ROOT, load_script

DATES = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2019-01-02", periods=60)]
TICKERS = ["AAA", "BBB", "CCC", "DDD", "TLT", "EURUSD", "BTCUSD", "ETHUSD", "LTCUSD"]
CLASSES = {"AAA": "equity", "BBB": "equity", "CCC": "equity", "DDD": "equity", "TLT": "bond", "EURUSD": "forex", "BTCUSD": "crypto", "ETHUSD": "crypto", "LTCUSD": "crypto"}


class Panel:
    def __init__(self, nan_ticker=None):
        rng = np.random.default_rng(0)
        self.dates = list(DATES)
        self.sessions = set(DATES)
        self.tickers = list(TICKERS)
        self.asset_class = dict(CLASSES)
        self.closes = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, (len(DATES), len(TICKERS))), axis=0))
        self.opens = self.closes * 0.999
        if nan_ticker:
            self.closes[:, TICKERS.index(nan_ticker)] = np.nan
            self.opens[:, TICKERS.index(nan_ticker)] = np.nan

    def index(self):
        return {ticker: position for position, ticker in enumerate(self.tickers)}


@pytest.fixture
def module(monkeypatch, tmp_path):
    instrument = load_script("v650_instrument")
    root = tmp_path
    for name, value in (("ROOT", root), ("V650", root / "v650"), ("WEIGHTS", root / "v650" / "weights"), ("RUN_CONFIGS", root / "run_configs"), ("RATE_CSV", root / "rates.csv")):
        monkeypatch.setattr(instrument, name, value)
    (root / "v650").mkdir()
    (root / "run_configs").mkdir()
    (root / "config.json").write_text((ROOT / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
    return instrument


def test_the_run_config_turns_on_the_target_path_and_relaxes_the_locks_for_plumbing(module):
    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    locked = module.target_path_config(base, weights_path="w.csv", weights_sha256="abc", window=("2019-01-01", "2019-12-31"))
    plumbing = module.target_path_config(base, weights_path="w.csv", weights_sha256="abc", window=("2019-01-01", "2019-12-31"), locks=False)
    assert locked["phase_v2"]["target_weights"]["enabled"] is True and locked["phase6"]["risk"]["max_total_drawdown_pct"] == 0.15 and plumbing["phase6"]["risk"]["max_total_drawdown_pct"] == 0.95
    assert locked["runtime"]["lean_window_override"] == {"start": "2019-01-01", "end": "2019-12-31"} and base["phase_v2"]["target_weights"].get("enabled") != "abc"


def test_random_weights_are_seeded_dollar_neutral_or_long_only_and_skip_dead_names(module):
    panel = Panel(nan_ticker="DDD")
    neutral = module.random_weights(panel, ["AAA", "BBB", "CCC", "DDD"], seed=1, start=DATES[0], end=DATES[-1], every=5, gross=1.0, neutral=True)
    assert neutral == module.random_weights(panel, ["AAA", "BBB", "CCC", "DDD"], seed=1, start=DATES[0], end=DATES[-1], every=5, gross=1.0, neutral=True)
    first = next(iter(neutral.values()))
    assert abs(sum(first.values())) < 1e-9 and abs(sum(abs(v) for v in first.values()) - 1.0) < 1e-9 and "DDD" not in first
    long_only = module.random_weights(panel, ["BTCUSD"], seed=2, start=DATES[0], end=DATES[-1], every=10, gross=0.3, neutral=False)
    assert all(value >= 0 for row in long_only.values() for value in row.values())
    dead = module.random_weights(Panel(nan_ticker="DDD"), ["DDD"], seed=1, start=DATES[0], end=DATES[-1], every=10, gross=1.0, neutral=True)
    assert all(row == {} for row in dead.values())


def test_the_oracle_goes_long_the_winners_and_short_the_losers(module):
    panel = Panel(nan_ticker="DDD")
    rows = module.oracle_weights(panel, ["AAA", "BBB", "CCC", "DDD"], start=DATES[0], end=DATES[-1], every=5, gross=1.0)
    assert rows and all(abs(sum(row.values())) < 1e-9 for row in rows.values())
    assert module.oracle_weights(panel, ["DDD"], start=DATES[0], end=DATES[-1], every=5, gross=1.0) == {}


def test_make_writes_every_plumbing_weight_file_and_run_config(module, monkeypatch):
    monkeypatch.setattr(module, "load_market_panel", lambda root, base: Panel())
    manifest = module.make()
    assert {"v650_bt13", "v650_bt17", "v650_bt12", "v650_bt18", "v650_bt23"} <= set(manifest) and (module.WEIGHTS / "plumbing_oracle.csv").exists()
    oracle_config = json.loads((module.RUN_CONFIGS / "v650_bt17.json").read_text(encoding="utf-8"))
    assert oracle_config["phase6"]["risk"]["max_total_drawdown_pct"] == 0.15 and (module.V650 / "instrument_manifest.json").exists()
    all_off = json.loads((module.RUN_CONFIGS / "v650_bt23.json").read_text(encoding="utf-8"))
    assert all_off["phase_v2"]["rolling_ic_gate"]["enabled"] is False and all_off["phase_v2"]["costs"]["cost_sizing_enabled"] is False


def _run_config(module, monkeypatch, name="v650_x"):
    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    (module.WEIGHTS).mkdir(parents=True, exist_ok=True)
    from portfolio.target_weights import write_weight_file

    sha = write_weight_file({DATES[5]: {"AAA": 0.1}}, module.WEIGHTS / "w.csv")
    config = module.target_path_config(base, weights_path="v650/weights/w.csv", weights_sha256=sha, window=(DATES[0], DATES[-1]))
    (module.RUN_CONFIGS / f"{name}.json").write_text(json.dumps(config), encoding="utf-8")
    return config


def test_the_engine_comparison_correlates_the_engine_with_a_finished_lean_run(module, monkeypatch, tmp_path):
    import data_pipeline.fred_backfill as fred
    import features.fx_carry as fx_carry

    _run_config(module, monkeypatch)
    module.RATE_CSV.write_text("date,rate\n2019-01-02,0.02\n", encoding="utf-8")
    monkeypatch.setattr(module, "load_market_panel", lambda root, config: Panel())
    monkeypatch.setattr(module, "load_rate_series", lambda path: ([], []))
    monkeypatch.setattr(fred, "load_cached_fred_series", lambda: {})
    monkeypatch.setattr(fx_carry, "fx_carry_3m", lambda ticker, kind, day, series: 0.0)
    nav = pd.Series(1000.0 * (1.0 + np.sin(np.arange(60)) * 0.01).cumprod(), index=DATES)
    monkeypatch.setattr(module, "simulate_target_weights", lambda weights, panel, config, start, end, **kwargs: {
        "total": nav.pct_change().dropna(), "nav": nav, "fees": 1.0, "financing": 0.5, "fills": 3, "locked_on": None})
    run_dir = tmp_path / "backtests" / "r"
    run_dir.mkdir(parents=True)
    stamps = [pd.Timestamp(day, tz="UTC").timestamp() for day in DATES]
    result = {"charts": {"Strategy Equity": {"series": {"Equity": {"values": [[stamp, value] for stamp, value in zip(stamps, nav.to_numpy() * 1.001)]}}}}}
    (run_dir / "1.json").write_text(json.dumps(result), encoding="utf-8")
    report = module.compare("v650_x", run_dir)
    assert report["corr_lag0"] > 0.9 and report["engine_fills"] == 3 and report["corr_weekly"] is not None and "annual_gap_bps" in report
    short = tmp_path / "backtests" / "short"
    short.mkdir()
    (short / "1.json").write_text(json.dumps({"charts": {"Strategy Equity": {"series": {"Equity": {"values": [[stamps[0], 1000.0], [stamps[1], 1001.0]]}}}}}), encoding="utf-8")
    thin = module.compare("v650_x", short)
    assert thin["corr_lag0"] is None and thin["corr_weekly"] is None


def _events(path, fills):
    path.mkdir(parents=True)
    (path / "1.json").write_text("{}", encoding="utf-8")
    events = [{"time": pd.Timestamp(day, tz="UTC").timestamp() + 72000, "status": "filled", "symbolValue": ticker, "fillQuantity": quantity, "fillPrice": price} for day, ticker, quantity, price in fills]
    (path / "1-order-events.json").write_text(json.dumps(events), encoding="utf-8")


def test_two_runs_are_compared_order_for_order(module, tmp_path):
    _events(tmp_path / "a", [("2019-01-03", "AAA", 10, 5.0), ("2019-01-04", "BBB", -5, 6.0)])
    _events(tmp_path / "b", [("2019-01-03", "AAA", 10, 5.0), ("2019-01-04", "BBB", -5, 6.5)])
    result = module.orders(tmp_path / "a", tmp_path / "b")
    assert result["identical"] is False and result["first"] == 2 and result["only_first"] and result["only_second"]
    assert module.orders(tmp_path / "a", tmp_path / "a")["identical"] is True


@pytest.mark.parametrize("argv,target", [(["make"], "make"), (["compare", "n", "backtests/r"], "compare"), (["orders", "backtests/a", "backtests/b"], "orders")])
def test_the_command_dispatches_each_stage(module, monkeypatch, capsys, argv, target):
    monkeypatch.setattr(module, target, lambda *args: {"ran": target})
    monkeypatch.setattr(sys, "argv", ["instrument", *argv])
    assert module.main() == 0 and f'"ran": "{target}"' in capsys.readouterr().out
