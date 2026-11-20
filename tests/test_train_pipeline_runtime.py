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
    _root2, code = run(monkeypatch, tmp_path / "toolong", built, ["--walk-forward", "--step-days", "10"], config_overrides={"phase_v2": {"retraining": {"walk_forward": {"train_span_days": 5000}}}})
    assert code == 0 and "no windows" in capsys.readouterr().out


def test_a_low_profile_candidate_writes_its_own_dataset(monkeypatch, tmp_path, built):
    """V6.6.10: `--write-dataset` leaves the run's dataset beside its schema, for the stack's later trainers (#385)."""
    root, code = run(monkeypatch, tmp_path, built, ["--candidate", "--version-id", "cand2", "--write-dataset", "--memory-profile", "low"])
    version = root / "ml" / "versions" / "cand2"
    written = pd.read_csv(version / "full_dataset.csv")
    assert code == 0 and len(written) == len(built[0]) and (version / "feature_schema.json").exists()


def test_a_low_profile_walk_forward_passes_the_profile_to_each_window_and_reads_back_in_float32(monkeypatch, tmp_path, built, capsys):
    overrides = copy.deepcopy(WALK_FORWARD)
    overrides["phase_v2"]["retraining"]["walk_forward"].update({"train_sequence": True, "net_performance": True})
    root = world.build_root(tmp_path, **overrides)
    world.repoint(monkeypatch, train, root)
    seen = []
    calls = in_process_trainers(monkeypatch, root)
    real_run = train.subprocess.run

    timeouts = []

    def recording(command, **kwargs):
        seen.append(command)
        timeouts.append(kwargs.get("timeout"))
        return real_run(command, **kwargs)

    monkeypatch.setattr(train.subprocess, "run", recording)
    dataset, metadata = built
    monkeypatch.setattr(train, "build_feature_dataset", lambda config: (dataset.copy(), copy.deepcopy(metadata)))
    monkeypatch.setattr(sys, "argv", ["train", "--walk-forward", "--memory-profile", "low"])
    assert train.main() == 0 and "train_sequence.py" in calls
    assert all(command[-2:] == ["--memory-profile", "low"] for command in seen)
    assert set(timeouts) == {2400 * 4}, "#408: a low-profile trainer gets four times the configured timeout"
    assert "Walk-forward run" in capsys.readouterr().out


def test_a_walk_forward_writes_its_run_id_where_asked_at_once(monkeypatch, tmp_path, built):
    """V6.6.10: `--run-id-file` records the id before the first window, so `aq cycle retrain --resume` finds a stopped run."""
    target = tmp_path / "cycle" / "walk_forward_run_id"
    _root, code = run(monkeypatch, tmp_path, built, ["--walk-forward", "--run-id-file", str(target)], config_overrides=WALK_FORWARD)
    assert code == 0 and target.read_text(encoding="utf-8").strip().startswith("walk-forward-")


