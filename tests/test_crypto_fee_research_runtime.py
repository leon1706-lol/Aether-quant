"""scripts/crypto_fee_research.py's runtime (V6.6.6, #359): the fill-rate summary, the route-aware fee, R-CRYPTO's decision with an eligible variant, and the whole
command (fill sweep, five variants, the C3 or C4 combination) with the as-live harness and the limit-fill simulator stood in."""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import pandas as pd
import pytest

from script_loader import ROOT, load_script

DATES = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2021-01-04", periods=20)]
CRYPTO = ["BTCUSD", "LTCUSD", "ETHUSD", "SOLUSD"]


@pytest.fixture
def module(monkeypatch, tmp_path):
    research = load_script("crypto_fee_research")
    monkeypatch.setattr(research, "ROOT_DIR", tmp_path)
    (tmp_path / "config.json").write_text((ROOT / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
    return research


def test_the_component_net_charges_fees_on_every_weight_change_of_the_named_tickers(module):
    frame = pd.DataFrame({"date": DATES[:3] * 2, "ticker": ["BTCUSD"] * 3 + ["SPY"] * 3, "target_return_1d": [0.01, 0.02, -0.01, 0.5, 0.5, 0.5]})
    result = SimpleNamespace(per_date=DATES[:3], weights_log=[{"BTCUSD": 0.1, "SPY": 0.5}, {"BTCUSD": 0.2}, {}])
    net = module.component_net(result, frame, {"BTCUSD"}, 60.0)
    assert net["gross"] == pytest.approx(0.1 * 0.02 + 0.2 * -0.01) and net["fees"] == pytest.approx((0.1 + 0.1 + 0.2) * 60.0 / 1e4) and net["net"] == pytest.approx(net["gross"] - net["fees"])


def test_the_fill_rates_come_from_the_limit_fill_simulator_on_the_crypto_rows(module, monkeypatch):
    import evaluation.limit_fill_simulator as simulator

    seen = {}
    monkeypatch.setattr(simulator, "simulate_limit_fills", lambda frame, unfilled_timeout_bars, offset_multiplier: seen.update(tickers=set(frame["ticker"]), timeout=unfilled_timeout_bars) or
                        {"overall": {"fill_rate": 0.9, "mean_bars_to_fill": 1.5}, "by_side": {"buy": {"fill_rate": 0.95}, "sell": {"fill_rate": 0.85}}})
    frame = pd.DataFrame({"ticker": ["BTCUSD", "SPY"], "date": DATES[:2]})
    frame.attrs["crypto_tickers"] = ["BTCUSD"]
    assert module.fill_rates(frame, 0.5, 3) == {"overall": 0.9, "buy": 0.95, "sell": 0.85, "mean_bars_to_fill": 1.5} and seen == {"tickers": {"BTCUSD"}, "timeout": 3}


def test_limit_exits_lower_the_fee_when_they_fill(module):
    assert module.fee_per_side(True, True, 0.97, 0.9) < module.fee_per_side(True, False, 0.97, 0.9)


def test_the_best_eligible_variant_wins_and_otherwise_the_current_route_stays(module):
    def row(net, sharpe):
        return {"validation": {"crypto_net": net}, "backtest": {"total_sharpe": sharpe}}

    results = {"C0": row(0.01, 1.0), "C1": row(0.02, 0.98), "C2": row(0.03, 0.99), "C3": row(0.05, 0.5), "C4": row(0.0, 1.0), "C5": row(0.06, 1.0)}
    verdict = module.decide(results, {"C1": 0.9, "C2": 0.9, "C5": 0.5})
    assert verdict == {"winner": "C2", "eligible": ["C1", "C2"]}
    assert module.decide({"C0": row(0.5, 1.0), "C1": row(0.1, 1.0)}, {"C1": 0.9}) == {"winner": "C0", "reason": "no variant beats C0's validation crypto net inside the constraints"}


class Harness:
    def __init__(self, split, dataset_path, *, graduates_positive):
        import json as _json

        self.split = split
        self.config = _json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        self.frame = pd.DataFrame([{"date": date, "ticker": ticker, "target_return_1d": (0.002 if ticker in ("BTCUSD", "LTCUSD") else (0.002 if graduates_positive else -0.002))} for date in DATES for ticker in CRYPTO])
        self.asset_class_by_ticker = {ticker: "crypto" for ticker in CRYPTO} | {"SPY": "equity"}
        self.metadata = {ticker: {"trading_eligible": True} for ticker in CRYPTO}
        self.venue_listing_dates = None

    def as_live(self, **kwargs):
        metadata = kwargs["candidate_metadata_by_ticker"]
        weights = [{ticker: 0.05 for ticker in CRYPTO if metadata[ticker]["trading_eligible"]} for _ in DATES]
        return SimpleNamespace(per_date=list(DATES), weights_log=weights, net_sharpe=0.5, net_total_return=0.1)


def _install(monkeypatch, *, graduates_positive, sell_rates):
    import evaluation.limit_fill_simulator as simulator
    import risk.asset_class_router as router

    levers = types.ModuleType("as_live_levers")
    levers.AsLiveHarness = lambda split, dataset_path: Harness(split, dataset_path, graduates_positive=graduates_positive)
    levers.summarize = lambda result: {"net_sharpe": result.net_sharpe, "net_total_return": result.net_total_return}
    calibration = types.ModuleType("lean_calibration")
    calibration.calibrated_overrides = lambda harness: {"rebalance_counter_start": 0}
    calibration.topology_inputs_fn_for = lambda harness, config: "fn"
    calibration.use_topology = lambda harness, fn: None
    monkeypatch.setitem(sys.modules, "as_live_levers", levers)
    monkeypatch.setitem(sys.modules, "lean_calibration", calibration)
    monkeypatch.setattr(router, "load_venue_listing_dates", lambda path: {})
    monkeypatch.setattr(simulator, "simulate_limit_fills", lambda frame, unfilled_timeout_bars, offset_multiplier: {
        "overall": {"fill_rate": 0.9, "mean_bars_to_fill": 1.0},
        "by_side": {"buy": {"fill_rate": 0.9}, "sell": {"fill_rate": sell_rates(offset_multiplier, unfilled_timeout_bars)}}})


@pytest.mark.parametrize("graduates_positive,better", [(False, "C3"), (True, "C4")])
def test_the_command_sweeps_fills_prices_five_variants_and_combines_the_better_graduate_lever(module, monkeypatch, tmp_path, capsys, graduates_positive, better):
    _install(monkeypatch, graduates_positive=graduates_positive, sell_rates=lambda offset, timeout: 0.9 if (offset, timeout) == (0.5, 5) else 0.8)
    out = tmp_path / "out" / "crypto.json"
    monkeypatch.setattr(sys, "argv", ["crypto_fee_research", "--out", str(out), "--dataset", "d.csv"])
    assert module.main() == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert set(written["results"]) == {"C0", "C1", "C2", "C3", "C4", "C5"} and written["decision"]["combined_with"] == better and written["decision"]["best_sweep"] == "offset0.5_timeout5"
    assert len(written["sweep"]) == 6 and written["fill_rates_routed"]["C2"] == 0.9 and "R-CRYPTO" in capsys.readouterr().out


def test_when_no_sweep_point_fills_enough_the_current_route_is_the_best_one(module, monkeypatch, tmp_path):
    _install(monkeypatch, graduates_positive=False, sell_rates=lambda offset, timeout: 0.5)
    out = tmp_path / "crypto_low.json"
    monkeypatch.setattr(sys, "argv", ["crypto_fee_research", "--out", str(out)])
    assert module.main() == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["decision"]["best_sweep"] == written["decision"]["current_sweep"] == "offset1.0_timeout3"
