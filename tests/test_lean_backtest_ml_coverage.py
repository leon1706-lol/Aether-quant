"""V2-20 - proves a standard `lean backtest .` run exercises the entire ML
system (baseline model, all 4 experts, MoE gating, topology, regime,
liquidity), not just a subset. This is an integration test, not a unit test:
it shells out to the real Lean CLI against this repo's own data/config, then
inspects the resulting visualization/state.json for evidence every subsystem
actually fired on at least one asset.

Mirrors retraining/lean_backtest.py's optional-dependency convention: if the
`lean` binary isn't on PATH, skip (never fail) - Lean/Docker are not assumed
to be installed in every environment this suite runs in.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from moe import EXPERT_NAMES

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = REPO_ROOT / "visualization" / "state.json"
# The old committed backtest window (2014-12-01 to 2018-08-13, 10 assets) was
# observed taking over an hour wall-clock on this project's Docker Lean
# runtime - main.py's per-bar model/expert inference (_run_exported_model) is
# plain Python with no vectorization, run once per asset per bar. The current
# backtest window (2018-04-01 to 2021-03-31, 20 assets) roughly doubles the
# per-bar cost from the asset count alone, so the timeout is generous on
# purpose. This test is meant for a deliberate, occasional run - not a fast
# per-commit check.
LEAN_BACKTEST_TIMEOUT_SECONDS = 14400


def _find_quantconnect_lean_binary() -> str | None:
    """`lean` on PATH is ambiguous on machines with elan installed: Lean 4
    (the theorem prover) ships its own `lean` binary that answers to the same
    name as QuantConnect's Lean CLI (`pip install lean`). Disambiguate by
    checking `--version` output - Lean 4 prints "Lean (version 4...."; the
    QuantConnect CLI prints a bare "lean <version>". Prefer the current
    venv's own Scripts/bin dir (where `pip install lean` actually put it in
    this repo) before falling back to whatever `lean` resolves to on PATH.
    """
    bin_dir_name = "Scripts" if sys.platform == "win32" else "bin"
    binary_name = "lean.exe" if sys.platform == "win32" else "lean"
    candidates = [
        str(REPO_ROOT / ".venv" / bin_dir_name / binary_name),
        str(Path(sys.prefix) / bin_dir_name / binary_name),
    ]
    on_path = shutil.which("lean")
    if on_path:
        candidates.append(on_path)

    for candidate in candidates:
        if candidate != on_path and not Path(candidate).exists():
            continue
        try:
            result = subprocess.run([candidate, "--version"], capture_output=True, text=True, timeout=30)
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
        version_output = (result.stdout or "") + (result.stderr or "")
        if "Lean (version" not in version_output:
            return candidate
    return None


_LEAN_BINARY = _find_quantconnect_lean_binary()

pytestmark = pytest.mark.skipif(
    _LEAN_BINARY is None,
    reason="QuantConnect Lean CLI not available - skipping full-system backtest integration test",
)


@pytest.fixture(scope="module")
def state_after_backtest() -> dict:
    result = subprocess.run(
        [_LEAN_BINARY, "backtest", "."],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=LEAN_BACKTEST_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        pytest.fail(f"lean backtest . failed (exit {result.returncode}):\n{result.stderr or result.stdout}")

    if not STATE_PATH.exists():
        pytest.fail(f"{STATE_PATH} was not written by the backtest run")

    with STATE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _signals_with_full_payload(state: dict) -> list[dict]:
    signals = state.get("signals", {})
    return [signal for signal in signals.values() if signal.get("feature_ready")]


def test_backtest_produced_at_least_one_fully_evaluated_signal(state_after_backtest):
    assert len(_signals_with_full_payload(state_after_backtest)) > 0


def test_baseline_model_ran(state_after_backtest):
    for signal in _signals_with_full_payload(state_after_backtest):
        assert signal.get("baseline_probability_up") is not None
        return
    pytest.fail("no evaluated signal found")


def test_all_four_experts_ran(state_after_backtest):
    for signal in _signals_with_full_payload(state_after_backtest):
        expert_probabilities = signal.get("expert_probabilities") or {}
        assert set(EXPERT_NAMES).issubset(expert_probabilities.keys())
        return
    pytest.fail("no evaluated signal found")


def test_moe_gating_ran(state_after_backtest):
    for signal in _signals_with_full_payload(state_after_backtest):
        gating = signal.get("moe_gating") or {}
        assert len(gating.get("weights") or []) == len(EXPERT_NAMES)
        assert gating.get("final_probability_up") is not None
        return
    pytest.fail("no evaluated signal found")


def test_regime_detection_ran(state_after_backtest):
    for signal in _signals_with_full_payload(state_after_backtest):
        regime = signal.get("regime") or {}
        assert regime.get("trend_regime")
        return
    pytest.fail("no evaluated signal found")


def test_liquidity_engine_ran(state_after_backtest):
    for signal in _signals_with_full_payload(state_after_backtest):
        liquidity = signal.get("liquidity") or {}
        assert liquidity.get("liquidity_risk")
        return
    pytest.fail("no evaluated signal found")


def test_topology_ran(state_after_backtest):
    topology = state_after_backtest.get("topology") or {}
    assert len(topology.get("nodes") or []) > 0
