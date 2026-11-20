"""scripts/lowmem_proof.py (V6.6.10): the synthetic dataset, the verdict, and one real tiny run of both trainers under the low profile."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd

from script_loader import load_script, run_script


def test_the_dataset_has_the_asked_shape_and_every_split(tmp_path):
    proof = load_script("lowmem_proof")
    names = proof.write_dataset(tmp_path / "d.csv", rows=200, features=4, columns=30, tickers=10)
    frame = pd.read_csv(tmp_path / "d.csv")
    assert names == ["f000", "f001", "f002", "f003"] and len(frame) == 200 and frame.shape[1] == 30
    assert set(frame["split"]) == {"train", "validation", "backtest", "holdout"} and set(proof.TARGETS) <= set(frame.columns)


def test_the_verdict_fails_a_crash_a_missing_peak_and_a_peak_over_budget():
    proof = load_script("lowmem_proof")
    peaks = [{"stage": "multitask", "peak_gb": 1.0}, {"stage": "sequence", "peak_gb": 3.0}]
    assert proof.verdict(peaks, {"multitask": 0, "sequence": 0}, 2.6)["failed"] == {"sequence": "peak 3.0 GB > 2.6 GB"}
    assert proof.verdict(peaks[:1], {"multitask": 0, "sequence": 0}, 2.6)["failed"] == {"sequence": "no peak recorded"}
    assert proof.verdict([], {"multitask": 1}, 2.6)["failed"] == {"multitask": "exit 1"}
    assert proof.verdict(peaks, {"multitask": 0, "sequence": 0}, 4.0)["ok"] is True


def test_a_failing_runner_exits_one_and_cleans_up(tmp_path, capsys):
    proof = load_script("lowmem_proof")
    calls = []
    code = proof.main(["--rows", "60", "--features", "3", "--columns", "25", "--tickers", "6"], runner=lambda command, **kwargs: calls.append(command) or SimpleNamespace(returncode=2))
    assert code == 1 and len(calls) == 2 and "--memory-profile" in calls[0]
    assert json.loads(capsys.readouterr().out)["failed"] == {"multitask": "exit 2", "sequence": "exit 2"}


def test_a_tiny_real_run_trains_both_stages_within_budget(tmp_path, monkeypatch, capsys):
    code = run_script("lowmem_proof", ["--rows", "1200", "--features", "4", "--columns", "30", "--tickers", "20", "--epochs", "1", "--budget-gb", "8", "--work", str(tmp_path / "w")], monkeypatch)
    report = json.loads(capsys.readouterr().out)
    assert code == 0 and report["ok"] and set(report["peaks_gb"]) == {"multitask", "sequence"}
    assert not list((tmp_path / "w").glob("ml")), "the trainers wrote nothing into the working folder's own ml/"
