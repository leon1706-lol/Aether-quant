"""Branches that a clean CI checkout reaches differently from a developer's PC (V6.6.6, #359): no built C++ extension, no `openpyxl`, no `webui/dist`, no `ml/evaluation` or Lean market-hours files, another OS. Each test supplies
what the PC happened to hold, so the line is run on every machine."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import aq_cli
import generate_evaluation_report as report_module
from data_pipeline import factor_library
from evaluation import research_round
from inference import exported_model

ROOT = Path(__file__).resolve().parents[1]


def test_the_batched_linear_layer_uses_the_extension_when_there_is_one_and_the_numpy_path_when_it_fails(monkeypatch):
    weights = np.asarray([[[0.5, -0.25], [0.1, 0.3]]])
    current = np.asarray([[1.0, -0.5]])
    bias = np.asarray([[0.1, -0.1]])
    reference = np.einsum("noi,ni->no", weights, current) + bias
    calls = []

    class Working:
        @staticmethod
        def linear_batched(weights_stack, current_vector, bias_stack):
            calls.append("extension")
            return np.einsum("noi,ni->no", weights_stack, current_vector) + bias_stack + 1000.0

    class Broken:
        @staticmethod
        def linear_batched(*arguments):
            raise RuntimeError("the extension is out of date")

    monkeypatch.setattr(exported_model, "_cpp_inference", Working)
    assert exported_model._linear_batched(current, weights, bias) == pytest.approx(reference + 1000.0) and calls == ["extension"]
    monkeypatch.setattr(exported_model, "_cpp_inference", Broken)
    assert exported_model._linear_batched(current, weights, bias) == pytest.approx(reference)
    monkeypatch.setattr(exported_model, "_cpp_inference", None)
    assert exported_model._linear_batched(current, weights, bias) == pytest.approx(reference)


def test_the_other_metrics_table_gives_the_walk_forward_gap_to_the_real_lean_run(monkeypatch):
    monkeypatch.setattr(report_module, "_load_lean_sharpe", lambda: (0.5, "2023-07-01 to 2026-11-02"))
    walk_forward = {"net_performance_by_window": [{"simulation": {"net_sharpe": 1.0}}, {"simulation": {"net_sharpe": 2.0}}, {"simulation": None}]}
    body = report_module._build_other_metrics_markdown({}, walk_forward, None, None)
    assert "Gap: walk-forward − real Lean | +1.000" in body and "Gap: sequence offline" not in body


def test_the_failed_clause_of_a_candidate_is_the_first_gate_it_missed(monkeypatch):
    short = {"live_names": {"median": 3.0}}
    assert research_round._failed_clause(short, min_live_names=10) == "live_names"
    monkeypatch.setattr(research_round, "passes_sharpe_clauses", lambda score: False)
    assert research_round._failed_clause({"live_names": {"median": 30.0}}, min_live_names=10) == "sharpe"
    monkeypatch.setattr(research_round, "passes_sharpe_clauses", lambda score: True)
    assert research_round._failed_clause({"live_names": {"median": 30.0}}, min_live_names=10) == "ic"


def test_the_phase_deflation_inputs_come_from_the_ledgers_and_the_registry_once_a_candidate_exists(monkeypatch, tmp_path):
    evaluation = tmp_path / "ml" / "evaluation"
    (evaluation / "v660").mkdir(parents=True)
    (evaluation / "v650").mkdir(parents=True)
    (evaluation / "trial_registry.json").write_text(json.dumps({"trials": [{"phase": "v600", "median_sharpe": 0.4}, {"phase": "v610", "median_sharpe": 0.6}]}), encoding="utf-8")
    rows = [{"role": "candidate", "window": "v660_selection", "trial_id": name, "annualised_sharpe": sharpe} for name, sharpe in (("a", 0.2), ("b", 0.8))]
    (evaluation / "v660" / "trial_ledger.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(aq_cli, "ML_DIR", tmp_path / "ml")
    result = aq_cli._phase_deflation_inputs()
    assert result["same_window_trials"] == 2 and result["N"] >= 4 and result["floored"] is False


def test_an_aqr_workbook_is_read_below_its_prose_without_a_spreadsheet_library(monkeypatch):
    rows = [["Some prose", None], ["DATE", "USA"], ["01/02/2020", 0.01], ["01/03/2020", None], ["not a date", 0.5], ["01/06/2020", 0.02]]
    monkeypatch.setattr(factor_library.pd, "read_excel", lambda *args, **kwargs: pd.DataFrame(rows))
    series = factor_library.parse_aqr_sheet(b"unused", sheet="Sheet1", name="mkt")
    assert list(series.index) == ["2020-01-02", "2020-01-06"] and series.name == "mkt" and series.tolist() == [0.01, 0.02]


def test_a_built_dashboard_is_served_with_the_client_side_routes_falling_back_to_its_index(monkeypatch, tmp_path):
    from starlette.testclient import TestClient

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>dashboard</html>", encoding="utf-8")
    (dist / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setenv("AQ_WEBUI_DIST", str(dist))
    spec = importlib.util.spec_from_file_location("_api_server_with_dist", ROOT / "monitoring" / "api_server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client = TestClient(module.app)
    assert "dashboard" in client.get("/").text and "dashboard" in client.get("/accounts/desk").text and client.get("/app.js").text == "console.log(1)"
    assert client.get("/missing.png").status_code == 404
