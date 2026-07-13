from datetime import date
from unittest.mock import patch

from monitoring.assets_status import build_assets_status


def _config(assets: list[dict] | None = None, futures_enabled: bool = False, options_enabled: bool = False) -> dict:
    return {
        "phase_v2": {"futures_risk": {"enabled": futures_enabled}, "options_risk": {"enabled": options_enabled}},
        "phase1": {"universe": {"assets": assets or []}},
    }


def test_build_assets_status_reports_ib_disabled_by_default():
    with patch("monitoring.assets_status.load_futures_contract_specs", return_value={}), patch(
        "monitoring.assets_status.load_cached_fred_series", return_value={}
    ):
        report = build_assets_status(_config(), {"ib-account": "", "ib-user-name": ""})

    assert report["ib_status"] == "disabled"
    assert report["futures_risk_enabled"] is False
    assert report["options_risk_enabled"] is False


def test_build_assets_status_reports_ready_when_ib_enabled_and_credentials_present():
    config = _config()
    config["phase_v2"]["ib"] = {"enabled": True}
    with patch("monitoring.assets_status.load_futures_contract_specs", return_value={}), patch(
        "monitoring.assets_status.load_cached_fred_series", return_value={}
    ):
        report = build_assets_status(config, {"ib-account": "DU123", "ib-user-name": "user"})

    assert report["ib_status"] == "ready"


def test_build_assets_status_futures_contract_specs_counted_and_sorted():
    with patch(
        "monitoring.assets_status.load_futures_contract_specs", return_value={"NQ": {}, "ES": {}, "CL": {}}
    ), patch("monitoring.assets_status.load_cached_fred_series", return_value={}):
        report = build_assets_status(_config(), {})

    assert report["futures_contract_specs_loaded"] == 3
    assert report["futures_contract_specs_tickers"] == ["CL", "ES", "NQ"]


def test_build_assets_status_fred_cache_most_recent_date_across_series():
    fred_series = {
        "treasury_10yr": [{"date": date(2026, 6, 1), "value": 0.04}, {"date": date(2026, 7, 1), "value": 0.041}],
        "treasury_2yr": [{"date": date(2026, 6, 15), "value": 0.038}],
    }
    with patch("monitoring.assets_status.load_futures_contract_specs", return_value={}), patch(
        "monitoring.assets_status.load_cached_fred_series", return_value=fred_series
    ):
        report = build_assets_status(_config(), {})

    assert report["fred_cache_series_count"] == 2
    assert report["fred_cache_most_recent_date"] == "2026-07-01"


def test_build_assets_status_empty_fred_cache_reports_none():
    with patch("monitoring.assets_status.load_futures_contract_specs", return_value={}), patch(
        "monitoring.assets_status.load_cached_fred_series", return_value={}
    ):
        report = build_assets_status(_config(), {})

    assert report["fred_cache_most_recent_date"] is None


def test_build_assets_status_counts_configured_futures_and_options_assets():
    assets = [
        {"ticker": "ES", "asset_class": "future"},
        {"ticker": "CL", "security_type": "future"},
        {"ticker": "SPY_500C", "asset_class": "option"},
        {"ticker": "AAPL", "security_type": "equity"},
    ]
    with patch("monitoring.assets_status.load_futures_contract_specs", return_value={}), patch(
        "monitoring.assets_status.load_cached_fred_series", return_value={}
    ):
        report = build_assets_status(_config(assets), {})

    assert report["configured_futures_assets"] == 2
    assert report["configured_options_assets"] == 1


def test_build_assets_status_never_raises_on_empty_config():
    with patch("monitoring.assets_status.load_futures_contract_specs", return_value={}), patch(
        "monitoring.assets_status.load_cached_fred_series", return_value={}
    ):
        report = build_assets_status({}, {})

    assert report["configured_futures_assets"] == 0
    assert report["configured_options_assets"] == 0
