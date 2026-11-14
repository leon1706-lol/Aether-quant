"""scripts/v660_lean.py's runtime (V6.6.6, #359): the run configs of the instrument batch, the synthetic stopping stock, the engine comparison with a Lean run,
the order comparison and the command, on small synthetic panels and manifests."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from script_loader import ROOT, load_script
from synthetic_lean import SESSIONS, write_zip

DATES = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2014-01-02", periods=60)]


class Panel:
    def __init__(self, tickers, stop=None):
        self.dates = list(DATES)
        self.sessions = set(DATES)
        self.tickers = list(tickers)
        self.asset_class = {ticker: "equity" for ticker in tickers}
        rng = np.random.default_rng(0)
        self.closes = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, (len(DATES), len(tickers))), axis=0))
        if stop:
            self.closes[40:, tickers.index(stop)] = np.nan
        self.opens = self.closes * 0.999

    def index(self):
        return {ticker: position for position, ticker in enumerate(self.tickers)}


@pytest.fixture
def module(monkeypatch, tmp_path):
    load_script("v650_instrument")
    lean = load_script("v660_lean")
    out = tmp_path / "v660"
    out.mkdir()
    (tmp_path / "run_configs").mkdir()
    for name, value in (("ROOT", tmp_path), ("OUT", out), ("WEIGHTS", out / "weights"), ("RUN_CONFIGS", tmp_path / "run_configs")):
        monkeypatch.setattr(lean, name, value)
    (tmp_path / "config.json").write_text((ROOT / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
    return lean


def test_a_run_config_is_written_with_or_without_a_data_root(module):
    first = module.write_run("r", {"a": 1}, data_root="data_wide")
    assert first["data_root"] == "data_wide" and (module.RUN_CONFIGS / "r.dataroot").read_text(encoding="utf-8").strip() == "data_wide"
    second = module.write_run("r", {"a": 1})
    assert second["data_root"] == "data" and not (module.RUN_CONFIGS / "r.dataroot").exists() and second["config_sha"] == first["config_sha"]
    assert module.write_run("fresh", {"a": 2})["name"] == "fresh"


def test_a_wide_run_builds_its_universe_and_writes_its_weights(module, monkeypatch):
    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(module, "wide_config_for", lambda config, root, tickers, data_dir: json.loads(json.dumps(config)))
    run = module.wide_run("v660_x", {DATES[0]: {"AAA": 0.1}}, ("2014-01-02", "2014-03-01"), base, {"AAA"}, data_root="data_wide")
    config = json.loads((module.RUN_CONFIGS / "v660_x.json").read_text(encoding="utf-8"))
    assert run["rows"] == 1 and config["phase_v2"]["target_weights"]["no_bar_exit"] is True and (module.WEIGHTS / "v660_x.csv").exists()
    custom = module.wide_run("v660_y", {}, ("a", "b"), base, {"AAA"}, data_root="data_wide", locks=True, config_for=lambda config, tickers: json.loads(json.dumps(config)))
    assert custom["rows"] == 0


def test_the_name_that_stops_inside_the_window_is_found(module):
    panel = Panel(["AAA", "BBB"], stop="BBB")
    assert module.stopping_name(panel, ["AAA", "BBB"], (DATES[5], DATES[-1])) == "BBB"
    assert module.stopping_name(panel, ["AAA"], (DATES[5], DATES[-1])) is None


def test_a_synthetic_stock_is_a_copy_cut_at_its_stop_date(module, tmp_path):
    folder = tmp_path / "data_wide" / "equity" / "usa" / "daily"
    write_zip(folder / "aaa.zip", [10.0 + index for index in range(len(SESSIONS))], scale=10000)
    stop = module.synthetic_stop(tmp_path, "AAA", SESSIONS[20], "data_wide")
    assert stop["ticker"] == "ZZSTOP" and stop["last"] == SESSIONS[20] and (folder / "zzstop.zip").exists()


def _instrument_world(module, monkeypatch, tmp_path, *, with_dead_coin=True):
    import build_wide_root

    tickers = {f"S{n:03d}": {"member": True, "first": "2013-01-01", "last": "2016-01-01"} for n in range(260)}
    (tmp_path / "data_wide").mkdir()
    (tmp_path / "data_wide" / "wide_manifest.json").write_text(json.dumps({"tickers": tickers}), encoding="utf-8")
    coins = {f"c{n}": {"ticker": f"C{n}USD", "first": "2019-01-01", "last": "2022-01-01"} for n in range(14)}
    coins["dead1"] = {"ticker": "DEAD1USD", "first": "2019-06-01", "last": "2021-06-01"}
    coins["dead2"] = {"ticker": "DEAD2USD", "first": "2019-06-01", "last": "2021-05-01"}
    coins["btc"] = {"ticker": "BTCUSD", "first": "2019-01-01", "last": "2022-01-01"}
    (tmp_path / "data_crypto_wide").mkdir()
    (tmp_path / "data_crypto_wide" / "crypto_wide_manifest.json").write_text(json.dumps({"coins": coins}), encoding="utf-8")
    monkeypatch.setattr(module, "name_side", lambda ticker, names: "A")
    monkeypatch.setattr(module, "coin_side", lambda ticker, names: "A")
    monkeypatch.setattr(module, "project_tickers", lambda config, kind: [])
    monkeypatch.setattr(module, "synthetic_stop", lambda root, ticker, stop_date, data_dir: {"ticker": "ZZSTOP", "first": "2013-01-01", "last": "2015-03-31"})
    monkeypatch.setattr(module, "wide_config_for", lambda config, root, tickers, data_dir: json.loads(json.dumps(config)))
    monkeypatch.setattr(build_wide_root, "wide_config", lambda base, manifest, tickers, keep_project_crypto: json.loads(json.dumps(base)))

    def panel_for(root, config, data_dir):
        names = sorted({asset["ticker"] for asset in config["phase1"]["universe"]["assets"]}) or ["AAA"]
        return Panel(names)

    monkeypatch.setattr(module, "load_market_panel", panel_for)
    monkeypatch.setattr(module, "random_weights", lambda panel, tickers, **kwargs: {DATES[0]: {tickers[0]: 0.1}})
    monkeypatch.setattr(module, "oracle_weights", lambda panel, tickers, **kwargs: {"2020-03-02": {tickers[0]: 0.1, tickers[1]: -0.1}, "2021-04-01": {tickers[0]: 0.1}})


def test_the_instrument_batch_writes_four_plumbing_runs(module, monkeypatch, tmp_path):
    _instrument_world(module, monkeypatch, tmp_path)
    runs = module.make_instrument()
    assert set(runs) == {"v660_bt24", "v660_bt25", "v660_bt26", "v660_bt27"} and runs["v660_bt27"]["died"] == ["DEAD1USD", "DEAD2USD"]
    bt26 = json.loads((module.RUN_CONFIGS / "v660_bt26.json").read_text(encoding="utf-8"))
    assert bt26["phase6"]["risk"]["max_total_drawdown_pct"] == 0.02 and (module.OUT / "instrument_manifest.json").exists()


def _lean_run(path, nav):
    path.mkdir(parents=True)
    stamps = [pd.Timestamp(day, tz="UTC").timestamp() for day in DATES]
    result = {"charts": {"Strategy Equity": {"series": {"Equity": {"values": [[stamp, value] for stamp, value in zip(stamps, nav)]}}}}, "statistics": {"Total Fees": "$12.00"}}
    (path / "1.json").write_text(json.dumps(result), encoding="utf-8")


def test_the_engine_comparison_judges_the_instrument_run_against_its_gates(module, monkeypatch, tmp_path):
    from portfolio.target_weights import write_weight_file
    from v650_instrument import target_path_config

    base = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    (module.WEIGHTS).mkdir(parents=True)
    sha = write_weight_file({DATES[5]: {"AAA": 0.1}}, module.WEIGHTS / "w.csv")
    config = target_path_config(base, weights_path="v660/weights/w.csv", weights_sha256=sha, window=(DATES[0], DATES[-1]))
    (module.RUN_CONFIGS / "v660_x.json").write_text(json.dumps(config), encoding="utf-8")
    (module.RUN_CONFIGS / "v660_x.dataroot").write_text("data_wide\n", encoding="utf-8")
    (tmp_path / "data_wide" / "alternative" / "interest-rate" / "usa").mkdir(parents=True)
    (tmp_path / "data_wide" / "alternative" / "interest-rate" / "usa" / "interest-rate.csv").write_text("date,rate\n", encoding="utf-8")
    nav = pd.Series(1000.0 * (1.0 + np.sin(np.arange(60)) * 0.01).cumprod(), index=DATES)
    monkeypatch.setattr(module, "load_market_panel", lambda root, config, data_dir: Panel(["AAA"]))
    monkeypatch.setattr(module, "load_rate_series", lambda path: ([], []))
    monkeypatch.setattr(module, "simulate_target_weights", lambda weights, panel, cfg, start, end, **kwargs: {"total": nav.pct_change().dropna(), "fees": 12.0, "no_bar_exits": [], "locked_on": None})
    _lean_run(tmp_path / "backtests" / "r", nav.to_numpy())
    report = module.compare("v660_x", tmp_path / "backtests" / "r")
    assert report["passes_r_instr2"] is True and report["fees_within_2pct"] is True and (module.OUT / "instrument_result.json").exists()
    off = tmp_path / "backtests" / "off"
    _lean_run(off, nav.to_numpy() * np.linspace(1.0, 2.0, 60))
    (off / "1.json").write_text(json.dumps({"charts": json.loads((off / "1.json").read_text(encoding="utf-8"))["charts"]}), encoding="utf-8")
    (module.RUN_CONFIGS / "v660_x.dataroot").unlink()
    (tmp_path / "data" / "alternative" / "interest-rate" / "usa").mkdir(parents=True)
    worse = module.compare("v660_x", off)
    assert worse["passes_r_instr2"] is False and worse["lean_fees"] is None and worse["fees_within_2pct"] is None
    again = json.loads((module.OUT / "instrument_result.json").read_text(encoding="utf-8"))
    assert set(again) == {"v660_x"}


def _events(path, fills):
    path.mkdir(parents=True)
    (path / "1.json").write_text("{}", encoding="utf-8")
    events = [{"time": pd.Timestamp(day, tz="UTC").timestamp() + 72000, "status": "filled", "symbolValue": ticker, "fillQuantity": quantity, "fillPrice": 5.0} for day, ticker, quantity in fills]
    (path / "1-order-events.json").write_text(json.dumps(events), encoding="utf-8")


def test_two_runs_are_equal_or_differ_by_named_fills(module, tmp_path):
    _events(tmp_path / "a", [("2019-01-03", "AAA", 10), ("2019-01-04", "BBB", -5)])
    _events(tmp_path / "b", [("2019-01-03", "AAA", 10)])
    report = module.compare_orders(tmp_path / "a", tmp_path / "b")
    assert report["equal"] is False and report["only_first"] and report["only_second"] == []
    assert module.compare_orders(tmp_path / "a", tmp_path / "a")["equal"] is True


def test_the_command_dispatches_each_stage(module, monkeypatch, capsys):
    monkeypatch.setattr(module, "make_instrument", lambda: {"ran": "instrument"})
    monkeypatch.setattr(module, "compare", lambda name, path: {"ran": "compare"})
    monkeypatch.setattr(module, "compare_orders", lambda a, b: {"ran": "orders"})
    for argv, word in ((["instrument"], "instrument"), (["compare", "n", "r"], "compare"), (["orders", "a", "b"], "orders")):
        monkeypatch.setattr(sys, "argv", ["v660_lean", *argv])
        assert module.main() == 0 and word in capsys.readouterr().out
    assert SimpleNamespace is not None
