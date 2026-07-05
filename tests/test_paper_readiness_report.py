import json
from unittest.mock import MagicMock

from execution.paper_readiness_report import build_paper_readiness_view, write_paper_readiness_file


def _make_conn_mock():
    conn_mock = MagicMock()
    cur_mock = MagicMock()
    conn_mock.cursor.return_value.__enter__.return_value = cur_mock
    conn_mock.cursor.return_value.__exit__.return_value = False
    return conn_mock, cur_mock


def _sample_event(total_value: float) -> dict:
    return {
        "mode": "observation",
        "portfolio": {"simulated": True, "total_value": total_value},
        "market_analysis": {"reasons": []},
    }


def _confirmed_config(**thresholds_overrides) -> dict:
    thresholds = {
        "min_observations": 2,
        "min_simulated_sharpe": -10.0,
        "max_simulated_drawdown_floor": -0.99,
        "max_single_rejection_reason_share": 1.0,
    }
    thresholds.update(thresholds_overrides)
    return {
        "phase_v2": {
            "paper_trading": {
                "brokerage": "lean_paper_brokerage",
                "live_data_provider_configured": True,
                "manual_review_confirmed": True,
                "readiness_thresholds": thresholds,
            }
        }
    }


def test_build_paper_readiness_view_reports_ready_when_all_checks_pass():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchall.return_value = [
        (_sample_event(100.0),),
        (_sample_event(101.0),),
        (_sample_event(102.0),),
    ]

    view = build_paper_readiness_view(conn_mock, _confirmed_config())

    assert view["ready"] is True
    assert view["broker_config_present"] is True
    assert view["blocking_reasons"] == []
    assert view["observation_summary"]["count_observations"] == 3


def test_build_paper_readiness_view_reports_not_ready_when_broker_config_missing():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchall.return_value = [(_sample_event(100.0),), (_sample_event(101.0),)]
    config = _confirmed_config()
    config["phase_v2"]["paper_trading"]["manual_review_confirmed"] = False

    view = build_paper_readiness_view(conn_mock, config)

    assert view["ready"] is False
    assert view["broker_config_present"] is False
    assert "paper_broker_config_missing_manual_review" in view["blocking_reasons"]


def test_build_paper_readiness_view_reports_not_ready_on_insufficient_observations():
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchall.return_value = []

    view = build_paper_readiness_view(conn_mock, _confirmed_config(min_observations=500))

    assert view["ready"] is False
    assert "observation_count" in view["blocking_reasons"]


def test_write_paper_readiness_file_writes_json(tmp_path):
    view = {"ready": True, "checks": {}, "blocking_reasons": []}
    path = tmp_path / "grafana" / "paper_readiness_report.json"

    write_paper_readiness_file(view, path)

    assert json.loads(path.read_text(encoding="utf-8")) == view
