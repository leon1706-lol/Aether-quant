"""`aq lab new`: a model folder from a template (`aether_quant/_templates/lab/<template>/`): `model.py` with its
`build(n_features, heads, **hparams)`, `config.toml`, and a test that checks the network's shapes and gradients.
"""

from __future__ import annotations

import re
from pathlib import Path

from lab.spec import TEMPLATES, TORCH_TEMPLATES

TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "aether_quant" / "_templates" / "lab"

TEST_TEXT = '''"""{name}: the network builds, gives one finite score per row for its head, and its input layer gets a gradient from that head."""

import importlib.util
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
HERE = Path(__file__).resolve().parent


def _module():
    spec = importlib.util.spec_from_file_location("{name}_model", HERE / "model.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shapes_and_gradients():
    model = _module().build(6, ["rank_20d"])
    rows = torch.randn({batch_shape})
    output = model(rows)
    scores = output["rank_20d"] if isinstance(output, dict) else output[0] if isinstance(output, tuple) else output
    assert scores.shape[0] == 8 and torch.isfinite(scores).all()
    scores.sum().backward()
    first = next(parameter for parameter in model.parameters() if parameter.requires_grad)
    assert first.grad is not None and torch.isfinite(first.grad).all() and first.grad.abs().sum() > 0, "the input layer learns from the head"
'''


def valid_name(name: str) -> bool:
    """Whether a model name is safe as a folder and a module name: a letter, then up to 40 letters, digits or `_`."""
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,40}", name))


def new_model(lab_dir: Path, name: str, template: str, *, force: bool = False) -> list[str]:
    """Write models/<name>/ from `template`; returns the files written. Refuses an existing folder unless `force`."""
    if template not in TEMPLATES:
        raise ValueError(f"template must be one of {', '.join(TEMPLATES)}")
    if not valid_name(name):
        raise ValueError("a model name starts with a letter and holds letters, digits and _ only")
    folder = lab_dir / "models" / name
    if folder.exists() and any(folder.iterdir()) and not force:
        raise FileExistsError(f"{folder} exists (pass --force to overwrite it)")
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for source, target in (("model.py.tmpl", "model.py"), ("config.toml.tmpl", "config.toml")):
        text = (TEMPLATE_ROOT / template / source).read_text(encoding="utf-8").replace("{name}", name)
        (folder / target).write_text(text, encoding="utf-8", newline="\n")
        written.append(f"models/{name}/{target}")
    if template in TORCH_TEMPLATES:
        batch = "8, 20, 6" if template == "tcn" else "8, 6"
        (folder / f"test_{name}_model.py").write_text(TEST_TEXT.replace("{name}", name).replace("{batch_shape}", batch), encoding="utf-8", newline="\n")
        written.append(f"models/{name}/test_{name}_model.py")
    return written
