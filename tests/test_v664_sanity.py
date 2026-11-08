"""scripts/v664_sanity.py: the verdict's thresholds, on stored figures (V6.6.4). The scoring itself needs the crypto root and runs on the host that scores the round."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import v664_sanity as sanity  # noqa: E402


def _report(oracle, reverse, random):
    return {"oracle": {"sharpe": oracle}, "reversed_oracle": {"sharpe": reverse}, "random": {"sharpe": random}}


def test_a_path_that_sees_an_edge_passes():
    assert sanity.verdict(_report(12.0, -9.0, -0.4))["path_can_see_an_edge"] is True


def test_the_first_runs_figures_pass_at_the_revised_floor():
    assert sanity.verdict(_report(2.57, -2.23, 0.23))["path_can_see_an_edge"] is True
    assert sanity.ORACLE_FLOOR == 2.0


def test_a_dead_path_fails_each_condition():
    assert sanity.verdict(_report(0.5, -9.0, 0.0))["checks"]["oracle_large"] is False
    assert sanity.verdict(_report(12.0, 0.3, 0.0))["checks"]["reversal_negative"] is False
    assert sanity.verdict(_report(12.0, -9.0, 2.5))["checks"]["random_near_zero"] is False


def test_a_missing_figure_fails_closed():
    assert sanity.verdict(_report(None, -9.0, 0.0))["path_can_see_an_edge"] is False
    assert sanity.verdict(_report(12.0, None, 0.0))["path_can_see_an_edge"] is False
    assert sanity.verdict(_report(12.0, -9.0, None))["path_can_see_an_edge"] is False
