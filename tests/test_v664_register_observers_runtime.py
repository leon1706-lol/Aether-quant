"""scripts/v664_register_observers.py's runtime (V6.6.6, #359): the Coinbase universe fetch and the dry-run and applied `main()`, with the public API and the registry in a
temporary tree so the real `ml/generations` is never written."""

from __future__ import annotations

import json
import sys

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "scripts"))

import v664_register_observers as observers  # noqa: E402
from evaluation.generation_registry import Generation, load_registry, save_registry  # noqa: E402


def _candles(count, close, volume):
    return [[1_700_000_000 + index, close, close, close, close, volume] for index in range(count)]


def test_the_universe_is_fetched_ranked_by_traded_value_and_stablecoins_are_left_out(monkeypatch):
    monkeypatch.setattr(observers.time, "sleep", lambda seconds: None)
    products = [{"id": "BTC-USD", "quote_currency": "USD", "status": "online"}, {"id": "ETH-USD", "quote_currency": "USD", "status": "online"}, {"id": "USDT-USD", "quote_currency": "USD", "status": "online"},
                {"id": "PEG-USD", "quote_currency": "USD", "status": "online"}, {"id": "NEW-USD", "quote_currency": "USD", "status": "online"}, {"id": "EUR-USD", "quote_currency": "EUR", "status": "online"},
                {"id": "HALT-USD", "quote_currency": "USD", "status": "online", "trading_disabled": True}]
    candles = {"BTC-USD": _candles(300, 50000.0, 10.0), "ETH-USD": _candles(300, 3000.0, 100.0), "USDT-USD": _candles(300, 1.0, 1e6), "PEG-USD": _candles(300, 1.001, 1e6), "NEW-USD": _candles(100, 5.0, 1e6)}

    def get_json(url):
        if url == observers.PRODUCTS_URL:
            return products
        return candles[url.split("/products/")[1].split("/")[0]]

    universe, note = observers.fetch_universe(get_json, pause=0.0)
    assert universe == ["BTCUSD", "ETHUSD"] and note["products_online_usd"] == 5 and note["with_full_history"] == 4 and note["stablecoins_left_out"] == ["PEG-USD", "USDT-USD"]


def _tree(monkeypatch, tmp_path, *, with_registry=True):
    import forward_ledger

    scores = tmp_path / "scores.json"
    scores.write_text(json.dumps({"x10": {"sharpe": 0.8}, "x12": {"sharpe": 0.7}, "x14": {"sharpe": 0.6}, "x01": {"sharpe": 0.1}}), encoding="utf-8")
    rule = tmp_path / "observers.json"
    rule.write_text("{}", encoding="utf-8")
    rule.with_suffix(".sha256").write_text("a" * 64 + "\n", encoding="utf-8")
    monkeypatch.setattr(observers, "SCORES", scores)
    monkeypatch.setattr(observers, "OBSERVERS_RULE", rule)
    monkeypatch.setattr(observers, "ROOT", tmp_path)
    monkeypatch.setattr(observers, "fetch_universe", lambda get_json: (["BTCUSD", "ETHUSD"], {"products_online_usd": 2}))
    monkeypatch.setattr(forward_ledger, "session_for_outage", lambda now: "2026-11-06")
    if with_registry:
        folder = tmp_path / "ml" / "generations"
        folder.mkdir(parents=True)
        save_registry(folder / "registry.json", {"g0007": Generation(id="g0007", kind="rule", tier="installed", stage="active", born="2026-01-01", procedure_sha256="x")})
    return tmp_path / "ml" / "generations"


def test_a_dry_run_prints_what_it_would_register_and_writes_nothing(monkeypatch, tmp_path, capsys):
    folder = _tree(monkeypatch, tmp_path)
    assert observers.main([]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["chosen_x_trials"] == ["x10", "x12", "x14"] and summary["anchor"] == "2026-11-06" and summary["ids"] == ["obs_x10", "obs_x12", "obs_x14", "obs_k09"]
    assert set(load_registry(folder / "registry.json")) == {"g0007"} and not (folder / "lifecycle.jsonl").exists()


def test_an_applied_run_appends_each_observer_with_its_lifecycle_event(monkeypatch, tmp_path, capsys):
    folder = _tree(monkeypatch, tmp_path)
    assert observers.main(["--apply", "--anchor", "2026-11-05"]) == 0
    registry = load_registry(folder / "registry.json")
    assert set(registry) == {"g0007", "g0008", "g0009", "g0010", "g0011"} and registry["g0011"].needs == "fundamentals" and registry["g0008"].tier == "none" and registry["g0008"].stage == "shadow"
    events = [json.loads(line) for line in (folder / "lifecycle.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [event["payload"]["observer"] for event in events] == ["obs_x10", "obs_x12", "obs_x14", "obs_k09"] and "registered 4 observers" in capsys.readouterr().out
    assert pytest is not None
