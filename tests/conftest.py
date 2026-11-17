"""Suite-wide guards.

The installed models are a set (`retraining/artifact_pins.py`): a test that rewrites one file of it, as one rewrote `ml/scaler_stats.json`
on 2026-11-14 (Problems #382), leaves every file readable and every input mis-scaled. This fails the run that changes any of them. On CI there
is no `ml/`, so the guard has nothing to compare and does nothing.
"""

from __future__ import annotations

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
