"""evaluation/project_template.py and `aq init` / `aq pipeline` (V6.6.10): a new project is written from the template, its own tests
pass, and its pipeline runs end to end."""

from __future__ import annotations

import argparse
import subprocess
import sys

import pytest

import aq_cli
from evaluation import project_template


def test_the_template_lists_every_file_by_its_project_path():
    files = project_template.template_files()
    assert set(files) == {".gitignore", ".github/workflows/pipeline.yml", "README.md", "pipeline.toml", "my_signal.py", "tests/test_signal.py"}


def test_a_project_is_written_rendered_and_never_over_an_existing_one(tmp_path):
    written = project_template.create_project(tmp_path / "alpha", version="6.6.10")
    assert "my_signal.py" in written and "signal.py" not in written and (tmp_path / "alpha" / ".github" / "workflows" / "pipeline.yml").exists()
    assert 'name = "alpha"' in (tmp_path / "alpha" / "pipeline.toml").read_text(encoding="utf-8")
    assert "aether-quant==6.6.10" in (tmp_path / "alpha" / ".github" / "workflows" / "pipeline.yml").read_text(encoding="utf-8")
    with pytest.raises(FileExistsError, match="not empty"):
        project_template.create_project(tmp_path / "alpha")
    (tmp_path / "empty").mkdir()
    assert project_template.create_project(tmp_path / "empty", name="named") and "# named" in (tmp_path / "empty" / "README.md").read_text(encoding="utf-8")


def test_the_new_projects_own_tests_pass_and_its_pipeline_runs(tmp_path, monkeypatch, capsys):
    project = tmp_path / "proj"
    assert aq_cli.cmd_init(argparse.Namespace(directory=str(project), name=None)) == 0
    assert "next: cd" in capsys.readouterr().out
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"], cwd=project, capture_output=True, text=True, check=False)
    assert tests.returncode == 0, tests.stdout + tests.stderr
    monkeypatch.chdir(project)
    code = aq_cli.cmd_pipeline(argparse.Namespace(pipeline_command="run", config=None, run_id="r1", runs_dir="runs"))
    out = capsys.readouterr().out
    assert code in (0, 3) and "# proj" in out and (project / "runs" / "r1" / "report.md").exists()
    assert aq_cli.cmd_pipeline(argparse.Namespace(pipeline_command="status", config=None, run_id=None, runs_dir="runs")) == 0
    assert "6/6 stages" in capsys.readouterr().out
    assert aq_cli.cmd_pipeline(argparse.Namespace(pipeline_command="status", config=None, run_id="r1", runs_dir="runs")) == 0


def test_init_refuses_and_the_pipeline_reports_its_failures(tmp_path, monkeypatch, capsys):
    (tmp_path / "taken").mkdir()
    (tmp_path / "taken" / "x").write_text("x", encoding="utf-8")
    assert aq_cli.cmd_init(argparse.Namespace(directory=str(tmp_path / "taken"), name=None)) == 1 and "not empty" in capsys.readouterr().err
    monkeypatch.chdir(tmp_path)
    assert aq_cli.cmd_pipeline(argparse.Namespace(pipeline_command="status", config=None, run_id=None, runs_dir="runs")) == 1
    assert aq_cli.cmd_pipeline(argparse.Namespace(pipeline_command="run", config=str(tmp_path / "missing.toml"), run_id=None, runs_dir="runs")) == 1
    strict = tmp_path / "strict.toml"
    strict.write_text('[pipeline]\nsignal = "momentum_20"\n\n[gate]\nmin_ic = 0.9\n', encoding="utf-8")
    assert aq_cli.cmd_pipeline(argparse.Namespace(pipeline_command="run", config=str(strict), run_id=None, runs_dir="runs")) == 3, "a failed gate is its own exit code"


def test_the_smoke_run_needs_no_file_and_the_version_falls_back(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert aq_cli.cmd_pipeline(argparse.Namespace(pipeline_command="run", config=None, run_id="smoke", runs_dir="runs")) in (0, 3)
    assert "the sample and 20-session momentum" in capsys.readouterr().out
    import importlib.metadata as metadata

    monkeypatch.setattr(metadata, "version", lambda name: (_ for _ in ()).throw(metadata.PackageNotFoundError(name)))
    assert aq_cli._installed_version() == "0.0.0"


def test_init_dry_run_and_force_and_the_pipeline_validate_list_and_json(tmp_path, monkeypatch, capsys):
    import json

    project = tmp_path / "proj"
    assert aq_cli.cmd_init(argparse.Namespace(directory=str(project), name=None, dry_run=True)) == 0
    assert "would write into" in capsys.readouterr().out and not project.exists()
    project.mkdir()
    (project / "README.md").write_text("mine", encoding="utf-8")
    (project / "notes.txt").write_text("keep", encoding="utf-8")
    assert aq_cli.cmd_init(argparse.Namespace(directory=str(project), name="proj", dry_run=False, force=True)) == 0
    out = capsys.readouterr().out
    assert "--force: overwriting README.md" in out and (project / "notes.txt").read_text(encoding="utf-8") == "keep"
    monkeypatch.chdir(project)
    namespace = dict(config=None, run_id=None, runs_dir="runs", json=False)
    assert aq_cli.cmd_pipeline(argparse.Namespace(pipeline_command="validate", **namespace)) == 0 and "pipeline.toml: valid" in capsys.readouterr().out
    assert aq_cli.cmd_pipeline(argparse.Namespace(pipeline_command="validate", **{**namespace, "json": True})) == 0
    assert "pipeline" in json.loads(capsys.readouterr().out)
    assert aq_cli.cmd_pipeline(argparse.Namespace(pipeline_command="validate", **{**namespace, "config": "missing.toml"})) == 1 and "aq pipeline validate" in capsys.readouterr().err
    assert aq_cli.cmd_pipeline(argparse.Namespace(pipeline_command="list", **namespace)) == 0 and "no pipeline runs yet" in capsys.readouterr().out
    for run in ("r1", "r2"):
        (project / "runs" / run).mkdir(parents=True)
        (project / "runs" / run / "state.json").write_text(json.dumps({"done": ["load"]}), encoding="utf-8")
    assert aq_cli.cmd_pipeline(argparse.Namespace(pipeline_command="list", **namespace)) == 0 and "r1: 1/6 stages" in capsys.readouterr().out
    assert aq_cli.cmd_pipeline(argparse.Namespace(pipeline_command="list", **{**namespace, "json": True})) == 0 and len(json.loads(capsys.readouterr().out)) == 2
    assert aq_cli.cmd_pipeline(argparse.Namespace(pipeline_command="status", all=True, **{**namespace, "json": True})) == 0
    assert [row["run"] for row in json.loads(capsys.readouterr().out)] == ["r1", "r2"]
