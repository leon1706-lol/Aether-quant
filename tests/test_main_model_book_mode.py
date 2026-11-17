"""main.py's in-Lean model book (V6.6.9, #394) on the synthetic Lean world: default off, a row decided from the models' own scores and traded
through the target-weights order path, and a book that holds when a pin, the definition or a weight is wrong."""

from __future__ import annotations

import json
import sys

import pytest

import lean_world as world
from lean_fakes import Market
from retraining.artifact_pins import write_artifact_pins

TICKERS = ("SPY", "AAPL", "MSFT", "XOM", "NVDA", "TLT", "BTCUSD", "ETHUSD", "EURUSD", "GBPJPY")
BOOK_PART = {
    "id": "bk", "track": "BOOK", "kind": "cross_sectional", "family": "external_score", "universe": ["equity"], "every": 2,
    "params": {"table": "ml_a1", "optimizer": "pooled"},
}
DEFINITION = {
    "kind": "blend", "history_start": "2019-01-01", "pinned_run": None, "settings": {"name_cap": 0.3, "class_caps": {"equity": 0.9}, "name_cap_by_class": {}},
    "parts": [{"generation": "g0006", "share": 1.0, "book": BOOK_PART, "phase_index": 0}],
}
OVERRIDES = {
    "phase_v2": {
        "target_weights": {"enabled": True, "source": "model_book", "min_weight_change": 0.0, "min_trade_usd": 0.0, "weights_path": "ml/none.csv", "financing_enabled": False},
        "rolling_ic_gate": {"enabled": False}, "model_book": {"candidate_path": "ml/target_weights_candidate.json", "artifact_pins_path": "ml/artifact_pins.json"},
        "forex_risk": {"enabled": True},
    },
    "phase1": {"target": {"ranking": {"min_universe_size": 4}}},
}


def _root(tmp_path, *, definition=DEFINITION, pins=True, source="model_book"):
    overrides = json.loads(json.dumps(OVERRIDES))
    overrides["phase_v2"]["target_weights"]["source"] = source
    root = world.make_root(tmp_path, overrides=overrides, tickers=TICKERS)
    if definition is not None:
        (root / "ml" / "target_weights_candidate.json").write_text(json.dumps(definition), encoding="utf-8")
    if pins:
        write_artifact_pins(root / "ml", root / "ml" / "artifact_pins.json")
    return root


def _risk_orders(algorithm):
    """The orders that are not the T-bill sweep parking idle cash."""
    return [order for order in algorithm.order_log if order[3] != "cash_sweep"]


def _algorithm(monkeypatch, root):
    main = world.install_stub(monkeypatch)
    monkeypatch.chdir(root)
    return world.build_algorithm(main, root)


@pytest.fixture(autouse=True)
def _forget_main(monkeypatch):
    yield
    monkeypatch.delitem(sys.modules, "main", raising=False)


def test_the_default_source_is_the_file_and_the_model_book_is_off(monkeypatch, tmp_path):
    algorithm = _algorithm(monkeypatch, _root(tmp_path, source="file"))
    assert algorithm._model_book_in_lean is False and algorithm._model_book_definition is None


def test_the_model_book_scores_the_universe_decides_a_row_and_trades_it(monkeypatch, tmp_path):
    algorithm = _algorithm(monkeypatch, _root(tmp_path))
    assert algorithm._model_book_in_lean and algorithm._model_book_blocked == "" and algorithm._model_book_definition.shares == {"g0006": 1.0}
    Market(algorithm, seed=3).run(120)
    rows = [json.loads(message.split("model_book_row ", 1)[1]) for message in algorithm.messages if message.startswith("model_book_row ")]
    assert rows and all(set(entry) == {"date", "row"} for entry in rows)
    assert any(entry["row"] for entry in rows) and len(algorithm._session_dates) == algorithm.bar_index
    assert _risk_orders(algorithm), "a decided row must reach the order path"
    held = {ticker for entry in rows for ticker in entry["row"]}
    assert held <= {"SPY", "AAPL", "MSFT", "XOM", "NVDA"}


def test_a_changed_model_file_leaves_the_book_holding(monkeypatch, tmp_path):
    root = _root(tmp_path)
    pins = json.loads((root / "ml" / "artifact_pins.json").read_text(encoding="utf-8"))
    pins["files"]["scaler_stats.json"] = "0" * 64  # the record no longer describes the file: the same as the file having changed
    (root / "ml" / "artifact_pins.json").write_text(json.dumps(pins), encoding="utf-8")
    algorithm = _algorithm(monkeypatch, root)
    assert "scaler_stats.json does not match" in algorithm._model_book_blocked
    Market(algorithm, seed=3).run(60)
    assert not any(message.startswith("model_book_row") for message in algorithm.messages) and not _risk_orders(algorithm)
    assert sum("model_book: holding" in message for message in algorithm.messages) == 2  # the setup line and one note, never one per bar


def test_a_missing_definition_or_missing_pins_hold_the_book(monkeypatch, tmp_path):
    algorithm = _algorithm(monkeypatch, _root(tmp_path, definition=None))
    assert "cannot be read" in algorithm._model_book_blocked
    Market(algorithm, seed=3).run(40)
    assert not _risk_orders(algorithm)
    (tmp_path / "second").mkdir()
    unpinned = _algorithm(monkeypatch, _root(tmp_path / "second", pins=False))
    assert "no artifact pins" in unpinned._model_book_blocked


def test_a_row_that_is_not_finite_or_a_model_past_its_age_is_not_traded(monkeypatch, tmp_path):
    algorithm = _algorithm(monkeypatch, _root(tmp_path))
    algorithm._model_age_days = lambda: 400.0
    Market(algorithm, seed=3).run(90)
    assert not any(message.startswith("model_book_row") for message in algorithm.messages) and not _risk_orders(algorithm)
    assert any("past their age limit" in message for message in algorithm.messages)


def test_a_definition_error_during_a_decision_is_noted_once_and_holds(monkeypatch, tmp_path):
    algorithm = _algorithm(monkeypatch, _root(tmp_path))
    import portfolio.model_book as model_book

    def broken(*args, **kwargs):
        raise ValueError("no such optimizer")

    monkeypatch.setattr(model_book, "lean_session_row", broken)
    Market(algorithm, seed=3).run(60)
    assert not _risk_orders(algorithm) and sum("could not be built" in message for message in algorithm.messages) == 1


def test_a_tick_with_no_equity_bar_has_no_decision_date_and_keeps_no_close(monkeypatch, tmp_path):
    from types import SimpleNamespace

    algorithm = _algorithm(monkeypatch, _root(tmp_path))
    empty = SimpleNamespace(Bars={})
    assert algorithm._equity_decision_date(empty) is None
    algorithm._record_session_closes(empty)
    assert len(algorithm._session_dates) == 0 and not algorithm._session_closes
