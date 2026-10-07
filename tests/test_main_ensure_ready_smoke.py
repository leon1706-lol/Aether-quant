"""Smoke test: main.py's `initialize()` + `_ensure_ready()` against the REAL config and model artifacts.

V5.5.0's first backtest attempt died on bar 1 with `type object 'datetime.time' has no attribute
'perf_counter'`: `from AlgorithmImports import *` exports Lean's `time` (datetime.time), silently
replacing the stdlib module main.py had imported. The wiring tests never ran `_ensure_ready()` (it loads
every model and derives ~hundreds of config values), and their stub did not export `time`, so nothing
caught it. This test closes both gaps: the stub below exports `time` exactly as Lean does, and the whole
first-bar setup path runs against what `aq backtest` would really load.

Skipped when `ml/` artifacts or `config.json` are absent (a fresh CI checkout - ml/ is gitignored).
Everything not stdlib is faked permissively; no Lean, Docker, Redis or Postgres is needed (the queues
degrade with a connection warning, exactly as they do in the test suite elsewhere).

Conventions match the rest of this repo: no test classes, module-level helpers."""

from __future__ import annotations

import datetime
import re
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("config.json", "ml/feature_schema.json", "ml/scaler_stats.json")

pytestmark = pytest.mark.skipif(
    not all((ROOT / name).exists() for name in REQUIRED),
    reason="needs config.json and trained ml/ artifacts (gitignored, absent on a fresh checkout)",
)


class _PermissiveQCAlgorithm:
    """Stands in for QCAlgorithm's very large public surface: any PUBLIC attribute is a MagicMock.
    Private attributes must really be set by main.py, so a typo there still fails."""

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        value = MagicMock(name=name)
        object.__setattr__(self, name, value)
        return value


@pytest.fixture(scope="module")
def algorithm():
    stub = types.ModuleType("AlgorithmImports")
    stub.QCAlgorithm = _PermissiveQCAlgorithm
    stub.time = datetime.time  # Lean's star import exports this and shadows the stdlib `time` module
    patcher = pytest.MonkeyPatch()
    patcher.setitem(sys.modules, "AlgorithmImports", stub)
    patcher.delitem(sys.modules, "main", raising=False)
    patcher.chdir(ROOT)
    import main  # noqa: PLC0415 - must come after the stub is installed

    instance = main.AetherQuantAlgorithm()
    instance._write_state = lambda *args, **kwargs: None  # never write visualization/state.json from a test
    instance.Debug = lambda message: None
    instance.Log = lambda message: None
    instance.Time = datetime.datetime(2019, 1, 2)

    for _ in range(80):  # Lean-only names main.py reaches during setup get a stand-in on first NameError
        try:
            if "_initialized_once" not in instance.__dict__:
                instance.initialize()
                instance.__dict__["_initialized_once"] = True
            instance._ensure_ready()
            break
        except NameError as error:
            match = re.search(r"name '(\w+)' is not defined", str(error))
            if not match:
                raise
            main.__dict__[match.group(1)] = MagicMock(name=match.group(1))
    else:  # pragma: no cover
        raise AssertionError("setup kept raising NameError")
    yield instance
    sys.modules.pop("main", None)
    patcher.undo()


def test_first_bar_setup_completes_with_lean_exporting_its_own_time(algorithm):
    assert algorithm.__dict__["_ready"] is True


def test_the_v550_config_blocks_were_read_into_real_values(algorithm):
    assert algorithm.legacy_sleeve_config["enabled"] is True
    assert 0.0 < algorithm.legacy_sleeve_config["max_weight_per_name"] <= algorithm.legacy_sleeve_config["max_gross_exposure"]
    assert algorithm.book_weight_floor_fraction == pytest.approx(0.5)
    assert algorithm.forex_cap_to_book_weight is True
    assert algorithm.max_forex_short_exposure <= algorithm.max_short_exposure
    assert algorithm._liquidity_slippage_source == "per_side"
    assert isinstance(algorithm._timing_probe.summary()["sections"], dict)  # empty while the probe flag is off


def test_the_new_per_symbol_state_containers_exist_before_the_first_bar(algorithm):
    for name in ("_last_formed_book_allocations", "_book_owned_symbols", "_limit_order_kept_flag", "_crypto_bar_probe_counts"):
        assert name in algorithm.__dict__, name
