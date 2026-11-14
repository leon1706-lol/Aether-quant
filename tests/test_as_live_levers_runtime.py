"""scripts/as_live_levers.py's runtime (V6.6.6, #359): the score cache, the rolling-IC gate and mechanism caches, as-live runs with a changed config, the
T-bill sweep and tranches, the legacy exits, the summary and the whole command, on a small synthetic dataset with stand-in model scores."""

from __future__ import annotations

import copy
import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from script_loader import ROOT, load_script
from test_as_live_levers import _synthetic_dataset


@pytest.fixture(scope="module")
def levers():
    return load_script("as_live_levers")


def _setup(levers, monkeypatch, tmp_path):
    import aq_cli

    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    equities = [a["ticker"] for a in config["phase1"]["universe"]["assets"] if a.get("asset_class", a["security_type"]) == "equity"][:24]
    dataset = _synthetic_dataset(tmp_path / "d.csv", equities)
    probability = dataset[["date", "ticker"]].assign(final_probability_up=np.where(dataset["ticker"] == equities[12], 0.6, 0.5))
    probability.to_parquet(tmp_path / "p.parquet")
    calls = []
    monkeypatch.setattr(aq_cli, "_blend_raw_scores_for_dataset",
                        lambda frame, *a, **k: calls.append(len(frame)) or (np.asarray([hash(t) % 1000 / 1000 for t in frame["ticker"]], dtype=float), {}))
    ml_stub = tmp_path / "ml"
    ml_stub.mkdir()
    (ml_stub / "model_weights.json").write_text(json.dumps({"training": {"decision_threshold": 0.5}}), encoding="utf-8")
    monkeypatch.setattr(levers, "CACHE_DIR", tmp_path / "cache")
    return ml_stub, calls


@pytest.fixture
def harness(levers, monkeypatch, tmp_path):
    ml_stub, calls = _setup(levers, monkeypatch, tmp_path)
    built = levers.AsLiveHarness("validation", dataset_path=tmp_path / "d.csv", use_cache=True, gate_warmup_days=45, legacy_probability_path=tmp_path / "p.parquet", ml_dir=ml_stub)
    built.calls = calls
    return built


def test_an_ensemble_and_ranked_inputs_change_the_score_fingerprint(levers, tmp_path):
    dataset = tmp_path / "d.csv"
    dataset.write_text("x\n1\n", encoding="utf-8")
    ml = tmp_path / "ml"
    (ml / "mt").mkdir(parents=True)
    (ml / "mt" / "seed1.json").write_text("{}", encoding="utf-8")
    plain = {"phase_v2": {"rank_signal": {}}}
    ranked = {"phase_v2": {"rank_signal": {}}, "phase1": {"features": {"cross_sectional_inputs": {"enabled": True}}}}
    ensemble = {"phase_v2": {"rank_signal": {}, "model_ensemble": {"enabled": True, "multitask_dir": "mt", "sequence_dir": "seq"}}}
    prints = {levers._fingerprint(config, dataset, ml) for config in (plain, ranked, ensemble)}
    assert len(prints) == 3
    (ml / "mt" / "seed2.json").write_text("{}", encoding="utf-8")
    assert levers._fingerprint(ensemble, dataset, ml) not in prints


def test_scores_are_cached_on_first_use_and_read_back_afterwards(levers, harness, monkeypatch, tmp_path):
    assert harness.calls and list((tmp_path / "cache").glob("*.npy"))
    again = levers.AsLiveHarness("validation", dataset_path=tmp_path / "d.csv", use_cache=True, gate_warmup_days=45, legacy_probability_path=tmp_path / "p.parquet", ml_dir=tmp_path / "ml")
    assert len(harness.calls) == 1 and len(again.frame) == len(harness.frame)


def test_a_run_with_the_gate_on_shares_its_state_across_floors_and_caches_mechanisms(harness):
    first = harness.as_live(ic_floor=0.0)
    second = harness.as_live(ic_floor=0.02)
    assert len(harness._states) == 1 and len(harness._gates) == 2 and len(first.per_date) == len(second.per_date)
    harness.as_live(ic_floor=0.0, gate_window=30, gate_horizon=10, gate_min_names=5, gate_event_count="per_tick")
    assert len(harness._states) == 2
    cached = len(harness._mechanisms)
    harness.as_live(include=("hrp",))
    harness.as_live(include=("hrp",))
    assert len(harness._mechanisms) == cached + 1
    assert harness.idealized().net_sharpe is not None


