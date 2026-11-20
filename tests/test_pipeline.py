"""evaluation/pipeline.py (V6.6.10): the one-command pipeline's file, stages, resume and gate."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from evaluation import pipeline


def _closes(sessions=260, names=6, seed=0, drift=0.0):
    rng = np.random.default_rng(seed)
    index = [str(day.date()) for day in pd.bdate_range("2023-01-02", periods=sessions)]
    returns = rng.normal(0, 0.02, (sessions, names)) + drift * np.arange(names) / names
    return pd.DataFrame(100 * np.exp(np.cumsum(returns, axis=0)), index=index, columns=[f"T{i}" for i in range(names)])


def test_the_file_merges_over_the_defaults_and_no_file_is_the_smoke_run(tmp_path):
    assert pipeline.load_pipeline(None)["pipeline"]["signal"] == pipeline.SMOKE_SIGNAL
    path = tmp_path / "pipeline.toml"
    path.write_text('[pipeline]\nname = "x"\ndata = "c.csv"\n\n[gate]\nmin_ic = 0.5\n\n[extra]\nk = 1\n', encoding="utf-8")
    spec = pipeline.load_pipeline(path)
    assert spec["pipeline"]["name"] == "x" and spec["pipeline"]["signal"] == "my_signal.py" and spec["gate"] == {"horizon": 20, "min_ic": 0.5, "min_t": 2.0}
    assert spec["extra"] == {"k": 1} and spec["root"] == str(tmp_path.resolve())


def test_closes_and_signals_load_from_the_sample_a_csv_or_a_file(tmp_path):
    assert pipeline.load_closes("sample", root=tmp_path).shape[1] == 11
    _closes().to_csv(tmp_path / "c.csv", index_label="date")
    assert pipeline.load_closes("c.csv", root=tmp_path).shape == (260, 6)
    assert pipeline.load_signal(pipeline.SMOKE_SIGNAL, root=tmp_path) is pipeline.momentum_20
    (tmp_path / "good.py").write_text("def score(closes):\n    return closes * 0 + 1\n", encoding="utf-8")
    assert pipeline.load_signal("good.py", root=tmp_path)(_closes()).iloc[0, 0] == 1
    (tmp_path / "bad.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(AttributeError, match="no score"):
        pipeline.load_signal("bad.py", root=tmp_path)
    with pytest.raises(FileNotFoundError, match="no signal file"):
        pipeline.load_signal("signal.txt", root=tmp_path)


def test_the_gate_reads_the_horizon_it_was_given():
    report = {"term_structure": {20: {"mean_ic": 0.05, "t_hac": 3.0}, "5": {"mean_ic": 0.01, "t_hac": 1.0}}}
    assert pipeline.gate_verdict(report, {"horizon": 20, "min_ic": 0.02, "min_t": 2.0})["passed"] is True
    assert pipeline.gate_verdict(report, {"horizon": 5, "min_ic": 0.02, "min_t": 2.0})["passed"] is False, "a JSON report keys horizons by string"
    assert pipeline.gate_verdict({}, {"horizon": 60, "min_ic": 0.0, "min_t": 0.0})["passed"] is False


def test_stages_resume_and_a_failed_stage_reruns(tmp_path):
    calls = []

    def boom():
        raise RuntimeError("reboot")

    actions = {name: (lambda name=name: calls.append(name) or name) for name in ("a", "b")}
    with pytest.raises(RuntimeError):
        pipeline.run_stages(["a", "b"], {**actions, "b": boom}, state_path=tmp_path / "s.json", emit=lambda _: None)
    pipeline.run_stages(["a", "b"], actions, state_path=tmp_path / "s.json", emit=lambda _: None)
    assert calls == ["a", "b"] and list(json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))["done"]) == ["a", "b"]


def test_a_whole_run_with_a_trained_model_writes_the_report(tmp_path):
    closes = _closes(drift=0.004)
    closes.to_csv(tmp_path / "c.csv", index_label="date")
    (tmp_path / "pipeline.toml").write_text('[pipeline]\nname = "t"\ndata = "c.csv"\nsignal = "momentum_20"\ntrain = true\n\n[gate]\nhorizon = 5\nmin_ic = -1.0\nmin_t = -100.0\n',
                                            encoding="utf-8")
    spec = pipeline.load_pipeline(tmp_path / "pipeline.toml")
    scored = lambda prices, work: pipeline.momentum_20(prices).stack().rename("score").reset_index().set_axis(["date", "ticker", "score"], axis=1)  # noqa: E731
    run_dir = tmp_path / "runs" / "r1"
    state = pipeline.run_stages(pipeline.STAGES, pipeline.pipeline_actions(spec, run_dir=run_dir, train_model=scored), state_path=run_dir / "state.json", emit=lambda _: None)
    assert set(state["done"]["gate"]["result"]) == {"signal", "model"} and all(v["passed"] for v in state["done"]["gate"]["result"].values())
    assert "PASS" in (run_dir / "report.md").read_text(encoding="utf-8") and json.loads((run_dir / "report.json").read_text(encoding="utf-8"))["name"] == "t"
    skipped = pipeline.pipeline_actions(pipeline.load_pipeline(None), run_dir=tmp_path / "runs" / "r2")
    assert skipped["train"]() == {"skipped": "train = false"}


def test_the_example_model_trains_and_scores_from_a_source_checkout(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    scores = pipeline.train_example_model(_closes(sessions=900, names=8), tmp_path / "model")
    assert {"date", "ticker", "score"} <= set(scores.columns) and scores["score"].notna().any()
    monkeypatch.setattr(pipeline, "__file__", str(tmp_path / "elsewhere" / "evaluation" / "pipeline.py"))
    with pytest.raises(FileNotFoundError, match="source checkout"):
        pipeline.train_example_model(_closes(), tmp_path / "m2")
