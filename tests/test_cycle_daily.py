"""scripts/cycle_daily.py and scripts/cycle_decide.py, on fixtures with no network."""

from __future__ import annotations

import datetime
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from cycle_daily import latest_decision, marks_for, run, summary_lines  # noqa: E402
from cycle_decide import read_weights, write_decision  # noqa: E402

from evaluation.forward_ledger import read_ledger  # noqa: E402
from evaluation.generation_ledger import ALLOCATION_ID, judge_generations  # noqa: E402
from evaluation.generation_registry import Generation, load_registry, save_registry  # noqa: E402

DAYS = [day.strftime("%Y-%m-%d") for day in pd.bdate_range("2024-01-02", periods=320)]
TODAY = DAYS[-1]
NOW = datetime.datetime.fromisoformat(f"{TODAY}T22:45:00+00:00")
DEFINITION = {
    "id": "t3", "kind": "time_series", "family": "crypto_trend", "universe": ["crypto"], "rebalance_every": 5, "params": {"lookback_a": 20, "lookback_b": 60, "lookback_c": 120},
    "tickers": ["BTCUSD", "ETHUSD"], "asset_class": {"BTCUSD": "crypto", "ETHUSD": "crypto"}, "anchor_date": DAYS[-3], "cost_class": "crypto", "initial_weights": {"BTCUSD": 0.05}, "data_sources": ["coinbase"],
}
G1 = Generation(id="g1", kind="rule", tier="installed", stage="active", born=DAYS[0], procedure_sha256="p", definition=DEFINITION)


def _candles(seed: int) -> list:
    closes = 100.0 * np.exp(np.cumsum(np.random.default_rng(seed).normal(0.001, 0.02, len(DAYS))))
    return [[int(datetime.datetime.fromisoformat(f"{day}T00:00:00+00:00").timestamp()), 0, 0, 0, float(close), 0] for day, close in zip(reversed(DAYS), reversed(closes))]


def _yahoo(seed: int, days=DAYS) -> dict:
    closes = 100.0 * np.exp(np.cumsum(np.random.default_rng(seed).normal(0.0005, 0.01, len(days))))
    stamps = [int(datetime.datetime.fromisoformat(f"{day}T20:00:00+00:00").timestamp()) for day in days]
    return {"chart": {"result": [{"timestamp": stamps, "indicators": {"quote": [{"close": [float(value) for value in closes]}], "adjclose": [{"adjclose": [float(value) for value in closes]}]}, "meta": {}}]}}


def _get_json(url: str):
    if "coinbase" in url:
        return _candles(1 if "BTC" in url else 2)
    return _yahoo(3 if "SPY" in url else 4 if "AGG" in url else 5)


@pytest.fixture
def world(tmp_path):
    registry = tmp_path / "registry.json"
    save_registry(registry, {"g1": G1})
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"enabled": False, "guard_max_drawdown": 0.15, "glide": {"glide_sessions": 252}}), encoding="utf-8")
    return registry, policy, tmp_path / "generations.jsonl"


def test_a_session_writes_a_row_per_generation_and_an_allocation(world):
    registry, policy, ledger = world
    written = run(registry, policy, ledger, get_json=_get_json, now=NOW)
    assert [row["payload"]["candidate"] for row in written] == ["g1", ALLOCATION_ID]
    assert written[0]["payload"]["status"] == "ok" and written[0]["payload"]["state"] == "healthy"
    assert written[1]["payload"]["shares"] == {"g1": 1.0}
    assert judge_generations(read_ledger(ledger))["chain_valid"] is True


def test_a_rerun_of_the_day_appends_nothing(world):
    registry, policy, ledger = world
    run(registry, policy, ledger, get_json=_get_json, now=NOW)
    before = ledger.read_bytes()
    assert run(registry, policy, ledger, get_json=_get_json, now=NOW) == []
    assert ledger.read_bytes() == before


def test_a_day_that_is_no_session_writes_nothing(world):
    registry, policy, ledger = world
    assert run(registry, policy, ledger, get_json=_get_json, now=NOW, session_override="2030-01-01") == []
    assert not ledger.exists()


def test_a_blocked_price_source_is_a_row_with_its_reason(world):
    registry, policy, ledger = world

    def blocked(url):
        raise ConnectionError("blocked")

    written = run(registry, policy, ledger, get_json=blocked, now=NOW, session_override=TODAY)
    assert written[0]["payload"]["status"] == "no_data" and "ConnectionError" in written[0]["payload"]["reason"]
    assert written[-1]["payload"]["shares"] == {"g1": 1.0}


def test_a_retired_or_rejected_generation_gets_no_row(world):
    registry, policy, ledger = world
    save_registry(registry, {"g1": G1, "gone": replace(G1, id="gone", stage="retired"), "no": replace(G1, id="no", stage="rejected")})
    assert [row["payload"]["candidate"] for row in run(registry, policy, ledger, get_json=_get_json, now=NOW)] == ["g1", ALLOCATION_ID]


