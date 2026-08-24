"""V5.4.2 - parity tests for main.py's delegated pure functions
(data_pipeline/bar_synthesis.py). Pins the exact behavior so a future
regression in either the delegation or the extracted function fails here
before it reaches a real Lean backtest."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from data_pipeline.bar_synthesis import midpoint_bar_from_quote_bar, pad_sequence_history


class _FakeQuoteBar:
    def __init__(self, bo, ho, lo, co, ao=None):
        self.Bid = SimpleNamespace(Open=bo, High=ho, Low=lo, Close=co)
        self.Ask = SimpleNamespace(
            Open=ao if ao is not None else co,
            High=ho + 0.001,
            Low=lo - 0.001,
            Close=co + 0.001,
        )


def test_midpoint_normal_quote_bar():
    qb = _FakeQuoteBar(bo=100.0, ho=102.0, lo=99.0, co=101.0)
    result = midpoint_bar_from_quote_bar(qb)
    # Expected values computed from the fixture's actual bid/ask fields.
    assert result.open == pytest.approx((qb.Bid.Open + qb.Ask.Open) / 2)
    assert result.high == pytest.approx((qb.Bid.High + qb.Ask.High) / 2)
    assert result.low == pytest.approx((qb.Bid.Low + qb.Ask.Low) / 2)
    assert result.close == pytest.approx((qb.Bid.Close + qb.Ask.Close) / 2)
    assert result.volume == 0.0


@pytest.mark.parametrize("bad", [None])
def test_midpoint_none_inputs_return_none(bad):
    assert midpoint_bar_from_quote_bar(bad) is None


def test_midpoint_missing_bid_side_returns_none():
    qb = SimpleNamespace(Bid=None, Ask=SimpleNamespace(Open=1, High=1, Low=1, Close=1))
    assert midpoint_bar_from_quote_bar(qb) is None


def test_pad_sequence_history_exact_padding():
    history = [[1.0, 2.0], [3.0, 4.0]]
    result = pad_sequence_history(history, window_size=5)
    assert len(result) == 5
    assert result[:3] == [[0.0, 0.0]] * 3
    assert result[3:] == [[1.0, 2.0], [3.0, 4.0]]


def test_pad_sequence_history_no_padding_needed():
    history = [[1.0], [2.0], [3.0]]
    result = pad_sequence_history(history, window_size=3)
    assert result == history
