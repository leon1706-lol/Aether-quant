"""scripts/daily_target_weights.py: a row computed with today's data equals the research file's row, and a date is written once."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from portfolio.premia_signals import TS, ResearchPanel, SleeveSpec, known_closes, signal_to_weights, sleeve_signal
from portfolio.target_weights import load_weight_file, weights_at_tick

_SPEC = importlib.util.spec_from_file_location(
    "daily_target_weights", Path(__file__).resolve().parent.parent / "scripts" / "daily_target_weights.py"
)
module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(module)

SPEC = SleeveSpec("trend", "T3", TS, "time_series_momentum", ("equity",), 5, {"lookback_a": 63})


def _context():
    rng = np.random.default_rng(1)
    dates = pd.bdate_range("2018-01-01", periods=400).strftime("%Y-%m-%d").tolist()
    tickers = ["A", "B", "C", "D", "E"]
    closes = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, size=(400, 5)), axis=0))
    classes = {ticker: "equity" for ticker in tickers}
    panel = ResearchPanel(known_closes(dates, tickers, closes, classes, set(dates)), classes)
    return SimpleNamespace(panel=panel)


def _candidate_rows(definition, context, *, start, end, phase_index):
    signal = sleeve_signal(SPEC, context.panel)
    return signal_to_weights(signal, context.panel, kind=SPEC.kind, rebalance_every=SPEC.rebalance_every, phase_offset=phase_index, start=start, end=end)


def test_daily_rows_equal_the_research_file():
    context = _context()
    start = str(context.panel.known.index[100])
    research = _candidate_rows({}, context, start=start, end=str(context.panel.known.index[-1]), phase_index=0)

    checked = 0
    for date in sorted(research)[5:30:6]:
        row = module.row_for_date({}, context, date, candidate_rows=_candidate_rows, history_start=start)
        assert row == pytest.approx(research[date])
        checked += 1
    assert checked >= 3


def test_a_date_that_is_no_rebalance_day_gives_no_row():
    context = _context()
    start = str(context.panel.known.index[100])
    off_day = str(context.panel.known.index[101])
    assert module.row_for_date({}, context, off_day, candidate_rows=_candidate_rows, history_start=start) is None


def test_row_for_date_leaves_the_full_panel_in_place():
    context = _context()
    original = context.panel
    module.row_for_date({}, context, str(original.known.index[200]), candidate_rows=_candidate_rows, history_start=str(original.known.index[100]))
    assert context.panel is original


def test_append_writes_a_date_once_and_the_file_loads(tmp_path):
    path = tmp_path / "live.csv"
    assert module.append_row(path, "2024-01-02", {"SPY": 0.5, "TLT": -0.25}) is True
    assert module.append_row(path, "2024-01-02", {"SPY": 0.9}) is False
    assert module.append_row(path, "2024-01-03", {}) is True

    weights = load_weight_file(path)
    assert weights_at_tick(weights, "2024-01-02") == {"SPY": 0.5, "TLT": -0.25}
    assert weights_at_tick(weights, "2024-01-03") == {}


def test_append_refuses_a_non_finite_weight(tmp_path):
    with pytest.raises(ValueError, match="non-finite"):
        module.append_row(tmp_path / "live.csv", "2024-01-02", {"SPY": float("nan")})
    assert not (tmp_path / "live.csv").exists()