def test_a_new_ramping_generation_enters_at_its_share(world):
    registry, policy, ledger = world
    run(registry, policy, ledger, get_json=_get_json, now=NOW, session_override=DAYS[-2])
    save_registry(registry, {"g1": G1, "g2": replace(G1, id="g2", tier="tier1", stage="ramping", born=TODAY)})
    written = run(registry, policy, ledger, get_json=_get_json, now=NOW, session_override=TODAY)
    shares = written[-1]["payload"]["shares"]
    assert shares["g1"] == pytest.approx(0.7) and shares["g2"] == pytest.approx(0.3)


def test_a_shadow_generation_is_recorded_but_holds_nothing(world):
    registry, policy, ledger = world
    save_registry(registry, {"g1": G1, "g2": replace(G1, id="g2", tier="tier2", stage="shadow", born=TODAY)})
    written = run(registry, policy, ledger, get_json=_get_json, now=NOW)
    assert {row["payload"]["candidate"] for row in written} == {"g1", "g2", ALLOCATION_ID}
    assert written[-1]["payload"]["shares"]["g2"] == 0.0


def test_a_generation_needing_a_host_writes_no_data_until_it_has_decided(world):
    registry, policy, ledger = world
    save_registry(registry, {"g1": G1, "g2": replace(G1, id="g2", tier="tier2", stage="shadow", needs="fundamentals")})
    written = run(registry, policy, ledger, get_json=_get_json, now=NOW)
    mine = next(row["payload"] for row in written if row["payload"]["candidate"] == "g2")
    assert mine["status"] == "no_data" and "no decision" in mine["reason"]


def test_a_stale_decision_stops_being_used():
    decisions = [{"payload": {"candidate": "g2", "session": DAYS[-40], "decided": {"A": 0.1}}}]
    assert latest_decision(decisions, "g2", DAYS, TODAY, 20)[1].startswith("the newest decision is 39")
    fresh = [{"payload": {"candidate": "g2", "session": DAYS[-3], "decided": {"A": 0.1}}}]
    assert latest_decision(fresh, "g2", DAYS, TODAY, 20) == (None, None), "a decision from earlier: nothing new today, and no complaint"
    today = [{"payload": {"candidate": "g2", "session": TODAY, "decided": {"A": 0.1}}}]
    assert latest_decision(today, "g2", DAYS, TODAY, 20) == ({"A": 0.1}, None)


def test_marks_route_by_class():
    definition = {**DEFINITION, "tickers": ["BTCUSD", "AAPL"], "asset_class": {"BTCUSD": "crypto", "AAPL": "equity"}}
    seen = []

    def get_json(url):
        seen.append(url)
        return _get_json(url)

    marks = marks_for(replace(G1, definition=definition), DAYS, get_json)
    assert list(marks.columns) == ["BTCUSD", "AAPL"] and marks.notna().any().all()
    assert any("BTC-USD" in url for url in seen) and any("chart/AAPL" in url for url in seen), "AAPL must never be asked of Coinbase as A-USD"
    assert not any("A-USD" in url for url in seen)


def test_the_summary_says_what_a_person_needs(world):
    registry, policy, ledger = world
    written = run(registry, policy, ledger, get_json=_get_json, now=NOW)
    text = "\n".join(summary_lines(written, ledger))
    assert "Chain valid: True" in text and "g1" in text and "Shares" in text


def test_a_decision_is_made_once_by_a_generation_that_needs_a_host(tmp_path):
    registry = tmp_path / "registry.json"
    save_registry(registry, {"g1": G1, "g2": replace(G1, id="g2", needs="fundamentals", vintages=("v1",))})
    ledger = tmp_path / "decisions.jsonl"
    row = write_decision(registry, "g2", {"A": 0.1}, ledger, session=TODAY, created_at="t")
    assert row["payload"]["decided"] == {"A": 0.1} and row["payload"]["vintage"] == "v1"
    assert write_decision(registry, "g2", {"A": 0.9}, ledger, session=TODAY, created_at="t") is None
    assert read_ledger(ledger)[0]["payload"]["decided"] == {"A": 0.1}
    with pytest.raises(ValueError):
        write_decision(registry, "g1", {"A": 0.1}, ledger, session=TODAY, created_at="t")
    with pytest.raises(KeyError):
        write_decision(registry, "nobody", {"A": 0.1}, ledger, session=TODAY, created_at="t")


def test_a_damaged_weight_file_never_reaches_the_record(tmp_path):
    path = tmp_path / "weights.csv"
    path.write_text("ticker,weight\nA,nan\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_weights(path)


def test_the_installed_generation_is_the_forward_ledgers_rule():
    registry = load_registry(ROOT / "ml" / "generations" / "registry.json")
    candidates = json.loads((ROOT / "ml" / "forward" / "candidates.json").read_text(encoding="utf-8"))["candidates"]
    assert registry["g0001"].definition == next(entry for entry in candidates if entry["id"] == "t3_crypto_trend_blend")
    assert registry["g0001"].stage == "active" and registry["g0001"].tier == "installed"
