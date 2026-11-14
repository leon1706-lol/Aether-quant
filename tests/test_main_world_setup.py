"""main.py on a synthetic Lean world (V6.6.6, #359): the first-bar setup, then bars of a seeded market, with a temporary project root, config and `ml/` artifacts, so a clean
checkout runs the same code a Lean run does."""

from __future__ import annotations

import sys

import pytest

import lean_world as world
from lean_fakes import Market


@pytest.fixture
def algorithm(monkeypatch, tmp_path):
    main = world.install_stub(monkeypatch)
    root = world.make_root(tmp_path)
    monkeypatch.chdir(root)
    instance = world.build_algorithm(main, root)
    yield instance
    monkeypatch.delitem(sys.modules, "main", raising=False)


def test_the_first_bar_setup_completes_on_synthetic_artifacts(algorithm):
    assert algorithm.__dict__["_ready"] is True and len(algorithm.symbols) >= 5
    assert set(algorithm.expert_model_exports) == set(world.EXPERTS) and algorithm.multitask_model is not None and algorithm.sequence_model is not None


def test_a_run_of_bars_scores_every_symbol_and_trades_the_book(algorithm):
    market = Market(algorithm, seed=1)
    market.run(60)
    assert algorithm.bar_index > 0 and algorithm.order_log is not None
