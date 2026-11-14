"""scripts/profile_inference.py's runtime (V6.6.6, #359): loading the exports on disk, the per-bar, sequence and pool workloads, and the whole `main()` report,
with the inference functions and the process pool replaced by recording fakes."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from concurrent.futures import Future

import pytest

import inference
import scripts.profile_inference as profile_inference


class Recorder:
    def __init__(self):
        self.calls = []

    def make(self, name):
        def call(*args, **kwargs):
            self.calls.append(name)
            return name

        return call


@pytest.fixture
def fakes(monkeypatch):
    recorder = Recorder()
    for name in ("run_exported_model", "run_exported_multitask_model", "run_exported_sequence_multitask_model", "run_exported_models_batched",
                 "run_exported_multitask_models_batched", "run_exported_sequence_multitask_model_batched", "run_symbol_inference"):
        monkeypatch.setattr(profile_inference, name, recorder.make(name))
    monkeypatch.setattr(profile_inference, "build_models_batched_cache", lambda exports: "stack")
    monkeypatch.setattr(profile_inference, "build_multitask_models_batched_cache", lambda exports: "multitask_stack")
    return recorder


def _exports(*, baseline=True, experts=True, sequence=True):
    names = profile_inference.EXPERT_NAMES
    return {
        "baseline": {"export": {"architecture": [{"in_features": 3}]}} if baseline else None, "multitask": {"m": 1}, "sequence": {"s": 1} if sequence else None,
        "experts": {name: ({"e": 1} if experts else None) for name in names}, "expert_multitask": {name: ({"em": 1} if experts else None) for name in names},
    }


def test_the_exports_on_disk_are_loaded_and_the_missing_ones_are_named(monkeypatch, tmp_path, capsys):
    converted = []
    monkeypatch.setattr(profile_inference, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(profile_inference, "convert_state_dict_arrays", lambda export: converted.append(export))
    ml = tmp_path / "ml"
    (ml / "expert_models" / "bullish").mkdir(parents=True)
    (ml / "model_weights.json").write_text(json.dumps({"export": 1}), encoding="utf-8")
    (ml / "expert_models" / "bullish" / "model_weights.json").write_text(json.dumps({"export": 2}), encoding="utf-8")
    loaded = profile_inference.load_real_exports()
    assert loaded["baseline"] == {"export": 1} and loaded["experts"]["bullish"] == {"export": 2} and loaded["sequence"] is None and len(converted) == 2
    assert "missing real exports" in capsys.readouterr().err and profile_inference._load_json(tmp_path / "nope.json") is None


def test_a_symbol_bar_runs_every_model_batched_or_one_by_one(fakes):
    inputs = [([0.1], [[0.2]]), ([0.3], [[0.4]])]
    durations = profile_inference.run_workload(_exports(), inputs, use_batched=False)
    assert len(durations) == 2 and fakes.calls.count("run_exported_model") == 2 * 5 and fakes.calls.count("run_exported_multitask_model") == 2 * 5
    fakes.calls.clear()
    profile_inference.run_workload(_exports(), inputs, use_batched=True, stack_cache="a", multitask_stack_cache="b")
    assert fakes.calls.count("run_exported_models_batched") == 2 and fakes.calls.count("run_exported_multitask_models_batched") == 2
    fakes.calls.clear()
    profile_inference.run_workload(_exports(baseline=False, experts=False, sequence=False) | {"multitask": None}, inputs, use_batched=True)
    assert fakes.calls == []


def test_the_sequence_workloads_time_each_symbol_and_each_bar(fakes):
    sequences = [[[0.1]], [[0.2]], [[0.3]], [[0.4]], [[0.5]]]
    assert len(profile_inference.run_sequence_unbatched_workload({"s": 1}, sequences)) == 5
    batched = profile_inference.run_sequence_batched_workload({"s": 1}, sequences, symbols_per_bar=2)
    assert len(batched) == 2 and fakes.calls.count("run_exported_sequence_multitask_model_batched") == 2


def test_the_sequential_baseline_runs_the_same_function_as_the_pool(fakes):
    inputs = [([0.1], [[0.2]])] * 5
    assert len(profile_inference.run_parallel_baseline_workload({}, inputs, sequence_window_size=1, symbols_per_bar=2)) == 3
    assert fakes.calls.count("run_symbol_inference") == 5


class FakePool:
    mode = "ok"

    def __init__(self, max_workers, initializer, initargs):
        if FakePool.mode == "init_fail":
            raise RuntimeError("no pool")
        self.closed = False

    def submit(self, function, *args):
        if FakePool.mode == "submit_fail":
            raise RuntimeError("broken pool")
        future = Future()
        future.set_result(function(*args))
        return future

    def shutdown(self, wait):
        self.closed = True


@pytest.mark.parametrize("mode,expect_none", [("ok", False), ("init_fail", True), ("submit_fail", True)])
def test_the_pool_benchmark_reports_durations_or_degrades_to_none(fakes, monkeypatch, mode, expect_none):
    monkeypatch.setattr(profile_inference, "ProcessPoolExecutor", FakePool)
    FakePool.mode = mode
    inputs = [([0.1], [[0.2]])] * 5
    result = profile_inference.run_parallel_workload({}, inputs, sequence_window_size=1, symbols_per_bar=2, max_workers=2)
    assert (result is None) == expect_none and (expect_none or len(result) == 3)


def _run_main(monkeypatch, tmp_path, capsys, argv, exports, pool_mode="ok"):
    FakePool.mode = pool_mode
    monkeypatch.setattr(profile_inference, "ProcessPoolExecutor", FakePool)
    monkeypatch.setattr(profile_inference, "load_real_exports", lambda: exports)
    monkeypatch.setattr(profile_inference, "OUTPUT_PATH", tmp_path / "profile.txt")
    monkeypatch.setattr(sys, "argv", ["profile_inference", *argv])
    profile_inference.main()
    return capsys.readouterr().out, (tmp_path / "profile.txt").read_text(encoding="utf-8")


def test_the_plain_report_has_tail_latency_and_pstats(fakes, monkeypatch, tmp_path, capsys):
    out, written = _run_main(monkeypatch, tmp_path, capsys, ["--iterations", "6"], _exports())
    assert "Tail latency" in out and "p99_ms" in written and "bucket" not in out and "Sequence-encoder" not in out and "ProcessPool" not in out


def test_every_optional_section_is_reported_when_asked_for(fakes, monkeypatch, tmp_path, capsys):
    out, written = _run_main(monkeypatch, tmp_path, capsys, ["--iterations", "6", "--batched", "--bucket-report", "--no-gc", "--parallel", "--symbols-per-bar", "2", "--pool-workers", "2"], _exports())
    assert "bucket 0" in out and "Sequence-encoder symbol-batching comparison" in out and "process-pool, per BAR" in out and "verdict" in out and "bucket 0" in written


def test_a_failing_pool_is_reported_and_a_missing_baseline_uses_the_default_width(fakes, monkeypatch, tmp_path, capsys):
    out, _ = _run_main(monkeypatch, tmp_path, capsys, ["--iterations", "4", "--parallel", "--symbols-per-bar", "2"], _exports(baseline=False, sequence=False), pool_mode="init_fail")
    assert "process-pool: FAILED" in out


def test_without_batched_functions_the_workloads_fall_back_to_the_loop(monkeypatch, tmp_path):
    fake = types.ModuleType("inference")
    for name in ("convert_state_dict_arrays", "init_worker", "run_exported_model", "run_exported_multitask_model", "run_exported_sequence_multitask_model", "run_symbol_inference"):
        setattr(fake, name, getattr(inference, name))
    monkeypatch.setitem(sys.modules, "inference", fake)
    spec = importlib.util.spec_from_file_location("profile_inference_fallback", profile_inference.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.run_exported_models_batched is None and module.build_models_batched_cache is None and module.run_exported_sequence_multitask_model_batched is None
    monkeypatch.setattr(module, "run_exported_model", lambda export, inputs: None)
    monkeypatch.setattr(module, "run_exported_multitask_model", lambda export, inputs: None)
    monkeypatch.setattr(module, "run_exported_sequence_multitask_model", lambda export, inputs: None)
    assert len(module.run_workload(_exports(), [([0.1], [[0.2]])], use_batched=True)) == 1
