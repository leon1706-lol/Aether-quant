"""`train.main()` end to end on a synthetic project root (V6.6.6, #359): every mode the CLI has (inventory only, dataset only, a candidate version, experts only, the full active run, walk-forward),
on twelve generated assets under `tests/train_world.py`. The dataset is built once for the module and handed to each run; one test runs the real build."""

from __future__ import annotations

import copy
import json
import sys
import types

import pandas as pd
import pytest

import train
import train_multitask
import train_sequence
import train_world as world


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = world.build_root(tmp_path_factory.mktemp("built"))
    with pytest.MonkeyPatch.context() as patch:
        world.repoint(patch, train, root)
        # Lean's market-hours database is not in a clean checkout: give the build a forex holiday so the holiday-drop branch runs everywhere
        patch.setattr(train, "resolve_forex_lean_holidays", lambda config: frozenset({train.day_ordinal(pd.Timestamp("2018-12-25"))}))
        config = train.load_project_config()
        dataset, metadata = train.build_feature_dataset(config)
    return dataset, metadata


def run(monkeypatch, tmp_path, built, argv, *, config_overrides=None, real_build=False):
    root = world.build_root(tmp_path, **(config_overrides or {}))
    world.repoint(monkeypatch, train, root)
    if not real_build:
        dataset, metadata = built
        monkeypatch.setattr(train, "build_feature_dataset", lambda config: (dataset.copy(), copy.deepcopy(metadata)))
    monkeypatch.setattr(sys, "argv", ["train", *argv])
    return root, train.main()


def test_the_real_dataset_build_covers_every_asset_and_split(built):
    dataset, metadata = built
    assert set(dataset["ticker"]) == set(world.EQUITIES + world.BONDS + world.CRYPTO + world.FOREX)
    assert metadata["union_dates"] > 400 and {"train", "validation", "backtest"} <= set(dataset["split"])


def test_the_inventory_is_refreshed_with_and_without_an_existing_model(monkeypatch, tmp_path, built):
    root, code = run(monkeypatch, tmp_path, built, ["--init-only"])
    assert code == 0 and (root / "ml" / "model_weights.json").exists()
    _, code = run(monkeypatch, tmp_path / "again", built, ["--init-only"])
    assert code == 0


def test_a_dataset_only_run_writes_the_dataset_and_its_manifest(monkeypatch, tmp_path, built):
    root, code = run(monkeypatch, tmp_path, built, ["--dataset-only"])
    manifest = json.loads((root / "ml" / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert code == 0 and manifest["dataset_rows"] > 0 and (root / "ml" / "datasets" / "full_dataset.csv").exists()


def test_a_candidate_is_trained_into_its_own_version_directory(monkeypatch, tmp_path, built):
    root, code = run(monkeypatch, tmp_path, built, ["--candidate", "--version-id", "cand1"])
    version = root / "ml" / "versions" / "cand1"
    assert code == 0 and (version / "model_weights.json").exists() and (version / "training_metrics.json").exists() and not (root / "ml" / "model_weights.json").exists()


def test_a_candidate_without_a_version_id_is_refused(monkeypatch, tmp_path, built):
    with pytest.raises(SystemExit):
        run(monkeypatch, tmp_path, built, ["--candidate"])


def test_the_experts_alone_are_trained_and_reported(monkeypatch, tmp_path, built):
    root, code = run(monkeypatch, tmp_path, built, ["--experts-only"])
    assert code == 0 and (root / "ml" / "expert_training_metrics.json").exists()


def test_the_full_active_run_trains_the_baseline_and_the_experts(monkeypatch, tmp_path, built):
    root, code = run(monkeypatch, tmp_path, built, [])
    assert code == 0 and (root / "ml" / "model_weights.json").exists() and (root / "ml" / "training_metrics.json").exists() and (root / "ml" / "expert_training_metrics.json").exists()




WALK_FORWARD = {"phase_v2": {"retraining": {"walk_forward": {"train_span_days": 300, "validation_span_days": 100, "backtest_span_days": 100, "step_days": 100, "mode": "expanding",
                                                                "train_multitask": False, "train_sequence": False, "net_performance": False}}}}


def in_process_trainers(monkeypatch, root, returncodes=None):
    """`subprocess.run([python, train_x.py, ...])` becomes a call of that trainer's `main()` against the temporary root."""
    for module in (train_multitask, train_sequence):
        world.repoint(monkeypatch, module, root)
    calls = []

    def fake_run(command, **kwargs):
        script = command[1].replace("\\", "/").rsplit("/", 1)[-1]
        module = train_multitask if "multitask" in script else train_sequence
        monkeypatch.setattr(sys, "argv", [script, *command[2:]])
        code = (returncodes or {}).get(script)
        calls.append(script)
        if code is None:
            code = module.main()
        return types.SimpleNamespace(returncode=code, stderr="failed" if code else "", stdout="")

    monkeypatch.setattr(train.subprocess, "run", fake_run)
    return calls


def test_walk_forward_trains_a_baseline_per_window_and_summarises_the_stability(monkeypatch, tmp_path, built, capsys):
    root, code = run(monkeypatch, tmp_path, built, ["--walk-forward"], config_overrides=WALK_FORWARD)
    out = capsys.readouterr().out
    assert code == 0 and "Walk-forward run" in out and any((root / "ml" / "versions").glob("*/window_*"))


def test_walk_forward_with_the_sequence_and_multitask_models_and_the_net_book_per_window(monkeypatch, tmp_path, built, capsys):
    root = world.build_root(tmp_path, **WALK_FORWARD)
    world.repoint(monkeypatch, train, root)
    calls = in_process_trainers(monkeypatch, root)
    dataset, metadata = built
    monkeypatch.setattr(train, "build_feature_dataset", lambda config: (dataset.copy(), copy.deepcopy(metadata)))
    monkeypatch.setattr(sys, "argv", ["train", "--walk-forward", "--include-multitask", "--include-sequence", "--metrics", "backtest_mcc,rank_20d_ic", "--step-days", "100", "--mode", "expanding"])
    assert train.main() == 0
    assert "train_multitask.py" in calls and "train_sequence.py" in calls and "Walk-forward run" in capsys.readouterr().out


def test_walk_forward_survives_a_trainer_that_fails_and_a_window_that_does_not_fit(monkeypatch, tmp_path, built, capsys):
    root = world.build_root(tmp_path, **WALK_FORWARD)
    world.repoint(monkeypatch, train, root)
    in_process_trainers(monkeypatch, root, returncodes={"train_multitask.py": 1})
    dataset, metadata = built
    monkeypatch.setattr(train, "build_feature_dataset", lambda config: (dataset.copy(), copy.deepcopy(metadata)))
    monkeypatch.setattr(sys, "argv", ["train", "--walk-forward", "--include-multitask"])
    assert train.main() == 0
    root2, code = run(monkeypatch, tmp_path / "toolong", built, ["--walk-forward", "--step-days", "10"], config_overrides={"phase_v2": {"retraining": {"walk_forward": {"train_span_days": 5000}}}})
    assert code == 0 and "no windows" in capsys.readouterr().out
