from datetime import date
from unittest.mock import patch

from monitoring.assets_status import build_assets_status, build_assets_status_from_disk


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


def test_build_assets_status_from_disk_degrades_gracefully_when_lean_json_missing(tmp_path):
    """lean.json is deliberately excluded from the published Docker image
    (development/Problems.md #42) and only reaches a running engine
    container via a volume mount - a misconfigured deployment missing that
    mount must not 500 the /api/assets-status route, just report IB as not
    ready (same as if lean.json existed but had no credential fields)."""
    config_path = tmp_path / "config.json"
    config_path.write_text('{"phase_v2": {"ib": {"enabled": true}}, "phase1": {"universe": {"assets": []}}}', encoding="utf-8")
    missing_lean_json_path = tmp_path / "lean.json"  # deliberately never created

    with patch("monitoring.assets_status.CONFIG_PATH", config_path), patch(
        "monitoring.assets_status.LEAN_JSON_PATH", missing_lean_json_path
    ), patch("monitoring.assets_status.load_futures_contract_specs", return_value={}), patch(
        "monitoring.assets_status.load_cached_fred_series", return_value={}
    ):
        report = build_assets_status_from_disk()

    assert report["ib_status"] == "enabled_but_lean_credentials_missing"


def test_sleeve_status_reads_config_and_merges_the_runtime_guard_state():
    from monitoring.assets_status import build_sleeve_status

    config = {"phase_v2": {
        "forex_risk": {"enabled": True}, "forex_sleeve": {"enabled": True, "signal": "carry", "gross_budget": 0.1},
        "bond_sleeve": {"enabled": True, "signal": "ts_momentum", "gross_budget": 0.3},
        "class_weight_caps": {"crypto": {"enabled": True, "per_name_cap": 0.01, "class_gross_cap": 0.05}},
        "sleeve_guards": {"bond": {"enabled": True, "max_loss_fraction_nav": 0.01, "lookback_bars": 60, "cooldown_bars": 60}},
        "dynamic_risk": {"rl_sizing_enabled": True, "min_rl_multiplier": 0.9, "max_rl_multiplier": 1.1, "rl_shadow_guard": {"enabled": True}},
        "venue_listing_guard": {"enabled": True}, "topology_learning": {"enabled": True},
    }}
    status = build_sleeve_status(config, {"bond": {"active": False, "reason": "sleeve_loss_guard_tripped"}})
    assert status["forex_sleeve"]["enabled"] is True and status["forex_sleeve"]["signal"] == "carry"
    assert status["bond_sleeve"]["guard"]["enabled"] is True
    assert status["bond_sleeve"]["guard"]["runtime"] == {"active": False, "reason": "sleeve_loss_guard_tripped"}
    assert status["forex_sleeve"]["guard"]["enabled"] is False and status["forex_sleeve"]["guard"]["runtime"] is None
    assert status["crypto_graduates"]["per_name_cap"] == 0.01
    assert status["rl_sizing"] == {"enabled": True, "range": [0.9, 1.1], "shadow_guard": True}
    assert status["venue_listing_guard"] is True and status["learned_topology"] is True


def test_sleeve_status_of_an_empty_config_reads_as_disabled():
    from monitoring.assets_status import build_sleeve_status

    status = build_sleeve_status({})
    assert status["forex_sleeve"]["enabled"] is False and status["bond_sleeve"]["enabled"] is False
    assert status["rl_sizing"]["enabled"] is False and status["learned_topology"] is False


def test_assets_status_report_carries_the_sleeves_block():
    with patch("monitoring.assets_status.load_futures_contract_specs", return_value={}), patch(
        "monitoring.assets_status.load_cached_fred_series", return_value={}
    ):
        report = build_assets_status(_config(), {}, {"forex": {"active": True}})
    assert set(report["sleeves"]) >= {"forex_sleeve", "bond_sleeve", "crypto_graduates", "rl_sizing"}
    assert report["sleeves"]["forex_sleeve"]["guard"]["runtime"] == {"active": True}


def test_sleeve_status_shows_the_cash_sweep():
    from monitoring.assets_status import build_sleeve_status

    status = build_sleeve_status({"phase_v2": {"cash_sweep": {"enabled": True, "ticker": "BIL", "max_weight": 0.9,
                                                              "margin_leverage": 2.0, "exclude_from_risk_controls": True}}})
    assert status["cash_sweep"] == {"enabled": True, "ticker": "BIL", "max_weight": 0.9, "margin_leverage": 2.0,
                                    "exclude_from_risk_controls": True}
    assert build_sleeve_status({})["cash_sweep"]["enabled"] is False