def test_a_resumed_window_reuses_a_finished_trainer_and_continues_the_sequence_checkpoint(monkeypatch, tmp_path):
    """V6.6.10: inside a resumed walk-forward, a trainer that already finished in the window is not run again, and the sequence
    trainer continues from its per-epoch checkpoint under the low profile."""
    monkeypatch.setattr(train, "ML_DIR", tmp_path / "ml")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        version = tmp_path / "ml" / "versions" / "run" / "window_0"
        version.mkdir(parents=True, exist_ok=True)
        name = "sequence_training_metrics.json" if "train_sequence.py" in command[1] else "multitask_training_metrics.json"
        (version / name).write_text(json.dumps({"ran": True}), encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(train.subprocess, "run", fake_run)
    paths = (tmp_path / "d.csv", tmp_path / "s.json", tmp_path / "c.json")
    assert train._run_walk_forward_trainer("train_sequence.py", "run/window_0", *paths, timeout_seconds=5, memory_profile="low", resume=True) == {"ran": True}
    assert "--resume" in calls[-1]
    assert train._run_walk_forward_trainer("train_sequence.py", "run/window_0", *paths, timeout_seconds=5, memory_profile="low", resume=True) == {"ran": True}
    assert len(calls) == 1, "a finished trainer is not run again on resume"
    train._run_walk_forward_trainer("train_multitask.py", "run/window_0", *paths, timeout_seconds=5, memory_profile="low", resume=True)
    assert "--resume" not in calls[-1], "only the sequence trainer keeps a checkpoint"
    train._run_walk_forward_trainer("train_sequence.py", "run/window_0", *paths, timeout_seconds=5, memory_profile="standard", resume=False)
    assert "--resume" not in calls[-1] and len(calls) == 3, "a fresh run always trains"


def test_a_resumed_window_reuses_a_complete_dataset_and_baseline_and_rebuilds_a_torn_one(monkeypatch, tmp_path, built):
    """V6.6.10: a resumed window takes its dataset back when its completion marker is there, and its baseline when that marker is too;
    the baseline trained again on the dataset read back from its CSV scores as before, and a dataset without its marker is rebuilt."""
    target = tmp_path / "run_id"
    root, code = run(monkeypatch, tmp_path, built, ["--walk-forward", "--run-id-file", str(target)], config_overrides=WALK_FORWARD)
    run_id = target.read_text(encoding="utf-8").strip()
    windows = sorted((root / "ml" / "versions" / run_id).glob("window_*"))
    first = json.loads((windows[0] / "window_result.json").read_text(encoding="utf-8"))["backtest_mcc"]
    assert code == 0 and len(windows) >= 3 and all((window / "dataset_complete.json").exists() and (window / "baseline_complete.json").exists() for window in windows)
    for window in windows:
        (window / "window_result.json").unlink()
    (windows[0] / "baseline_complete.json").unlink()
    (windows[1] / "dataset_complete.json").unlink()
    builds, trained = [], []
    dataset, metadata = built
    monkeypatch.setattr(train, "build_feature_dataset", lambda config: builds.append(1) or (dataset.copy(), copy.deepcopy(metadata)))
    real_train = train.train_model
    monkeypatch.setattr(train, "train_model", lambda *args, **kwargs: trained.append(1) or real_train(*args, **kwargs))
    monkeypatch.setattr(sys, "argv", ["train", "--walk-forward", "--resume-run-id", run_id])
    assert train.main() == 0
    assert builds == [1], "only the window whose dataset was torn is built again"
    assert trained == [1, 1], "window 0 retrains on its read-back dataset, window 1 after its rebuild, the rest reuse their baselines"
    assert json.loads((windows[0] / "window_result.json").read_text(encoding="utf-8"))["backtest_mcc"] == pytest.approx(first)
    assert train._reusable_window_parts(train.candidate_output_paths(f"{run_id}/window_0"))["metrics"]["backtest"]


def test_a_failed_or_timed_out_window_trainer_marks_its_window_for_a_retry(monkeypatch, tmp_path):
    """#408: a window trainer that times out or exits non-zero leaves `<trainer>.failed`; a resumed walk-forward then retries that window
    instead of loading it as complete, and a later success clears the marker."""
    import subprocess

    monkeypatch.setattr(train, "ML_DIR", tmp_path / "ml")
    window = tmp_path / "ml" / "versions" / "run" / "window_0"
    window.mkdir(parents=True)
    (window / "window_result.json").write_text(json.dumps({"window_result": {"w": 1}, "backtest_mcc": 0.1}), encoding="utf-8")
    assert train._load_walk_forward_window_result("run", 0) is not None
    paths = (tmp_path / "d.csv", tmp_path / "s.json", tmp_path / "c.json")

    def timing_out(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(train.subprocess, "run", timing_out)
    assert train._run_walk_forward_trainer("train_sequence.py", "run/window_0", *paths, timeout_seconds=5) is None
    assert "TimeoutExpired" in (window / "train_sequence.failed").read_text(encoding="utf-8")
    assert train._load_walk_forward_window_result("run", 0) is None, "a window with a failed trainer is retried"
    monkeypatch.setattr(train.subprocess, "run", lambda command, **kwargs: types.SimpleNamespace(returncode=2, stderr="boom", stdout=""))
    assert train._run_walk_forward_trainer("train_multitask.py", "run/window_0", *paths, timeout_seconds=5) is None
    assert (window / "train_multitask.failed").read_text(encoding="utf-8").strip() == "exit 2"

    def succeeding(command, **kwargs):
        name = "sequence_training_metrics.json" if "train_sequence.py" in command[1] else "multitask_training_metrics.json"
        (window / name).write_text(json.dumps({"ran": True}), encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(train.subprocess, "run", succeeding)
    for script in ("train_sequence.py", "train_multitask.py"):
        assert train._run_walk_forward_trainer(script, "run/window_0", *paths, timeout_seconds=5) == {"ran": True}
    assert not list(window.glob("*.failed")) and train._load_walk_forward_window_result("run", 0) is not None
