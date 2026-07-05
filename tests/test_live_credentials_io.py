import sys
import types

from execution.live_credentials_io import load_live_credentials


def test_load_live_credentials_falls_back_to_env_vars_when_ib_config_absent(monkeypatch):
    monkeypatch.delitem(sys.modules, "ib_config", raising=False)
    monkeypatch.setenv("AETHER_IB_ACCOUNT", "U1111111")
    monkeypatch.setenv("AETHER_IB_USER_NAME", "envtrader")
    monkeypatch.setenv("AETHER_IB_PASSWORD", "envsecret")
    monkeypatch.setenv("AETHER_IB_TRADING_MODE", "live")

    credentials = load_live_credentials()

    assert credentials == {
        "ib_account": "U1111111",
        "ib_user_name": "envtrader",
        "ib_password": "envsecret",
        "ib_trading_mode": "live",
    }


def test_load_live_credentials_returns_all_empty_when_nothing_configured(monkeypatch):
    monkeypatch.delitem(sys.modules, "ib_config", raising=False)
    for var in ("AETHER_IB_ACCOUNT", "AETHER_IB_USER_NAME", "AETHER_IB_PASSWORD", "AETHER_IB_TRADING_MODE"):
        monkeypatch.delenv(var, raising=False)

    credentials = load_live_credentials()

    assert credentials["ib_account"] == ""
    assert credentials["ib_user_name"] == ""
    assert credentials["ib_password"] == ""
    assert credentials["ib_trading_mode"] == "paper"


def test_load_live_credentials_prefers_ib_config_module_when_importable(monkeypatch):
    fake_ib_config = types.ModuleType("ib_config")
    fake_ib_config.IB_ACCOUNT = "U2222222"
    fake_ib_config.IB_USER_NAME = "modtrader"
    fake_ib_config.IB_PASSWORD = "modsecret"
    fake_ib_config.IB_TRADING_MODE = "live"
    monkeypatch.setitem(sys.modules, "ib_config", fake_ib_config)
    monkeypatch.setenv("AETHER_IB_ACCOUNT", "should_be_ignored")

    credentials = load_live_credentials()

    assert credentials == {
        "ib_account": "U2222222",
        "ib_user_name": "modtrader",
        "ib_password": "modsecret",
        "ib_trading_mode": "live",
    }
