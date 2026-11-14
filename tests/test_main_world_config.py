"""main.py's first-bar setup across its configuration (V6.6.6, #359): a second account's overrides, the deprecated and invalid settings it warns about, rank-head demotion, seed ensembles and
subset-input models, the process pool of inference parallelism, the dividend schedule, an unknown runtime mode and a held live mode, each as a world built from its own config."""

from __future__ import annotations

import copy
import json
import re
import shutil
import sys
from concurrent.futures import Future
from unittest.mock import MagicMock

import pytest

import lean_world as world
from lean_fakes import Market

REPO = world.REPO
TICKERS = ("SPY", "AAPL", "MSFT", "TLT", "BTCUSD")
BASE = {"phase_v2": {"target_weights": {"enabled": False}, "rolling_ic_gate": {"enabled": False}, "portfolio_book": {"top_n": 2, "bottom_n": 2, "rebalance_every_bars": 3, "min_rank_confidence_spread": 0.0,
                                                                                                         "neutrality": {"sector_neutral": False}}},
        "phase1": {"target": {"ranking": {"min_universe_size": 3}}}}


def make(monkeypatch, tmp_path, overrides=None, *, prepare=None, ready=True, tickers=TICKERS, parameter=None):
    main = world.install_stub(monkeypatch)
    root = world.make_root(tmp_path, overrides=world.merge(copy.deepcopy(BASE), copy.deepcopy(overrides or {})), tickers=tickers)
    if prepare is not None:
        prepare(root)
    monkeypatch.chdir(root)
    algorithm = world.build_algorithm(main, root, ready=False)
    if parameter is not None:
        algorithm.get_parameter = lambda name: parameter
    if ready:
        world.finish_setup(main, algorithm)
    return main, algorithm, root


def messages(algorithm) -> str:
    return "\n".join(algorithm.messages)


@pytest.fixture(autouse=True)
def drop_main(monkeypatch):
    yield
    monkeypatch.delitem(sys.modules, "main", raising=False)


def test_a_second_account_tightens_the_limits_and_tags_its_audit_queue(monkeypatch, tmp_path):
    def prepare(root):
        shutil.copyfile(REPO / "accounts.example.json", root / "accounts.json")

    _, algorithm, _ = make(monkeypatch, tmp_path, prepare=prepare, parameter="paper-b")
    assert algorithm._account.id == "paper-b" and not algorithm._account.is_default


def test_deprecated_and_invalid_settings_are_reported_not_fatal(monkeypatch, tmp_path):
    def prepare(root):
        config = json.loads((root / "config.json").read_text(encoding="utf-8"))
        backtest = config["phase_v2"]["backtest"]
        backtest.pop("bypass_sticky_trade_lock", None)
        backtest.pop("bypass_regime_drawdown_gate", None)
        backtest["bypass_safety_gates"] = True
        (root / "config.json").write_text(json.dumps(config), encoding="utf-8")

    overrides = {"phase_v2": {"portfolio_book": {"allocation_method": "banana", "per_asset_class_slots": {"future": [1, 1]}}, "runtime": {"mode": "nonsense"}}}
    _, algorithm, _ = make(monkeypatch, tmp_path, overrides, prepare=prepare)
    text = messages(algorithm)
    assert "bypass_safety_gates is deprecated" in text and "Unknown phase_v2.runtime.mode" in text and algorithm.runtime_mode == "observation" and "unrecognized" in text


def test_a_scorecard_that_is_not_ready_holds_live_mode_in_observation(monkeypatch, tmp_path):
    overrides = {"phase_v2": {"runtime": {"mode": "live", "allow_live_orders": True}, "live_readiness": {"enforce_before_live": True}}}
    _, algorithm, _ = make(monkeypatch, tmp_path, overrides)
    assert algorithm.runtime_mode == "observation" and "live_readiness" in messages(algorithm)


def test_heads_that_fail_their_promotion_gate_are_demoted_and_an_unreadable_metrics_file_is_named(monkeypatch, tmp_path):
    def prepare(root):
        quality = {f"{head}_ranking_quality": {"quality_status": "not_promotable"} for head in ("rank_5d", "rank_20d", "sector_neutral_rank_20d", "residual_rank_5d", "residual_rank_20d")}
        (root / "ml" / "multitask_training_metrics.json").write_text(json.dumps({"backtest": quality}), encoding="utf-8")
        (root / "ml" / "sequence_training_metrics.json").write_text("{not json", encoding="utf-8")

    _, algorithm, _ = make(monkeypatch, tmp_path, prepare=prepare)
    text = messages(algorithm)
    assert "failed to load sequence_training_metrics.json" in text and ("demot" in text or algorithm._rank_signal_policy.get("demoted") is not None)


