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
