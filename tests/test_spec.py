"""lab/spec.py: a model's config merges defaults, the lab's and its own, validates, and takes one-run overrides."""

from __future__ import annotations

import sys

import pytest

from lab import spec


def test_the_config_merges_lab_and_model_files_and_overrides(tmp_path):
    (tmp_path / "lab.toml").write_text('[train]\nseeds = [1, 2]\nepochs = 5\n', encoding="utf-8")
    model = tmp_path / "models" / "m1"
    model.mkdir(parents=True)
    (model / "config.toml").write_text('[model]\ntemplate = "linear"\n[train]\nepochs = 7\n', encoding="utf-8")
    merged = spec.load_spec(model, lab_dir=tmp_path, overrides={"train": {"lr": 0.01}})
    assert merged["model"]["template"] == "linear" and merged["model"]["name"] == "m1"
    assert merged["train"]["seeds"] == [1, 2] and merged["train"]["epochs"] == 7 and merged["train"]["lr"] == 0.01
    assert merged["train"]["loss"] == spec.DEFAULTS["train"]["loss"], "untouched defaults stay"
    assert spec.load_spec(tmp_path / "models" / "none", lab_dir=None)["model"]["template"] == "multitask"


def test_every_problem_is_named_at_once(tmp_path):
    bad = spec.merge(spec.DEFAULTS, {"model": {"template": "rnn"}, "train": {"loss": "hinge", "seeds": [], "epochs": 0, "memory_profile": "huge"},
                                     "data": {"target": "rank_20d"}})
    problems = spec.validate(bad)
    assert len(problems) == 6
    assert any("template" in line for line in problems) and any("seeds" in line for line in problems) and any("train.epochs" in line for line in problems)
    with pytest.raises(ValueError, match="model.template"):
        spec.load_spec(tmp_path, overrides={"model": {"template": "rnn"}})


def test_overrides_parse_as_json_or_text():
    assert spec.parse_override("train.lr=3e-4") == {"train": {"lr": 0.0003}}
    assert spec.parse_override("model.hidden=[64,32]") == {"model": {"hidden": [64, 32]}}
    assert spec.parse_override("train.loss=listnet") == {"train": {"loss": "listnet"}}
    with pytest.raises(ValueError, match="section.key=value"):
        spec.parse_override("lr")


def test_a_toml_config_on_python_3_10_says_it_needs_3_11(tmp_path, monkeypatch):
    (tmp_path / "c.toml").write_text("[model]\n", encoding="utf-8")
    monkeypatch.setattr(sys, "version_info", (3, 10, 0))
    with pytest.raises(ValueError, match="3.11"):
        spec.read_toml(tmp_path / "c.toml")
