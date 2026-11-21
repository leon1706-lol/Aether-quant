"""lab/model_export.py: a lab run becomes an aq models zip that installs and scores with numpy, matching the run's own scores."""

from __future__ import annotations

import json
import zipfile

import pandas as pd
import pytest

from lab import model_export, trainer
from lab_world import make_lab, planted_closes
from retraining import model_catalog


def _round_trip(tmp_path, lab, run, name):
    zip_path = tmp_path / f"{name}.zip"
    result = model_export.export_run(run, zip_path, card="# card\n")
    assert model_catalog.zip_problems(zip_path) == [] and "manifest.json" in result["files"]
    folder = model_catalog.install_zip(zip_path, name=name, root=tmp_path / "cache", allow_unlisted=True)
    model = model_catalog.load(name, root=tmp_path / "cache")
    scores = model_catalog.score(model, planted_closes(), head="rank_20d")
    own = pd.read_csv(run / "scores.csv", dtype={"date": str, "ticker": str})
    merged = own.merge(scores, on=["date", "ticker"])
    return folder, model, merged


def test_a_linear_export_scores_exactly_as_the_run_did(tmp_path):
    lab = make_lab(tmp_path / "lab")
    run = lab / "runs" / trainer.train_run(lab, "lin", log=lambda line: None)["id"]
    _, model, merged = _round_trip(tmp_path, lab, run, "lab-lin")
    assert model["kind"] == "linear" and model["lab_features"]["features"][0] == "ret_1"
    assert len(merged) > 1000 and (merged["score_rank_20d"] - merged["score"]).abs().max() < 1e-6
    again = model_export.export_run(run, tmp_path / "again.zip", card="# card\n")
    assert again["sha256"] == model_export.export_run(run, tmp_path / "third.zip", card="# card\n")["sha256"], "the same run gives the same bytes"


@pytest.mark.parametrize(("template", "kind"), [("multitask", "multitask"), ("tcn", "sequence"), ("mlp", "baseline")])
def test_a_network_export_scores_like_the_run(tmp_path, template, kind):
    pytest.importorskip("torch")
    lab = make_lab(tmp_path / "lab", models={"m": template}, epochs=1)
    run = lab / "runs" / trainer.train_run(lab, "m", log=lambda line: None)["id"]
    _, model, merged = _round_trip(tmp_path, lab, run, f"lab-{template}")
    assert model["kind"] == kind and len(merged) > 1000
    assert merged[["score_rank_20d", "score"]].corr().iloc[0, 1] > 0.999


def test_the_zip_carries_its_manifest_and_refuses_other_templates(tmp_path):
    files = {"a.txt": b"x"}
    digest = model_export.write_zip(tmp_path / "z.zip", files)
    with zipfile.ZipFile(tmp_path / "z.zip") as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["source"] == "lab" and set(manifest["files"]) == {"a.txt"} and archive.getinfo("a.txt").date_time == model_export.FIXED_TIME
    assert len(digest) == 64
    run = tmp_path / "run"
    run.mkdir()
    (run / "run.json").write_text(json.dumps({"template": "production", "features": [], "seeds": [1], "target": "target_rank_20d"}), encoding="utf-8")
    with pytest.raises(ValueError, match="export supports"):
        model_export.export_files(run, card="")
