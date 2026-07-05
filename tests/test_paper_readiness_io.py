import json
import os
from unittest.mock import MagicMock

from execution.paper_readiness_io import fetch_observation_mode_events, read_paper_trading_config


def _bump_mtime(path) -> None:
    current = os.stat(path).st_mtime
    os.utime(path, (current + 1.0, current + 1.0))


def _make_conn_mock():
    conn_mock = MagicMock()
    cur_mock = MagicMock()
    conn_mock.cursor.return_value.__enter__.return_value = cur_mock
    conn_mock.cursor.return_value.__exit__.return_value = False
    return conn_mock, cur_mock


def _write_config(path, phase_v2_overrides=None) -> None:
    config = {
        "name": "Aether Quant",
        "phase_v2": {**(phase_v2_overrides or {})},
    }
    path.write_text(json.dumps(config, indent=4), encoding="utf-8")


def test_read_paper_trading_config_returns_empty_dict_when_config_missing(tmp_path):
    assert read_paper_trading_config(tmp_path / "does_not_exist.json") == {}


def test_read_paper_trading_config_returns_empty_dict_when_key_absent(tmp_path):
    config_path = tmp_path / "config.json"
    _write_config(config_path)

    assert read_paper_trading_config(config_path) == {}


def test_read_paper_trading_config_returns_the_nested_block(tmp_path):
    config_path = tmp_path / "config.json"
    _write_config(
        config_path,
        phase_v2_overrides={"paper_trading": {"brokerage": "lean_paper_brokerage", "manual_review_confirmed": True}},
    )

    result = read_paper_trading_config(config_path)

    assert result == {"brokerage": "lean_paper_brokerage", "manual_review_confirmed": True}


def test_fetch_observation_mode_events_filters_by_mode_and_returns_oldest_first():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchall.return_value = [({"symbol": "oldest"},), ({"symbol": "newest"},)]

    events = fetch_observation_mode_events(conn_mock, limit=100)

    sql, params = cur_mock.execute.call_args.args
    assert "mode = %(mode)s" in sql
    assert params["mode"] == "observation"
    assert params["limit"] == 100
    assert events == [{"symbol": "oldest"}, {"symbol": "newest"}]


def test_read_paper_trading_config_picks_up_a_later_change_after_mtime_updates(tmp_path):
    """Regression guard for the mtime-gated cache in execution/config_cache.py."""
    config_path = tmp_path / "config.json"
    _write_config(config_path, phase_v2_overrides={"paper_trading": {"brokerage": "lean_paper_brokerage"}})
    assert read_paper_trading_config(config_path) == {"brokerage": "lean_paper_brokerage"}

    _write_config(config_path, phase_v2_overrides={"paper_trading": {"brokerage": "interactive_brokers"}})
    _bump_mtime(config_path)

    assert read_paper_trading_config(config_path) == {"brokerage": "interactive_brokers"}


def test_fetch_observation_mode_events_decodes_json_string_payloads():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchall.return_value = [(json.dumps({"symbol": "AAPL"}),)]

    events = fetch_observation_mode_events(conn_mock)

    assert events == [{"symbol": "AAPL"}]
