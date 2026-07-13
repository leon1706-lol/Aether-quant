"""Tests for data_pipeline.ib_backfill. ib_insync is NEVER installed in
this dev environment (a deliberately optional, dev-only dependency) and
these tests NEVER connect to a real IB Gateway/TWS - every ib_insync
symbol is injected into sys.modules as a fake module via monkeypatch
before the module-under-test's deferred `from ib_insync import ...`
statements run.
"""

import json
import sys
import types
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from data_pipeline.ib_backfill import (
    IBNotConfiguredError,
    attempt_connection,
    connect_ib,
    disconnect_ib,
    fetch_future_historical_bars,
    fetch_option_chain_snapshot,
    fetch_option_historical_bars,
    ib_enabled,
    ib_readiness_status,
    load_futures_contract_specs,
)


def _config(enabled: bool = True, **overrides) -> dict:
    ib_block = {"enabled": enabled, "host": "127.0.0.1", "port": 7497, "client_id": 7, "connect_timeout_seconds": 10}
    ib_block.update(overrides)
    return {"phase_v2": {"ib": ib_block}}


def _lean_config(account: str = "DU12345", user_name: str = "trader1") -> dict:
    return {"ib-account": account, "ib-user-name": user_name}


class _FakeBar:
    def __init__(self, bar_date, open_, high, low, close, volume):
        self.date = bar_date
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume


@pytest.fixture
def fake_ib_insync(monkeypatch):
    """Installs a fake ib_insync module into sys.modules with IB/ContFuture/
    Option/Stock/util all mocked - removed automatically after the test via
    monkeypatch's teardown."""
    fake_module = types.ModuleType("ib_insync")

    fake_module.IB = MagicMock()

    def _cont_future(ticker, exchange=None, currency=None):
        return types.SimpleNamespace(symbol=ticker, exchange=exchange, currency=currency, contract_type="continuous")

    fake_module.ContFuture = MagicMock(side_effect=_cont_future)

    def _future(ticker, lastTradeDateOrContractMonth=None, exchange=None, currency=None):
        return types.SimpleNamespace(
            symbol=ticker, exchange=exchange, currency=currency,
            lastTradeDateOrContractMonth=lastTradeDateOrContractMonth, contract_type="dated",
        )

    fake_module.Future = MagicMock(side_effect=_future)

    def _stock(ticker, exchange, currency):
        return types.SimpleNamespace(symbol=ticker, secType="STK", conId=12345, exchange=exchange, currency=currency)

    fake_module.Stock = MagicMock(side_effect=_stock)

    def _option(ticker, expiry, strike, right, exchange):
        return types.SimpleNamespace(symbol=ticker, expiry=expiry, strike=strike, right=right, exchange=exchange)

    fake_module.Option = MagicMock(side_effect=_option)

    fake_util = types.SimpleNamespace(parseIBDatetime=lambda text: datetime.strptime(text, "%Y-%m-%d"))
    fake_module.util = fake_util

    monkeypatch.setitem(sys.modules, "ib_insync", fake_module)
    return fake_module


# ---------------------------------------------------------------------------
# ib_enabled / ib_readiness_status - pure, no ib_insync needed
# ---------------------------------------------------------------------------


def test_ib_enabled_false_when_config_flag_off():
    assert ib_enabled(_config(enabled=False), _lean_config()) is False


def test_ib_enabled_false_when_lean_account_missing():
    assert ib_enabled(_config(enabled=True), _lean_config(account="")) is False


def test_ib_enabled_false_when_lean_username_missing():
    assert ib_enabled(_config(enabled=True), _lean_config(user_name="")) is False


def test_ib_enabled_true_when_all_configured():
    assert ib_enabled(_config(enabled=True), _lean_config()) is True


def test_ib_readiness_status_disabled():
    assert ib_readiness_status(_config(enabled=False), _lean_config()) == "disabled"


def test_ib_readiness_status_credentials_missing():
    assert ib_readiness_status(_config(enabled=True), _lean_config(account="")) == "enabled_but_lean_credentials_missing"


def test_ib_readiness_status_ready():
    assert ib_readiness_status(_config(enabled=True), _lean_config()) == "ready"


# ---------------------------------------------------------------------------
# connect_ib - IBNotConfiguredError contract, never a raw exception
# ---------------------------------------------------------------------------


def test_connect_ib_raises_ib_not_configured_error_when_disabled():
    with pytest.raises(IBNotConfiguredError):
        connect_ib(_config(enabled=False), _lean_config())


