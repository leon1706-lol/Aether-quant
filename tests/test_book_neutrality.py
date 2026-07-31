import random

from portfolio.book_neutrality import apply_book_neutrality


def _neutralize(weights, sectors=None, **overrides):
    kwargs = dict(
        dollar_neutral=True,
        sector_neutral=True,
        gross_exposure_cap=1.0,
        max_weight_per_name=0.12,
        sector_max_net_weight=0.05,
    )
    kwargs.update(overrides)
    return apply_book_neutrality(weights, sector_by_symbol=sectors or {}, **kwargs)


def test_empty_book_returns_empty_and_never_raises():
    weights, diagnostics = _neutralize({})
    assert weights == {}
    assert diagnostics["steps_applied"] == ["empty_book_no_op"]


def test_dollar_neutral_balanced_legs_sum_to_zero():
    weights, diagnostics = _neutralize(
        {"L1": 0.12, "L2": 0.12, "S1": -0.12, "S2": -0.12},
        sectors={"L1": "Tech", "L2": "Fin", "S1": "Tech", "S2": "Fin"},
    )
    assert abs(sum(weights.values())) < 1e-9
    assert abs(diagnostics["net_after"]) < 1e-9


def test_dollar_neutral_scales_the_larger_leg_down_only():
    weights, _ = _neutralize(
        {"L1": 0.30, "S1": -0.10},
        sectors={"L1": "Tech", "S1": "Fin"},
        sector_neutral=False,
    )
    # Long leg (0.30) is larger than short leg (0.10) - it must be scaled
    # DOWN to match, never the short leg scaled up beyond its own magnitude.
    assert abs(weights["L1"]) == abs(weights["S1"])
    assert abs(weights["L1"]) <= 0.30
    assert abs(weights["S1"]) == 0.10


def test_sector_neutral_makes_each_bucket_net_zero():
    weights, diagnostics = _neutralize(
        {"A": 0.10, "B": 0.10, "C": -0.05},
        sectors={"A": "Tech", "B": "Tech", "C": "Fin"},
        dollar_neutral=False,
        sector_max_net_weight=1.0,
    )
    tech_net = weights["A"] + weights["B"]
    assert abs(tech_net) < 1e-9
    assert abs(diagnostics["per_sector_net"]["Tech"]) < 1e-9


def test_sector_neutral_single_member_bucket_left_untouched():
    # A lone name in its own sector has no peer to demean against -
    # demeaning it would just zero it out, a much bigger behavior change
    # than "neutralize this sector" implies.
    weights, _ = _neutralize(
        {"A": 0.10, "B": -0.10},
        sectors={"A": "Tech", "B": "Fin"},
        dollar_neutral=False,
        sector_max_net_weight=1.0,
    )
    assert weights["A"] == 0.10
    assert weights["B"] == -0.10


def test_sector_bucket_over_max_net_weight_is_shrunk_not_amplified():
    # Two Tech names both long (no offsetting short in the bucket) leaves a
    # nonzero net after demeaning - shrink must bring it within the cap.
    weights, diagnostics = _neutralize(
        {"A": 0.10, "B": 0.08},
        sectors={"A": "Tech", "B": "Tech"},
        dollar_neutral=False,
        sector_max_net_weight=0.02,
    )
    tech_net = weights["A"] + weights["B"]
    assert abs(tech_net) <= 0.02 + 1e-9
    assert abs(weights["A"]) <= 0.10
    assert abs(weights["B"]) <= 0.08


def test_per_name_cap_binds_before_anything_else():
    weights, _ = _neutralize(
        {"A": 0.50, "B": -0.50},
        sectors={"A": "Tech", "B": "Fin"},
        max_weight_per_name=0.12,
    )
    assert abs(weights["A"]) <= 0.12
    assert abs(weights["B"]) <= 0.12


def test_gross_exposure_cap_scales_everything_down():
    weights, diagnostics = _neutralize(
        {"A": 0.5, "B": 0.5, "C": -0.5, "D": -0.5},
        sectors={"A": "X", "B": "Y", "C": "X", "D": "Y"},
        sector_neutral=False,
        max_weight_per_name=0.6,
        gross_exposure_cap=1.0,
    )
    gross = sum(abs(w) for w in weights.values())
    assert gross <= 1.0 + 1e-9
    assert "gross_cap" in diagnostics["steps_applied"]


def test_all_long_book_with_dollar_neutral_requested_degrades_gracefully_never_raises():
    # No shorts exist - dollar-neutrality has nothing to balance against.
    # Must never divide by zero or raise; the step is simply skipped.
    weights, diagnostics = _neutralize(
        {"A": 0.10, "B": 0.08},
        sectors={"A": "Tech", "B": "Fin"},
    )
    assert weights["A"] == 0.10
    assert weights["B"] == 0.08
    assert "dollar_neutral_skipped_one_sided_book" in diagnostics["steps_applied"]


def test_result_is_independent_of_input_dict_iteration_order():
    raw = {"L1": 0.12, "L2": 0.12, "S1": -0.12, "S2": -0.12}
    sectors = {"L1": "Tech", "L2": "Fin", "S1": "Tech", "S2": "Fin"}

    baseline_weights, _ = _neutralize(dict(raw), sectors=sectors)

    items = list(raw.items())
    random.Random(7).shuffle(items)
    shuffled_weights, _ = _neutralize(dict(items), sectors=sectors)

    assert {k: round(v, 10) for k, v in baseline_weights.items()} == {
        k: round(v, 10) for k, v in shuffled_weights.items()
    }


def test_diagnostics_report_pre_and_post_gross_and_net():
    weights, diagnostics = _neutralize(
        {"L1": 0.12, "S1": -0.12},
        sectors={"L1": "Tech", "S1": "Fin"},
    )
    assert diagnostics["pre_gross"] == 0.24
    assert diagnostics["post_gross"] > 0.0
    assert "net_before" in diagnostics
    assert "net_after" in diagnostics
