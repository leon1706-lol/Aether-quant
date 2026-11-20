"""scripts/build_example_models.py (V6.6.10): the zips, their manifests, a real trainer into a temporary folder, and the refusal to
publish a model whose hash is an installed one's."""

from __future__ import annotations

import hashlib
import json
import zipfile

import numpy as np
import pandas as pd
import pytest

from retraining import model_catalog as catalog
from script_loader import load_script


def _fake_train(kind, *, work, config_path, dataset, schema):
    version = work / "ml" / "versions" / kind
    version.mkdir(parents=True, exist_ok=True)
    entry = next(entry for entry in catalog.EXAMPLES.values() if entry["kind"] == kind)
    (version / entry["model"]).write_text(json.dumps({"kind": kind}), encoding="utf-8")
    (version / entry["schema"]).write_text(json.dumps({"model_input_names": list(catalog.FEATURES)}), encoding="utf-8")
    metrics = "sequence_training_metrics.json" if kind == "sequence" else "multitask_training_metrics.json"
    (version / metrics).write_text(json.dumps({"backtest": {"rank_20d_ic": {"mean_ic": 0.01}}}), encoding="utf-8")
    return version


def test_the_build_writes_checked_zips_and_their_manifest(tmp_path, monkeypatch, capsys):
    builder = load_script("build_example_models")
    monkeypatch.setattr(builder, "train", _fake_train)
    assert builder.main(["--out", str(tmp_path / "out")]) == 0
    manifest = json.loads((tmp_path / "out" / catalog.MANIFEST_ASSET).read_text(encoding="utf-8"))
    assert set(manifest["models"]) == set(catalog.EXAMPLES)
    for name, entry in manifest["models"].items():
        path = tmp_path / "out" / f"{name}.zip"
        assert catalog.sha256_file(path) == entry["sha256"] and catalog.zip_problems(path) == []
        assert "An example, not a trading model" in zipfile.ZipFile(path).read("card.md").decode("utf-8")
    assert '"example-crypto-seq"' in capsys.readouterr().out
    first = (tmp_path / "out" / "example-crypto-mlp.zip").read_bytes()
    builder.main(["--out", str(tmp_path / "out")])
    assert (tmp_path / "out" / "example-crypto-mlp.zip").read_bytes() == first, "the same files give the same zip"


def test_a_relative_out_lands_under_the_repo_and_a_pinned_hash_is_refused(tmp_path, monkeypatch):
    builder = load_script("build_example_models")
    monkeypatch.setattr(builder, "train", _fake_train)
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    (tmp_path / "config.json").write_text((builder.Path(builder.__file__).resolve().parents[1] / "config.json").read_text(encoding="utf-8"), encoding="utf-8")
    assert builder.main(["--out", "dist/ex"]) == 0 and (tmp_path / "dist" / "ex" / catalog.MANIFEST_ASSET).exists()
    pinned = hashlib.sha256(json.dumps({"kind": "multitask"}).encode("utf-8")).hexdigest()
    (tmp_path / "ml").mkdir()
    (tmp_path / "ml" / "artifact_pins.json").write_text(json.dumps({"files": {"multitask_model.json": pinned}}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="never published"):
        builder.main(["--out", "dist/ex2"])


def test_a_real_trainer_runs_into_the_work_folder_and_a_failure_is_raised(tmp_path):
    import train_multitask

    builder = load_script("build_example_models")
    ml_dir = train_multitask.ML_DIR
    rng = np.random.default_rng(1)
    index = [str(day.date()) for day in pd.bdate_range("2023-01-02", periods=420)]
    closes = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.02, (420, 8)), axis=0)), index=index, columns=[f"C{i}" for i in range(8)])
    frame = catalog.example_dataset(closes, splits={"train_end": "2023-12-31", "validation_end": "2024-03-31", "backtest_end": "2024-06-30"})
    frame.to_csv(tmp_path / "d.csv", index=False)
    (tmp_path / "s.json").write_text(json.dumps({"model_input_names": list(catalog.FEATURES)}), encoding="utf-8")
    config = builder.training_config(json.loads((builder.ROOT / "config.json").read_text(encoding="utf-8")))
    config["phase_v2"]["retraining"]["multitask_training"].update({"epochs": 1, "min_train_rows": 10, "min_validation_rows": 5, "min_backtest_rows": 5})
    (tmp_path / "c.json").write_text(json.dumps(config), encoding="utf-8")
    version = builder.train("multitask", work=tmp_path / "w", config_path=tmp_path / "c.json", dataset=tmp_path / "d.csv", schema=tmp_path / "s.json")
    assert (version / "multitask_model.json").exists() and str(version).startswith(str(tmp_path))
    with pytest.raises(RuntimeError, match="trainer failed"):
        builder.train("multitask", work=tmp_path / "w2", config_path=tmp_path / "missing.json", dataset=tmp_path / "d.csv", schema=tmp_path / "s.json")
    assert ml_dir == train_multitask.ML_DIR, "the trainer's ml folder is restored, so later in-process trainers write where they should"


def test_runs_as_a_script(monkeypatch, capsys):
    from script_loader import run_script

    assert run_script("build_example_models", ["--help"], monkeypatch) == 0
    assert "example models" in capsys.readouterr().out
