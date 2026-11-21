"""`aq models` (V6.6.10): list, install (a release or a local zip), info and score, against a temporary cache."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile

import pandas as pd

import aq_cli
from retraining import model_catalog as catalog


def _example_zip(path, *, card=b"# example card"):
    export = {"export": {"trunk": [{"type": "linear", "weight_key": "w", "bias_key": "b"}], "heads": {"rank_20d": [{"type": "linear", "weight_key": "h", "bias_key": "hb"}]},
                         "state_dict": {"w": [[1.0] * 6], "b": [0.0], "h": [[1.0]], "hb": [0.0]}}}
    files = {"multitask_model.json": json.dumps(export).encode(), "multitask_feature_schema.json": json.dumps({"model_input_names": list(catalog.FEATURES)}).encode()}
    if card is not None:
        files["card.md"] = card
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("manifest.json", json.dumps({"files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}))
    return path


def _run(root, command, **extra):
    return aq_cli.cmd_models(argparse.Namespace(models_command=command, **extra), root=root)


def test_list_install_info_and_score(tmp_path, capsys):
    root = tmp_path / "cache"
    assert _run(root, "list") == 0 and "not installed" in capsys.readouterr().out
    assert _run(root, "install", name="example-crypto-mlp", version=None, from_zip=str(_example_zip(tmp_path / "m.zip"))) == 0
    assert "installed example-crypto-mlp" in capsys.readouterr().out
    assert _run(root, "list") == 0 and "installed " in capsys.readouterr().out
    assert _run(root, "info", name="example-crypto-mlp") == 0 and "# example card" in capsys.readouterr().out
    assert _run(root, "score", name="example-crypto-mlp", csv=None, head="rank_20d", out=None) == 0
    printed = capsys.readouterr().out
    assert "BTCUSD" in printed and "score" in printed
    closes = pd.DataFrame({f"C{i}": [100.0 + i + 0.5 * day * (1 + (i % 3)) for day in range(90)] for i in range(5)}, index=[str(d.date()) for d in pd.bdate_range("2024-01-01", periods=90)])
    closes.index.name = "date"
    closes.to_csv(tmp_path / "closes.csv")
    assert _run(root, "score", name="example-crypto-mlp", csv=str(tmp_path / "closes.csv"), head="rank_20d", out=str(tmp_path / "s.csv")) == 0
    assert set(pd.read_csv(tmp_path / "s.csv").columns) == {"date", "ticker", "score"}


def test_a_card_less_model_and_the_release_path(tmp_path, monkeypatch, capsys):
    root = tmp_path / "cache"
    _run(root, "install", name="example-crypto-mlp", version=None, from_zip=str(_example_zip(tmp_path / "m.zip", card=None)))
    capsys.readouterr()
    assert _run(root, "info", name="example-crypto-mlp") == 0 and "(no model card)" in capsys.readouterr().out
    monkeypatch.setattr(catalog, "install", lambda name, version, root: root / name)
    assert _run(root, "install", name="example-crypto-seq", version="6.6.10", from_zip=None) == 0


def test_a_refusal_is_an_exit_code_with_the_reason(tmp_path, capsys):
    assert _run(tmp_path, "install", name="nope", version=None, from_zip=None) == 1
    assert "unknown example" in capsys.readouterr().err
    assert _run(tmp_path, "install", name="my-lab-model", version=None, from_zip=str(_example_zip(tmp_path / "m.zip"))) == 0, "a zip from aq lab export installs by any name"
    capsys.readouterr()
    assert _run(tmp_path, "info", name="example-crypto-seq") == 1


def test_the_parser_routes_models():
    out = subprocess.run([sys.executable, str(aq_cli.ROOT_DIR / "aq_cli.py"), "models", "--help"], capture_output=True, text=True, check=False).stdout
    assert "install" in out and "score" in out


def test_list_and_info_print_json_and_remove_asks_for_an_installed_model(tmp_path, capsys):
    root = tmp_path / "cache"
    assert _run(root, "install", name="my-lab", version=None, from_zip=str(_example_zip(tmp_path / "m.zip"))) == 0
    capsys.readouterr()
    assert _run(root, "list", json=True) == 0
    rows = {row["name"]: row for row in json.loads(capsys.readouterr().out)}
    assert rows["my-lab"]["kind"] == "lab" and rows["example-crypto-mlp"]["installed"] is False
    assert _run(root, "info", name="my-lab", json=True) == 0 and json.loads(capsys.readouterr().out)["card"] == "# example card"
    assert _run(root, "remove", name="nothing", dry_run=False) == 1 and "is not installed" in capsys.readouterr().err
    assert _run(root, "remove", name="my-lab", dry_run=True) == 0 and (root / "my-lab").is_dir()
    assert _run(root, "remove", name="my-lab", dry_run=False) == 0 and not (root / "my-lab").exists()
