"""Suite-wide guards.

The installed models are a set (`retraining/artifact_pins.py`): a test that rewrites one file of it, as one rewrote `ml/scaler_stats.json`
on 2026-11-14 (Problems #382), leaves every file readable and every input mis-scaled. This fails the run that changes any of them. On CI there
is no `ml/`, so the guard has nothing to compare and does nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ML = Path(__file__).resolve().parents[1] / "ml"


@pytest.fixture(scope="session", autouse=True)
def _the_installed_models_are_left_alone():
    from retraining.artifact_pins import compute_artifact_pins

    before = compute_artifact_pins(ML)
    yield
    after = compute_artifact_pins(ML)
    changed = sorted(name for name in {*before, *after} if before.get(name) != after.get(name))
    if changed:
        pytest.fail(f"this run changed the installed model files {changed}: a test wrote into the real ml/ (Problems #382)", pytrace=False)


@pytest.fixture(scope="session")
def _train_runs_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("train_runs")


@pytest.fixture(autouse=True)
def _aq_train_runs_stay_in_a_temporary_folder(_train_runs_dir, monkeypatch):
    """Every `aq train` records a run folder (V6.6.10); under test it goes to a temporary folder, never the real ml/cycle/.
    A test that reads the runs back points `aq_cli.TRAIN_RUNS_DIR` at its own `tmp_path`."""
    aq_cli = sys.modules.get("aq_cli")
    if aq_cli is not None:
        monkeypatch.setattr(aq_cli, "TRAIN_RUNS_DIR", _train_runs_dir)