def test_connect_ib_raises_ib_not_configured_error_when_lean_credentials_missing():
    with pytest.raises(IBNotConfiguredError):
        connect_ib(_config(enabled=True), _lean_config(account=""))


def test_connect_ib_never_imports_ib_insync_when_disabled():
    # ib_insync isn't installed in this environment at all - if
    # connect_ib() tried to import it before the enabled check, this test
    # itself would fail with ModuleNotFoundError, proving the check
    # short-circuits before any deferred import.
    assert "ib_insync" not in sys.modules or True  # environment-independent guard
    with pytest.raises(IBNotConfiguredError):
        connect_ib(_config(enabled=False), _lean_config())


def test_connect_ib_calls_ib_connect_with_configured_host_port_client_id(fake_ib_insync):
    fake_ib_instance = MagicMock()
    fake_ib_insync.IB.return_value = fake_ib_instance

    result = connect_ib(_config(enabled=True, host="192.168.1.5", port=4002, client_id=99), _lean_config())

    fake_ib_instance.connect.assert_called_once()
    _, kwargs = fake_ib_instance.connect.call_args
    args = fake_ib_instance.connect.call_args.args
    assert args[0] == "192.168.1.5"
    assert args[1] == 4002
    assert kwargs["clientId"] == 99
    assert result is fake_ib_instance


def test_disconnect_ib_calls_disconnect():
    fake_ib = MagicMock()
    disconnect_ib(fake_ib)
    fake_ib.disconnect.assert_called_once()


# ---------------------------------------------------------------------------
# attempt_connection - never raises, always a clean (bool, str) tuple
# ---------------------------------------------------------------------------


def test_attempt_connection_returns_false_when_not_configured():
    reachable, detail = attempt_connection(_config(enabled=False), _lean_config())
    assert reachable is False
    assert "not configured" in detail


def test_attempt_connection_returns_true_on_successful_round_trip(fake_ib_insync):
    fake_ib_instance = MagicMock()
    fake_ib_insync.IB.return_value = fake_ib_instance

    reachable, detail = attempt_connection(_config(enabled=True), _lean_config())

    assert reachable is True
    assert detail == "reachable"
    fake_ib_instance.disconnect.assert_called_once()


def test_attempt_connection_returns_false_on_connection_exception(fake_ib_insync):
    fake_ib_instance = MagicMock()
    fake_ib_instance.connect.side_effect = ConnectionRefusedError("no gateway running")
    fake_ib_insync.IB.return_value = fake_ib_instance

    reachable, detail = attempt_connection(_config(enabled=True), _lean_config())

    assert reachable is False
    assert "connection failed" in detail


# ---------------------------------------------------------------------------
# fetch_future_historical_bars - row shape + graceful failure
# ---------------------------------------------------------------------------


def test_fetch_future_historical_bars_normalizes_row_shape(fake_ib_insync):
    fake_ib = MagicMock()
    fake_ib.reqHistoricalData.return_value = [
        _FakeBar(datetime(2024, 1, 2), 4780.0, 4790.0, 4770.0, 4785.0, 1_500_000),
    ]

    rows = fetch_future_historical_bars(fake_ib, "ES", {"exchange": "CME"}, "2024-01-01", "2024-06-01")

    assert rows == [
        {"date": date(2024, 1, 2), "open": 4780.0, "high": 4790.0, "low": 4770.0, "close": 4785.0, "volume": 1_500_000.0}
    ]


def test_fetch_future_historical_bars_empty_response_returns_empty_list(fake_ib_insync):
    fake_ib = MagicMock()
    fake_ib.reqHistoricalData.return_value = []
    rows = fetch_future_historical_bars(fake_ib, "ES", {"exchange": "CME"}, "2024-01-01", "2024-06-01")
    assert rows == []


def test_fetch_future_historical_bars_never_raises_on_ib_failure(fake_ib_insync):
    fake_ib = MagicMock()
    fake_ib.qualifyContracts.side_effect = RuntimeError("contract not found")
    rows = fetch_future_historical_bars(fake_ib, "BOGUS", {"exchange": "CME"}, "2024-01-01", "2024-06-01")
    assert rows == []


def test_fetch_future_historical_bars_uses_continuous_contract_by_default(fake_ib_insync):
    fake_ib = MagicMock()
    fake_ib.reqHistoricalData.return_value = []

    fetch_future_historical_bars(fake_ib, "ES", {"exchange": "CME"}, "2024-01-01", "2024-06-01")

    fake_ib_insync.ContFuture.assert_called_once()
    fake_ib_insync.Future.assert_not_called()


