"""scripts/crypto_graduation_research.py's runtime (V6.6.6, #359): the class caps, one eligibility-limited as-live run, and the whole command in both of R-SLEEVE's
branches (a capped configuration passes R-GATE, or the graduates ship at the minimum cap), with the harness and the gate stood in."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from script_loader import load_script

CRYPTO = ["BTCUSD", "LTCUSD", "ETHUSD", "SOLUSD", "XRPUSD"]


@pytest.fixture
def module(monkeypatch, tmp_path):
    research = load_script("crypto_graduation_research")
    (tmp_path / "ml" / "evaluation").mkdir(parents=True)
    monkeypatch.setattr(research, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(research, "summarize", lambda result: {"net_sharpe": result.sharpe, "net_total_return": 0.1, "net_max_drawdown": -0.05})
    return research


class Harness:
    def __init__(self, split, use_cache, dataset_path):
        self.split = split
        self.asset_class_by_ticker = {ticker: "crypto" for ticker in CRYPTO} | {"SPY": "equity"}
        self.metadata = {ticker: {"trading_eligible": ticker != "XRPUSD"} for ticker in CRYPTO} | {"SPY": {"trading_eligible": True}}
        self.frame = pd.DataFrame({"ticker": CRYPTO[:4] + ["SPY"]})
        self.core_crypto = frozenset({"BTCUSD"})
        self._mechanisms = {"stale": 1}
        self.venue_listing_dates = None
        self.runs = []

    def as_live(self, candidate_metadata_by_ticker, class_weight_caps):
        eligible = {ticker for ticker, entry in candidate_metadata_by_ticker.items() if entry["trading_eligible"] and ticker in CRYPTO}
        self.runs.append((eligible, class_weight_caps))
        return SimpleNamespace(sharpe=0.1 + 0.05 * len(eligible) + (0.02 if class_weight_caps else 0.0) + (0.01 if self.split == "validation" else 0.0))


def test_caps_exempt_the_core_names(module):
    caps = module.caps_for(0.02, 0.1)
    assert caps and "crypto" in str(caps)


def test_a_run_makes_exactly_the_named_crypto_names_selectable(module):
    harness = Harness("backtest", True, None)
    result = module.run(harness, eligible={"BTCUSD", "ETHUSD"}, caps=None)
    assert harness.runs == [({"BTCUSD", "ETHUSD"}, None)] and harness._mechanisms == {} and {"BTCUSD", "ETHUSD"} <= set(harness.core_crypto) and result.sharpe > 0
    module.run(harness, eligible=set(), caps=module.caps_for(0.01, 0.05))
    assert harness.runs[-1][0] == set() and harness.runs[-1][1]


def _command(module, monkeypatch, tmp_path, *, passes, hurts=()):
    import evaluation.readme_research as readme_research

    created = []
    monkeypatch.setattr(module, "AsLiveHarness", lambda split, use_cache, dataset_path: created.append(Harness(split, use_cache, dataset_path)) or created[-1])
    refreshed = []
    monkeypatch.setattr(readme_research, "refresh_readme_best_effort", lambda: refreshed.append(True))

    def gate(base, variant):
        wins = passes(base, variant)
        return {"passes_r_gate": wins}

    monkeypatch.setattr(module, "r_gate", gate)
    monkeypatch.setattr(sys, "argv", ["crypto_graduation_research", "--no-cache", "--dataset-validation", "v.csv"])
    assert module.main() == 0
    assert refreshed == [True] and [h.split for h in created] == ["backtest", "validation"]
    return json.loads((tmp_path / "ml" / "evaluation" / "crypto_graduation_research.json").read_text(encoding="utf-8"))


def test_a_capped_configuration_that_passes_r_gate_ships_at_its_researched_cap(module, monkeypatch, tmp_path, capsys):
    written = _command(module, monkeypatch, tmp_path, passes=lambda base, variant: variant["backtest"]["net_sharpe"] > base["backtest"]["net_sharpe"])
    assert written["graduates"] == ["ETHUSD", "SOLUSD"] and set(written["results"]) >= {"core_only", "all_uncapped", "capped 0.01/0.05", "capped 0.04/0.1"}
    assert written["decision"]["branch"] in ("edge_pass", "trade_anyway_minimum_cap") and set(written["leave_one_out"]) == {"ETHUSD", "SOLUSD"}
    assert "decision:" in capsys.readouterr().out


def test_an_edge_pass_names_the_best_validation_configuration(module, monkeypatch, tmp_path):
    written = _command(module, monkeypatch, tmp_path, passes=lambda base, variant: True)
    decision = written["decision"]
    assert decision["branch"] == "edge_pass" and decision["config"].startswith("capped") and decision["per_name_cap"] > 0 and decision["passing"] and set(written["removal_would_pass_r_gate"]) == {"ETHUSD", "SOLUSD"}


def test_with_no_passing_configuration_the_graduates_ship_at_the_minimum_cap(module, monkeypatch, tmp_path):
    written = _command(module, monkeypatch, tmp_path, passes=lambda base, variant: False)
    decision = written["decision"]
    assert decision["branch"] == "trade_anyway_minimum_cap" and decision["per_name_cap"] == 0.01 and decision["class_gross_cap"] == 0.05 and decision["loss_guard"] is True
    assert decision["best_capped_config"].startswith("capped") and written["removal_would_pass_r_gate"] == []
