"""V2-20 - proves a standard `lean backtest .` run exercises the entire ML
system (baseline model, all 4 experts, MoE gating, topology, regime,
liquidity), not just a subset. This is an integration test, not a unit test:
it shells out to the real Lean CLI against this repo's own data/config, then
inspects the resulting visualization/state.json for evidence every subsystem
actually fired on at least one asset.

Mirrors retraining/lean_backtest.py's optional-dependency convention: if the
`lean` binary isn't on PATH, skip (never fail) - Lean/Docker are not assumed
to be installed in every environment this suite runs in.

Also requires a usable local Lean Data folder (see
_lean_data_folder_is_usable() below), not just the binary - development/
Problems.md#10: once `requirements-dev.txt` started installing the real
`lean` PyPI package, GitHub's CI runner had the binary on PATH for the first
time, so the binary-only skip check stopped skipping there - but CI's fresh
checkout still has none of `data/`'s Lean bootstrap reference files
(data/** is gitignored), so `lean backtest .` failed immediately with
"Unable to locate symbol properties file" instead of skipping as originally
intended.
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
# backtest window (2019-01-01 to 2021-03-31, 20 assets - widened from
# 2018-04-01 for a statistically meaningful validation split on multi-horizon
# targets, see development/Changelog.md) still roughly doubles the per-bar
# cost from the asset count alone, so the timeout is generous on purpose.
# This test is meant for a deliberate, occasional run - not a fast
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


def _lean_data_folder_is_usable(root: Path = REPO_ROOT) -> bool:
    """The `lean` binary being importable is necessary but not sufficient -
    every `lean backtest .` run, regardless of universe/config, first loads
    Lean's own bootstrap reference databases (symbol properties, market
    hours, etc.) from the local Data folder. This repo's data/** is
    gitignored (real market data is too large for a public repo - see
    .gitignore), so a fresh checkout (any CI runner, or a fresh local clone
    before `lean data download`/manual setup) has the binary but not a
    working Data folder. Checking for this file specifically - not just
    `data/` existing - because it's the exact one `lean backtest .` fails
    on first (confirmed via a real CI run, development/Problems.md#10).
    `root` is overridable (default REPO_ROOT) purely for testability."""
    return (root / "data" / "symbol-properties" / "symbol-properties-database.csv").exists()


_LEAN_BINARY = _find_quantconnect_lean_binary()
_LEAN_DATA_READY = _lean_data_folder_is_usable()

# lean_backtest (registered in pyproject.toml) is what actually gates the
# real-backtest tests below out of a default `aq test` run - a real
# `lean backtest .` here takes over an hour wall-clock, and _skip_no_lean
# below only checks binary/data-folder *availability*, not whether you
# actually want to pay that cost right now. `aq test --lean`/`--full` drops
# the marker exclusion; the skipif stays as a secondary guard for machines
# with no working local Lean setup at all.
#
# Deliberately NOT a module-level `pytestmark` list (unlike this file's
# previous version): that would also skip _lean_data_folder_is_usable()'s
# own regression test below whenever the thing it's testing is exactly the
# "no Lean data folder" case (e.g. in CI) - the one environment where
# proving this guard works correctly matters most. Applied per-function to
# only the tests that actually need a real backtest instead.
_skip_no_lean = pytest.mark.skipif(
    _LEAN_BINARY is None or not _LEAN_DATA_READY,
    reason="QuantConnect Lean CLI or a usable local Lean Data folder not available - skipping full-system backtest integration test",
)


def test_lean_data_folder_check_true_when_symbol_properties_file_present(tmp_path):
    (tmp_path / "data" / "symbol-properties").mkdir(parents=True)
    (tmp_path / "data" / "symbol-properties" / "symbol-properties-database.csv").write_text("x")
    assert _lean_data_folder_is_usable(tmp_path) is True


def test_lean_data_folder_check_false_when_symbol_properties_file_missing(tmp_path):
    assert _lean_data_folder_is_usable(tmp_path) is False


def test_lean_data_folder_check_false_on_fresh_checkout_shape(tmp_path):
    """Mirrors a real fresh clone/CI checkout: data/ exists (its directory
    structure is git-tracked via .keep files) but data/** contents are
    gitignored - see development/Problems.md#10."""
    (tmp_path / "data").mkdir()
    assert _lean_data_folder_is_usable(tmp_path) is False


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


@_skip_no_lean
@pytest.mark.lean_backtest
def test_backtest_produced_at_least_one_fully_evaluated_signal(state_after_backtest):
    assert len(_signals_with_full_payload(state_after_backtest)) > 0


@_skip_no_lean
@pytest.mark.lean_backtest
def test_baseline_model_ran(state_after_backtest):
    for signal in _signals_with_full_payload(state_after_backtest):
        assert signal.get("baseline_probability_up") is not None
        return
    pytest.fail("no evaluated signal found")


@_skip_no_lean
@pytest.mark.lean_backtest
def test_all_four_experts_ran(state_after_backtest):
    for signal in _signals_with_full_payload(state_after_backtest):
        expert_probabilities = signal.get("expert_probabilities") or {}
        assert set(EXPERT_NAMES).issubset(expert_probabilities.keys())
        return
    pytest.fail("no evaluated signal found")


@_skip_no_lean
@pytest.mark.lean_backtest
def test_moe_gating_ran(state_after_backtest):
    for signal in _signals_with_full_payload(state_after_backtest):
        gating = signal.get("moe_gating") or {}
        assert len(gating.get("weights") or []) == len(EXPERT_NAMES)
        assert gating.get("final_probability_up") is not None
        return
    pytest.fail("no evaluated signal found")


@_skip_no_lean
@pytest.mark.lean_backtest
def test_regime_detection_ran(state_after_backtest):
    for signal in _signals_with_full_payload(state_after_backtest):
        regime = signal.get("regime") or {}
        assert regime.get("trend_regime")
        return
    pytest.fail("no evaluated signal found")


@_skip_no_lean
@pytest.mark.lean_backtest
def test_liquidity_engine_ran(state_after_backtest):
    for signal in _signals_with_full_payload(state_after_backtest):
        liquidity = signal.get("liquidity") or {}
        assert liquidity.get("liquidity_risk")
        return
    pytest.fail("no evaluated signal found")


@_skip_no_lean
@pytest.mark.lean_backtest
def test_topology_ran(state_after_backtest):
    topology = state_after_backtest.get("topology") or {}
    assert len(topology.get("nodes") or []) > 0


@_skip_no_lean
@pytest.mark.lean_backtest
def test_model_input_dimensionality_is_59(state_after_backtest):
    """Proves the full regime/liquidity/topology/peer-return/technical-
    indicator-as-input feature pipeline (train.py::build_feature_dataset() /
    main.py::_build_model_input()) was actually exercised in a real
    backtest, not just unit-tested. Grew from the original 48 (regime +
    liquidity + topology) to 59: +4 peer-return features (Phase 5) + 6
    technical indicators + 1 cross-sectional momentum rank (Phase 6) - see
    development/Changelog.md."""
    model_config = state_after_backtest.get("config", {}).get("model", {})
    assert model_config.get("input_count") == 59


@_skip_no_lean
@pytest.mark.lean_backtest
def test_baseline_multitask_model_ran(state_after_backtest):
    """Proves train.py::AetherNetMultiTask (train_multitask.py,
    ml/multitask_model.json) actually loaded and produced magnitude/
    volatility predictions during a real backtest."""
    model_config = state_after_backtest.get("config", {}).get("model", {})
    assert model_config.get("multitask", {}).get("model_loaded") is True
    for signal in _signals_with_full_payload(state_after_backtest):
        assert signal.get("predicted_return_magnitude") is not None
        assert signal.get("predicted_volatility") is not None
        return
    pytest.fail("no evaluated signal found")


@_skip_no_lean
@pytest.mark.lean_backtest
def test_expert_multitask_heads_ran(state_after_backtest):
    """Proves per-expert multitask heads (ml/expert_models/<name>/
    multitask_model.json) actually fed moe/gating.py's _weighted_blend()
    into GatingDecision.final_magnitude during a real backtest."""
    for signal in _signals_with_full_payload(state_after_backtest):
        gating = signal.get("moe_gating") or {}
        assert gating.get("final_magnitude") is not None
        return
    pytest.fail("no evaluated signal found")


@_skip_no_lean
@pytest.mark.lean_backtest
def test_sequence_model_ran(state_after_backtest):
    """Proves the Phase 2 causal-TCN sequence encoder
    (train.py::AetherNetSequenceMultiTask, ml/sequence_model.json) actually
    loaded and ran during a real backtest. Informational-only - this does
    not assert it fed any trading decision, only that it executed."""
    model_config = state_after_backtest.get("config", {}).get("model", {})
    assert model_config.get("sequence", {}).get("model_loaded") is True
    for signal in _signals_with_full_payload(state_after_backtest):
        sequence_model = signal.get("sequence_model") or {}
        assert set(sequence_model.keys()) >= {"direction", "magnitude", "volatility"}
        return
    pytest.fail("no evaluated signal found")