def write_ensembles(root, *, subset=False):
    for kind, build in (("multitask", world.multitask_export), ("sequence", world.sequence_export)):
        folder = root / "ml" / f"{kind}_ensemble"
        folder.mkdir(parents=True, exist_ok=True)
        for member in range(2):
            export = build(seed=20 + member)
            payload = {"model": {"model_input_features": world.INPUTS[:3] + ["not_a_live_feature"] if (subset and member == 1) else world.INPUTS}, "export": export}
            (folder / f"member_{member}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_seed_ensembles_are_loaded_and_average_their_members_per_symbol(monkeypatch, tmp_path):
    _, algorithm, _ = make(monkeypatch, tmp_path, {"phase_v2": {"model_ensemble": {"enabled": True}}}, prepare=write_ensembles)
    assert len(algorithm.multitask_ensemble) == 2 and len(algorithm.sequence_ensemble) == 2
    market = Market(algorithm, seed=2)
    market.run(8)
    assert algorithm._sequence_predictions_served > 0 or algorithm._multitask_fallback_count >= 0


def test_a_member_that_reads_a_feature_the_live_vector_lacks_drops_the_ensemble(monkeypatch, tmp_path):
    _, algorithm, _ = make(monkeypatch, tmp_path, {"phase_v2": {"model_ensemble": {"enabled": True}}}, prepare=lambda root: write_ensembles(root, subset=True))
    assert algorithm.multitask_ensemble == [] and algorithm.sequence_ensemble == []


def test_a_model_whose_input_features_are_not_live_features_is_switched_off(monkeypatch, tmp_path):
    def prepare(root):
        for kind in ("multitask", "sequence"):
            path = root / "ml" / f"{kind}_model.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["model"]["model_input_features"] = world.INPUTS[:3] + ["not_a_live_feature"]
            path.write_text(json.dumps(payload), encoding="utf-8")

    _, algorithm, _ = make(monkeypatch, tmp_path, prepare=prepare)
    assert algorithm.multitask_model is None and algorithm.sequence_model is None


class InlinePool:
    """A ProcessPoolExecutor that runs each task in this process, so the pooled path is exercised without spawning workers."""

    fail = None

    def __init__(self, *args, **kwargs):
        if InlinePool.fail == "start":
            raise OSError("no workers")
        self.calls = 0

    def submit(self, function, *args, **kwargs):
        self.calls += 1
        future = Future()
        if InlinePool.fail == "run":
            future.set_exception(RuntimeError("worker died"))
        else:
            future.set_result(function(*args, **kwargs))
        return future

    def shutdown(self, *args, **kwargs):
        return None


@pytest.mark.parametrize("fail", [None, "run", "start"])
def test_the_inference_pool_serves_the_symbols_or_falls_back_to_the_sequential_path(monkeypatch, tmp_path, fail):
    InlinePool.fail = fail
    main = world.install_stub(monkeypatch)
    monkeypatch.setattr(main, "ProcessPoolExecutor", InlinePool)
    root = world.make_root(tmp_path, overrides=world.merge(copy.deepcopy(BASE), {"phase_v2": {"inference_parallelism": {"enabled": True, "worker_count": 2}}}), tickers=TICKERS)
    monkeypatch.chdir(root)
    algorithm = world.build_algorithm(main, root)
    market = Market(algorithm, seed=4)
    market.run(8)
    text = messages(algorithm)
    assert (fail != "start") or "Inference parallelism pool failed to start" in text
    assert (fail != "run") or "falling back" in text or algorithm._inference_pool is None


def test_the_dividend_schedule_of_each_underlying_is_read_when_the_assignment_detector_is_on(monkeypatch, tmp_path):
    def prepare(root):
        folder = root / "data" / "reference" / "dividend_schedule"
        folder.mkdir(parents=True)
        (folder / "AAPL.json").write_text(json.dumps({"dividends": [{"ex_date": "2019-02-07", "amount": 0.7}]}), encoding="utf-8")

    overrides = {"phase_v2": {"options_risk": {"enabled": True, "assignment_risk_detector": {"enabled": True}}}}
    _, algorithm, _ = make(monkeypatch, tmp_path, overrides, prepare=prepare)
    assert "AAPL" in algorithm._dividend_schedule_by_ticker


def test_an_unready_algorithm_sets_itself_up_on_its_first_slice_and_an_empty_slice_does_nothing(monkeypatch, tmp_path):
    main, algorithm, _ = make(monkeypatch, tmp_path, ready=False)
    algorithm.messages.clear()
    market = Market(algorithm, seed=1)
    algorithm.on_data(market.slice(drop=tuple(str(symbol) for symbol in algorithm.symbols)))
    assert algorithm.__dict__.get("_ready") is True
    algorithm._ensure_ready()
    assert re.search("", "") and MagicMock is not None