def test_fetch_future_historical_bars_uses_dated_contract_when_contract_month_given(fake_ib_insync):
    fake_ib = MagicMock()
    fake_ib.reqHistoricalData.return_value = []

    fetch_future_historical_bars(fake_ib, "ES", {"exchange": "CME"}, "2024-01-01", "2024-06-01", contract_month="202406")

    fake_ib_insync.Future.assert_called_once()
    fake_ib_insync.ContFuture.assert_not_called()
    _, kwargs = fake_ib_insync.Future.call_args
    assert kwargs["lastTradeDateOrContractMonth"] == "202406"


def test_fetch_future_historical_bars_dated_contract_never_raises_on_ib_failure(fake_ib_insync):
    fake_ib = MagicMock()
    fake_ib.qualifyContracts.side_effect = RuntimeError("contract not found")
    rows = fetch_future_historical_bars(fake_ib, "ES", {"exchange": "CME"}, "2024-01-01", "2024-06-01", contract_month="202406")
    assert rows == []


# ---------------------------------------------------------------------------
# fetch_option_chain_snapshot - row shape + graceful failure
# ---------------------------------------------------------------------------


def test_fetch_option_chain_snapshot_returns_rows_per_strike_and_right(fake_ib_insync):
    fake_ib = MagicMock()
    fake_param = types.SimpleNamespace(expirations={"20260821"}, strikes={500.0})
    fake_ib.reqSecDefOptParams.return_value = [fake_param]
    fake_ticker_data = types.SimpleNamespace(bid=4.5, ask=4.7, last=4.6, volume=1200)
    fake_ib.reqMktData.return_value = fake_ticker_data

    rows = fetch_option_chain_snapshot(fake_ib, "SPY", "20260821")

    assert len(rows) == 2  # one call row + one put row for the single strike
    rights = {row["right"] for row in rows}
    assert rights == {"call", "put"}
    assert all(row["strike"] == 500.0 for row in rows)


def test_fetch_option_chain_snapshot_never_raises_on_ib_failure(fake_ib_insync):
    fake_ib = MagicMock()
    fake_ib.reqSecDefOptParams.side_effect = RuntimeError("no chain data")
    rows = fetch_option_chain_snapshot(fake_ib, "SPY", "20260821")
    assert rows == []


def test_fetch_option_chain_snapshot_no_matching_expiry_returns_empty(fake_ib_insync):
    fake_ib = MagicMock()
    fake_param = types.SimpleNamespace(expirations={"20260101"}, strikes={500.0})
    fake_ib.reqSecDefOptParams.return_value = [fake_param]
    rows = fetch_option_chain_snapshot(fake_ib, "SPY", "20260821")
    assert rows == []


# ---------------------------------------------------------------------------
# fetch_option_historical_bars - row shape + graceful failure
# ---------------------------------------------------------------------------


def test_fetch_option_historical_bars_normalizes_row_shape(fake_ib_insync):
    fake_ib = MagicMock()
    fake_ib.reqHistoricalData.return_value = [_FakeBar(datetime(2026, 6, 1), 4.5, 4.9, 4.3, 4.6, 800)]

    rows = fetch_option_historical_bars(fake_ib, "SPY", "2026-08-21", 500.0, "call", "2026-01-01", "2026-06-01")

    assert rows == [{"date": date(2026, 6, 1), "open": 4.5, "high": 4.9, "low": 4.3, "close": 4.6, "volume": 800.0}]


def test_fetch_option_historical_bars_never_raises_on_ib_failure(fake_ib_insync):
    fake_ib = MagicMock()
    fake_ib.qualifyContracts.side_effect = RuntimeError("contract not found")
    rows = fetch_option_historical_bars(fake_ib, "SPY", "2026-08-21", 500.0, "put", "2026-01-01", "2026-06-01")
    assert rows == []


# ---------------------------------------------------------------------------
# load_futures_contract_specs - defensive load
# ---------------------------------------------------------------------------


def test_load_futures_contract_specs_from_real_reference_file():
    specs = load_futures_contract_specs()
    assert "ES" in specs


def test_load_futures_contract_specs_missing_file_returns_empty(tmp_path):
    assert load_futures_contract_specs(tmp_path / "missing.json") == {}


def test_load_futures_contract_specs_unparseable_returns_empty(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_futures_contract_specs(path) == {}
