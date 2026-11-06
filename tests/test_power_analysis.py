"""evaluation/power_analysis.py."""

from __future__ import annotations

import math

import pytest

from evaluation.power_analysis import (
    excluded_alpha_sharpe,
    fundamental_law_ir,
    minimum_detectable_alpha_sharpe,
    power_of_t_test,
    power_table,
)


def test_minimum_detectable_alpha_sharpe():
    assert minimum_detectable_alpha_sharpe(9.0) == pytest.approx(1.0)
    assert minimum_detectable_alpha_sharpe(16.0, t_bar=2.0) == pytest.approx(0.5)
    assert minimum_detectable_alpha_sharpe(0.0) == math.inf


def test_power_is_a_half_at_the_minimum_detectable_size_and_grows_with_years():
    assert power_of_t_test(1.0, 9.0) == pytest.approx(0.5)
    assert power_of_t_test(0.5, 30.0) > power_of_t_test(0.5, 5.0)
    assert power_of_t_test(0.5, 0.0) == 0.0


def test_excluded_alpha_sharpe_bounds_the_truth():
    bound = excluded_alpha_sharpe(0.0, 16.0)
    assert bound == pytest.approx(1.644854 / 4.0, rel=1e-5)
    # a true alpha at the bound would have shown a t above what was seen 95% of the time
    assert power_of_t_test(bound, 16.0, t_bar=0.0) == pytest.approx(0.95, abs=1e-6)


def test_fundamental_law_ten_times_the_names_is_about_three_times_the_ir():
    assert fundamental_law_ir(0.02, 550, 12) / fundamental_law_ir(0.02, 55, 12) == pytest.approx(math.sqrt(10))
    assert fundamental_law_ir(0.02, 55, 12) == pytest.approx(0.5138, abs=1e-3)


def test_power_table_is_plain_json_data():
    import json

    table = power_table()
    assert json.loads(json.dumps(table))["t_bar"] == 3.0
    assert set(table["power"]) == {"3.3", "8.0", "15.8", "22.8"}
