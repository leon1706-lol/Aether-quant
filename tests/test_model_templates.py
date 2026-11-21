"""lab/model_templates.py: aq lab new writes a model folder from a template, and the torch templates' own tests pass."""

from __future__ import annotations

import subprocess
import sys

import pytest

from lab import model_templates as mt


@pytest.mark.parametrize("template", ["mlp", "multitask", "tcn", "linear"])
def test_every_template_writes_its_folder(tmp_path, template):
    written = mt.new_model(tmp_path, "m1", template)
    folder = tmp_path / "models" / "m1"
    assert (folder / "model.py").exists() and (folder / "config.toml").exists()
    assert f'template = "{template}"' in (folder / "config.toml").read_text(encoding="utf-8")
    assert "{name}" not in (folder / "model.py").read_text(encoding="utf-8")
    assert ("models/m1/test_m1_model.py" in written) == (template != "linear")


def test_the_generated_shape_tests_pass(tmp_path):
    pytest.importorskip("torch")
    for name, template in (("seq", "tcn"), ("mt", "multitask")):
        mt.new_model(tmp_path, name, template)
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path / "models")], capture_output=True, text=True, check=False,
                            cwd=str(tmp_path), env={**__import__("os").environ, "PYTHONPATH": str(mt.TEMPLATE_ROOT.parents[2])})
    assert result.returncode == 0, result.stdout + result.stderr


def test_names_templates_and_existing_folders_are_checked(tmp_path):
    assert mt.valid_name("m_1") and not mt.valid_name("1m") and not mt.valid_name("a-b")
    with pytest.raises(ValueError, match="template"):
        mt.new_model(tmp_path, "m", "rnn")
    with pytest.raises(ValueError, match="starts with a letter"):
        mt.new_model(tmp_path, "9", "mlp")
    mt.new_model(tmp_path, "m", "linear")
    with pytest.raises(FileExistsError, match="--force"):
        mt.new_model(tmp_path, "m", "mlp")
    assert "models/m/test_m_model.py" in mt.new_model(tmp_path, "m", "mlp", force=True)
