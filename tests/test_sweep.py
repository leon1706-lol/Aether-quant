"""lab/sweep.py: a grid parses, every point is a counted run (failures too), a resumed sweep skips its finished points, and
the sweep is judged by its PBO."""

from __future__ import annotations

import json

import pytest

from lab import sweep, trainer
from lab_world import make_lab


def test_grids_parse_with_lists_sections_and_text():
    grid = sweep.parse_grid("lr=1e-3,3e-4 hidden=[64,32],[128] train.loss=mse,listnet")
    assert grid == {"train.lr": [0.001, 0.0003], "model.hidden": [[64, 32], [128]], "train.loss": ["mse", "listnet"]}
    assert len(sweep.grid_points(grid)) == 8 and len(sweep.grid_points(grid, random_k=3, seed=1)) == 3
    assert sweep.as_overrides({"train.lr": 0.1, "model.hidden": [8]}) == {"train": {"lr": 0.1}, "model": {"hidden": [8]}}
    with pytest.raises(ValueError, match="key=v1,v2"):
        sweep.parse_grid("lr")
    with pytest.raises(ValueError, match="empty"):
        sweep.parse_grid("  ")


def test_a_sweep_trains_counts_resumes_and_reports_its_pbo(tmp_path):
    lab = make_lab(tmp_path / "lab")
    calls = []

    def train(lab_dir, model, **kwargs):
        calls.append(kwargs["overrides"])
        if kwargs["overrides"]["model"]["ridge"] == 3.0:
            raise RuntimeError("diverged")
        return trainer.train_run(lab_dir, model, **kwargs)

    grid = {"model.ridge": [0.1, 10.0, 3.0]}
    state = sweep.run_sweep(lab, "lin", grid, train=train, log=lambda line: None)
    assert [item["status"] for item in state["points"]] == ["finished", "finished", "failed: diverged"]
    rows = [json.loads(line) for line in (lab / "trials.jsonl").read_text(encoding="utf-8").splitlines()]
    failed = [row for row in rows if (row.get("detail") or {}).get("failed") == "diverged"]
    assert len(failed) == 1 and failed[0]["role"] == "candidate", "a failed point counts toward N too"
    assert state["best"]["oof_ic"] > 0 and state["pbo"]["days"] >= 32 and state["pbo"]["value"] is not None
    saved = json.loads((lab / "runs" / "sweep_lin.json").read_text(encoding="utf-8"))
    assert len(saved["points"]) == 3
    calls.clear()
    lines: list[str] = []
    sweep.run_sweep(lab, "lin", grid, train=train, log=lines.append)
    assert calls == [] and sum("done earlier" in line for line in lines) == 3, "a resumed sweep retrains nothing it has"
    with pytest.raises(ValueError, match="past --max-trials 4"):
        sweep.run_sweep(lab, "lin", {"model.ridge": [1.0, 2.0]}, train=train, max_trials=4, trials_now=3)


def test_pbo_needs_two_runs_and_enough_common_days(tmp_path):
    lab = make_lab(tmp_path / "lab")
    record = trainer.train_run(lab, "lin", log=lambda line: None)
    assert sweep.sweep_pbo(lab, [record["id"]]) is None
    assert sweep.run_sweep(lab, "lin", {"model.ridge": [1.0]}, train=lambda *a, **k: (_ for _ in ()).throw(ValueError("x")), log=lambda line: None)["best"] is None


def test_a_sweep_with_few_common_days_reports_why_it_has_no_pbo(tmp_path, monkeypatch):
    import pandas as pd

    short = {"a": pd.Series([0.01] * 10, index=range(10)), "b": pd.Series([0.02] * 10, index=range(10))}
    from lab import run_evaluation

    monkeypatch.setattr(run_evaluation, "load_run_frame", lambda run_dir: (None, run_dir.name, None))
    monkeypatch.setattr(run_evaluation, "spread_returns", lambda frame, column: short[column])
    assert sweep.sweep_pbo(tmp_path, ["a", "b"]) == {"value": None, "reason": "only 10 common days; PBO needs at least 32"}
    assert sweep.sweep_pbo(tmp_path, ["a"]) is None
