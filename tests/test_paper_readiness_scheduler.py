"""Tests for execution.paper_readiness_scheduler (Phase 7 of the 5/10 ->
9/10 roadmap).

Conventions: no test classes, module-level helpers, _pg_conn constructor
injection mirroring performance/trigger_worker.py::TriggerWorker's test
style and tests/test_paper_readiness_report.py's conn-mock shape.
"""

import json
from unittest.mock import MagicMock

from execution.paper_readiness_scheduler import PaperReadinessScheduler


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


def test_run_once_writes_report_file(tmp_path):
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchall.return_value = [(_sample_event(100.0),), (_sample_event(101.0),)]
    report_path = tmp_path / "paper_readiness_report.json"
    scheduler = PaperReadinessScheduler(
        config=_confirmed_config(), report_path=report_path, _pg_conn=conn_mock
    )

    view = scheduler.run_once()

    assert view["ready"] is True
    written = json.loads(report_path.read_text(encoding="utf-8"))
    assert written["ready"] is True


def test_run_once_reflects_not_ready_state(tmp_path):
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchall.return_value = []
    report_path = tmp_path / "paper_readiness_report.json"
    scheduler = PaperReadinessScheduler(
        config=_confirmed_config(min_observations=500), report_path=report_path, _pg_conn=conn_mock
    )

    view = scheduler.run_once()

    assert view["ready"] is False
    written = json.loads(report_path.read_text(encoding="utf-8"))
    assert written["ready"] is False


def test_run_once_never_touches_paper_trading_config_flags(tmp_path):
    # Hard boundary (Phase 7): this scheduler only regenerates the report -
    # it must never mutate the config dict it was given, especially not
    # live_data_provider_configured/manual_review_confirmed.
    conn_mock, cur_mock = _make_conn_mock()
    cur_mock.fetchall.return_value = [(_sample_event(100.0),)]
    config = _confirmed_config()
    original_paper_trading_config = dict(config["phase_v2"]["paper_trading"])
    scheduler = PaperReadinessScheduler(config=config, report_path=tmp_path / "report.json", _pg_conn=conn_mock)

    scheduler.run_once()

    assert config["phase_v2"]["paper_trading"] == original_paper_trading_config


def test_close_does_not_close_injected_connection(tmp_path):
    conn_mock, _cur_mock = _make_conn_mock()
    scheduler = PaperReadinessScheduler(
        config=_confirmed_config(), report_path=tmp_path / "report.json", _pg_conn=conn_mock
    )

    scheduler.close()

    conn_mock.close.assert_not_called()
