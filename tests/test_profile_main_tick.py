"""scripts/profile_main_tick.py (V6.6.6): the per-tick feature path timed outside Lean. `import main` is served a stand-in
algorithm here (a meta-path finder), so the timing loop, the bar reader and the CLI run without models or Lean."""

from __future__ import annotations

import datetime
import importlib.abc
import importlib.util
import json
import sys
import types
import zipfile
from collections import defaultdict, deque

import pytest

from script_loader import load_script


def _fake_main_module():
    module = types.ModuleType("main")
    module.ALT_DATA_PUBLICATION_LAG_DAYS = {"DGS10": 1}
    module.CROSS_ASSET_SENSITIVITY_DRIVERS = {"rates": "DGS10"}
    module.series_value_asof = lambda series, day, lag: 4.2 if series else None

    class AetherQuantAlgorithm:
        def __init__(self):
            self.symbols = ["SPY", "BTCUSD"]
            self.asset_lookup = {"SPY": {"ticker": "SPY"}, "BTCUSD": {"ticker": "BTCUSD"}}
            self.phase1 = {"features": {}}
            self.fred_series = {"DGS10": [1]}
            self.symbol_windows = defaultdict(list)
            self.symbol_long_windows = defaultdict(list)
            self.symbol_treasury_10yr_history = defaultdict(list)
            self.symbol_sensitivity_driver_history = defaultdict(lambda: {"rates": deque()})
            self.model_inputs = 0

        def initialize(self):
            if "Resolution" not in module.__dict__:
                raise NameError("name 'Resolution' is not defined")

        def _ensure_ready(self):
            pass

        def _build_topology_payload(self):
            return {"nodes": [{"symbol": "SPY"}]}

        def _build_macro_payload(self):
            return {}

        _build_bond_payload = _build_alt_data_payload = _build_sensitivity_driver_levels = _build_macro_payload

        def _build_model_input(self, symbol, node):
            self.model_inputs += 1

    module.AetherQuantAlgorithm = AetherQuantAlgorithm
    return module


class _MainFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, module):
        self.module = module

    def find_spec(self, name, path=None, target=None):
        return importlib.util.spec_from_loader(name, self) if name == "main" else None

    def create_module(self, spec):
        return self.module

    def exec_module(self, module):
        pass


@pytest.fixture
def fake_main(monkeypatch):
    module = _fake_main_module()
    finder = _MainFinder(module)
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])
    monkeypatch.delitem(sys.modules, "main", raising=False)
    monkeypatch.delitem(sys.modules, "AlgorithmImports", raising=False)
    yield module
    sys.modules.pop("main", None)
    sys.modules.pop("AlgorithmImports", None)


def _zip(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(path.stem + ".csv", "\n".join(rows) + "\n")


def _tree(root):
    days = [datetime.date(2024, 6, 1) + datetime.timedelta(days=offset) for offset in range(28)]
    _zip(root / "data" / "spy.zip", [f"{day:%Y%m%d} 00:00,1000000,1010000,990000,1005000,500" for day in days if day.day != 19])  # a missing bar
    _zip(root / "data" / "btc.zip", [f"{day:%Y%m%d} 00:00,60000,61000,59000,60500" for day in days])
    _zip(root / "data" / "eur.zip", [f"{day:%Y%m%d} 00:00,1.08,1.09,1.07,1.085,9" for day in days])
    assets = [{"ticker": "SPY", "security_type": "equity", "data_path": "data/spy.zip"}, {"ticker": "BTCUSD", "security_type": "crypto", "data_path": "data/btc.zip"}]
    (root / "config.json").write_text(json.dumps({"phase1": {"universe": {"assets": assets}}}), encoding="utf-8")
    return assets


def test_read_bars_scales_equity_and_drops_forex_volume(tmp_path, monkeypatch):
    module = load_script("profile_main_tick")
    _tree(tmp_path)
    monkeypatch.setattr(module, "ROOT_DIR", tmp_path)
    spy = module.read_bars({}, {"security_type": "equity", "data_path": "data/spy.zip"})
    assert spy[0] == (datetime.date(2024, 6, 1), {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 500.0})
    assert module.read_bars({}, {"security_type": "forex", "data_path": "data/eur.zip"})[0][1]["volume"] == 0.0
    assert module.read_bars({}, {"security_type": "crypto", "data_path": "data/btc.zip"})[0][1]["volume"] == 0.0


def test_the_permissive_stub_mocks_public_names_only():
    module = load_script("profile_main_tick")
    stub = module._PermissiveQCAlgorithm()
    assert stub.SetCash is stub.SetCash
    with pytest.raises(AttributeError):
        stub._private  # noqa: B018


@pytest.mark.parametrize("extra", [["--cprofile", "--scalar-beta", "--repeat", "2"], []])
def test_main_times_each_stage(tmp_path, monkeypatch, capsys, fake_main, extra):
    module = load_script("profile_main_tick")
    _tree(tmp_path)
    monkeypatch.setattr(module, "ROOT_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)
    report_path = tmp_path / "report.json"
    monkeypatch.setattr(module.sys, "argv", ["x", "--warm", "5", "--days", "3", "--end", "2024-06-20", "--json", str(report_path), *extra])
    if "--scalar-beta" in extra:
        import features.bond_features as bond_features

        monkeypatch.setattr(bond_features, "_VECTOR_BETA_MIN_LENGTH", bond_features._VECTOR_BETA_MIN_LENGTH)
    assert module.main() == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["days"] == 3 and report["symbols"] == 2 and report["model_input_calls"] == 6
    assert set(report["ms_per_day"]) == {"topology_payload", "macro_bond_alt_payloads", "build_model_input"}
    assert ("cumulative" in capsys.readouterr().out) is ("--cprofile" in extra)


def test_a_name_error_that_is_not_a_missing_lean_name_is_raised(tmp_path, monkeypatch, fake_main):
    module = load_script("profile_main_tick")
    monkeypatch.setattr(module, "ROOT_DIR", tmp_path)
    monkeypatch.chdir(tmp_path)  # build_algorithm moves into ROOT_DIR, and the monkeypatch puts the directory back
    fake_main.AetherQuantAlgorithm.initialize = lambda self: (_ for _ in ()).throw(NameError("something else"))
    with pytest.raises(NameError, match="something else"):
        module.build_algorithm(datetime.datetime(2024, 1, 2))
