"""examples/aether_quant_quickstart.py runs end to end (V6.4.3)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_quickstart_runs():
    result = subprocess.run([sys.executable, str(ROOT / "examples" / "aether_quant_quickstart.py")], capture_output=True, text=True,
                            timeout=300, check=False)
    assert result.returncode == 0, result.stderr
    assert "observation may trade: False" in result.stdout
    assert "truncated: (False, 2)" in result.stdout
    assert "formal targets:" in result.stdout


def test_the_cycle_example_hands_over_and_takes_risk_off():
    result = subprocess.run([sys.executable, str(ROOT / "examples" / "aether_quant_cycle.py")], capture_output=True, text=True, timeout=300, check=False)
    assert result.returncode == 0, result.stderr
    assert "0.70   0.30" in result.stdout and "0.00   1.00" in result.stdout
    assert "dead" in result.stdout and "T-bills" in result.stdout


def test_the_models_example_loads_a_folder_and_scores_the_sample():
    """V6.6.10: the catalog, then any exported model folder loaded and scored with the numpy pass, offline."""
    result = subprocess.run([sys.executable, str(ROOT / "examples" / "aether_quant_models.py")], capture_output=True, text=True, timeout=300, check=False)
    assert result.returncode == 0, result.stderr
    assert "example-crypto-mlp (multitask)" in result.stdout and "loaded momentum-minus-volatility (multitask)" in result.stdout
    assert "11 coins" in result.stdout and "ranking on " in result.stdout


def test_every_example_finds_the_package_without_an_install():
    """CI runs the suite without `pip install -e .`, and pytest's pythonpath does not reach a child process: an example that
    imports aether_quant must put the repo root on sys.path itself (V6.6.1 and V6.6.2 failed CI on exactly this)."""
    for path in sorted((ROOT / "examples").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))" in text, path.name
        assert text.index("sys.path.insert") < text.index("from aether_quant"), path.name


def test_the_lab_example_trains_judges_compares_and_exports_offline():
    """V6.7.1: the model lab's whole path on the bundled sample, with the linear template (no torch)."""
    result = subprocess.run([sys.executable, str(ROOT / "examples" / "aether_quant_lab.py")], capture_output=True, text=True, timeout=600, check=False)
    assert result.returncode == 0, result.stderr
    assert "out-of-sample IC" in result.stdout and ", N 2" in result.stdout and "DSR at N=2" in result.stdout
    assert "momentum_20" in result.stdout and "linear_model.json" in result.stdout and "manifest.json" in result.stdout
