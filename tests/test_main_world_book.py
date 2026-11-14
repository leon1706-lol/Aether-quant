"""main.py's rank-driven book path on a synthetic Lean world (V6.6.6, #359): the per-symbol feature build, the models, the book, the sizing chain and the order paths, with
`phase_v2.target_weights` off (the installed config trades the weight-file path, which `test_main_world_setup.py` runs)."""

from __future__ import annotations

import sys

import pytest

import lean_world as world
from lean_fakes import Market

BOOK = {
    "phase_v2": {
        "target_weights": {"enabled": False}, "rolling_ic_gate": {"enabled": False},
        "portfolio_book": {"top_n": 2, "bottom_n": 2, "rebalance_every_bars": 3, "min_rank_confidence_spread": 0.0, "hysteresis_rank_margin": 0.0,
                           "neutrality": {"sector_neutral": False, "max_weight_per_name": 0.3, "sector_max_net_weight": 1.0}},
        "exits": {"max_holding_bars": 6, "trailing_stop_pct": 0.05},
    },
    "phase1": {"target": {"ranking": {"min_universe_size": 4}}},
    "phase6": {"risk": {"trade_cooldown_bars": 1}},
}
TICKERS = ("SPY", "AAPL", "MSFT", "XOM", "NVDA", "TLT", "BTCUSD", "ETHUSD", "EURUSD", "GBPJPY")


@pytest.fixture
def book(monkeypatch, tmp_path):
    main = world.install_stub(monkeypatch)
    root = world.make_root(tmp_path, overrides=BOOK, tickers=TICKERS)
    monkeypatch.chdir(root)
    instance = world.build_algorithm(main, root)
    yield instance
    monkeypatch.delitem(sys.modules, "main", raising=False)


def test_the_book_scores_ranks_and_trades_a_run_of_bars(book):
    market = Market(book, seed=1)
    market.run(70)
    assert book.bar_index > 0 and book.order_log
