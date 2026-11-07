"""examples/aether_quant_quickstart.py runs end to end (V6.4.3)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_quickstart_runs():
    result = subprocess.run([sys.executable, str(ROOT / "examples" / "aether_quant_quickstart.py")], capture_output=True, text=True,
                            timeout=300)
    assert result.returncode == 0, result.stderr
    assert "observation may trade: False" in result.stdout
    assert "truncated: (False, 2)" in result.stdout
    assert "formal targets:" in result.stdout


def test_the_cycle_example_hands_over_and_takes_risk_off():
    result = subprocess.run([sys.executable, str(ROOT / "examples" / "aether_quant_cycle.py")], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr
    assert "0.70   0.30" in result.stdout and "0.00   1.00" in result.stdout
    assert "dead" in result.stdout and "T-bills" in result.stdout