def test_a_changed_config_is_applied_for_that_run_only(harness):
    before = copy.deepcopy(harness.config["phase_v2"]["portfolio_book"])
    result = harness.as_live(gate="off", config_overrides={"portfolio_book.allocation_method": "hrp", "brand_new.section.key": 1})
    assert harness.config["phase_v2"]["portfolio_book"] == before and "brand_new" not in harness.config["phase_v2"] and len(result.per_date) > 0


def test_the_t_bill_sweep_and_the_tranche_book_are_options_of_a_run(harness, monkeypatch):
    import evaluation.live_parity as live_parity

    monkeypatch.setattr(live_parity, "build_cash_sweep_kwarg", lambda config, root, force_enabled: None)
    assert len(harness.as_live(gate="off", cash_sweep=True).per_date) > 0
    tranched = harness.as_live(gate="off", tranches=2)
    assert len(tranched.per_date) > 0


def test_the_legacy_sleeve_reads_its_exits_from_the_config(harness):
    config = copy.deepcopy(harness.config)
    config["phase_v2"]["exits"] = {"enabled": True, "max_holding_bars": 30, "trailing_stop_pct": 0.1}
    config["phase_v2"].setdefault("legacy_sleeve", {})["enabled"] = True
    options = harness.v610_mechanisms(config, extra_returns={"2022-01-03": 0.001})
    legacy = options["legacy_component"]
    assert legacy["max_holding_dates"] == 30 and legacy["trailing_stop_pct"] == 0.1 and options["kill_switch_extra_returns"] == {"2022-01-03": 0.001}
    assert "legacy_component" not in harness.v610_mechanisms(legacy=False)


def test_the_split_dataset_arguments_and_the_summary(levers, harness):
    import argparse

    parser = argparse.ArgumentParser()
    levers.add_split_dataset_args(parser)
    args = parser.parse_args(["--dataset-validation", "v.csv"])
    assert levers.dataset_for_split(args, "validation") == "v.csv" and levers.dataset_for_split(args, "backtest") is None
    summary = levers.summarize(harness.as_live(gate="off"))
    assert {"net_sharpe", "annualized_turnover", "mean_net_exposure"} <= set(summary)


def test_the_command_runs_every_variant_and_writes_its_json(levers, monkeypatch, tmp_path, capsys):
    result = SimpleNamespace(net_sharpe=0.5, net_total_return=0.1, net_max_drawdown=-0.05, num_rebalances=10, num_vetoed_rebalances=2, veto_reasons={}, mean_names_long=5.0, mean_names_short=5.0,
                             num_kill_switch_locked_dates=0, num_kill_switch_frozen_decisions=0, annualized_turnover=3.0, cost_drag_annual_bps=20.0, mean_gross_exposure=1.0, mean_net_exposure=0.0)
    seen = []

    class FakeHarness:
        def __init__(self, split, use_cache):
            seen.append((split, use_cache))

        def idealized(self):
            return result

        def as_live(self, **kwargs):
            return result

    monkeypatch.setattr(levers, "AsLiveHarness", FakeHarness)
    monkeypatch.setattr(levers, "ML_DIR", tmp_path)
    (tmp_path / "evaluation").mkdir()
    monkeypatch.setattr(sys, "argv", ["as_live_levers", "--split", "validation", "--no-cache"])
    assert levers.main() == 0
    written = json.loads((tmp_path / "evaluation" / "as_live_levers_validation.json").read_text(encoding="utf-8"))
    assert seen == [("validation", False)] and len(written["variants"]) == 22
    monkeypatch.setattr(sys, "argv", ["as_live_levers", "--only", "HRP", "IC floor"])
    assert levers.main() == 0
    narrowed = json.loads((tmp_path / "evaluation" / "as_live_levers.json").read_text(encoding="utf-8"))
    assert "HRP allocation" in narrowed["variants"] and "as-live (config)" in narrowed["variants"] and len(narrowed["variants"]) < 22 and "net_sharpe" in capsys.readouterr().out
