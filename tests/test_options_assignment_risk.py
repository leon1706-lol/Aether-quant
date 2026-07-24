from datetime import date

from portfolio.options_assignment_risk import (
    assignment_risk_flag,
    assignment_risk_score,
    days_to_next_ex_dividend,
    early_exercise_optimal_for_dividend,
    extrinsic_value,
)


# ---------------------------------------------------------------------------
# extrinsic_value
# ---------------------------------------------------------------------------


def test_extrinsic_value_call_subtracts_intrinsic():
    # spot=105, strike=100 -> intrinsic=5; option trading at 7 -> extrinsic=2.
    assert extrinsic_value(7.0, 105, 100, "call") == 2.0


def test_extrinsic_value_put_subtracts_intrinsic():
    # spot=95, strike=100 -> intrinsic=5; option trading at 6 -> extrinsic=1.
    assert abs(extrinsic_value(6.0, 95, 100, "put") - 1.0) < 1e-9


def test_extrinsic_value_out_of_the_money_intrinsic_is_zero():
    assert extrinsic_value(3.0, 90, 100, "call") == 3.0


def test_extrinsic_value_none_for_missing_price():
    assert extrinsic_value(None, 100, 100, "call") is None


def test_extrinsic_value_none_for_non_positive_price():
    assert extrinsic_value(0.0, 100, 100, "call") is None
    assert extrinsic_value(-1.0, 100, 100, "call") is None


def test_extrinsic_value_right_is_case_insensitive():
    assert extrinsic_value(7.0, 105, 100, "CALL") == extrinsic_value(7.0, 105, 100, "call")


# ---------------------------------------------------------------------------
# early_exercise_optimal_for_dividend - the exact textbook boundary
# ---------------------------------------------------------------------------


def test_early_exercise_optimal_when_extrinsic_below_dividend():
    assert early_exercise_optimal_for_dividend(0.5, 0.6) is True


def test_early_exercise_not_optimal_when_extrinsic_above_dividend():
    assert early_exercise_optimal_for_dividend(0.7, 0.6) is False


def test_early_exercise_not_optimal_at_exact_boundary():
    # Strict "<" - exactly equal is NOT optimal (indifferent, not worth
    # exercising for a knife-edge cushion).
    assert early_exercise_optimal_for_dividend(0.6, 0.6) is False


def test_early_exercise_never_optimal_with_missing_input():
    assert early_exercise_optimal_for_dividend(None, 0.6) is False
    assert early_exercise_optimal_for_dividend(0.5, None) is False
    assert early_exercise_optimal_for_dividend(None, None) is False


# ---------------------------------------------------------------------------
# days_to_next_ex_dividend
# ---------------------------------------------------------------------------


def test_days_to_next_ex_dividend_basic():
    assert days_to_next_ex_dividend(date(2024, 1, 1), date(2024, 1, 6)) == 5


def test_days_to_next_ex_dividend_negative_when_past_due():
    assert days_to_next_ex_dividend(date(2024, 1, 10), date(2024, 1, 6)) == -4


def test_days_to_next_ex_dividend_none_for_missing_input():
    assert days_to_next_ex_dividend(None, date(2024, 1, 6)) is None
    assert days_to_next_ex_dividend(date(2024, 1, 1), None) is None


# ---------------------------------------------------------------------------
# assignment_risk_score - the composite signal
# ---------------------------------------------------------------------------


def test_assignment_risk_score_puts_always_zero():
    # The hard invariant this module's docstring promises: a put is NEVER
    # a dividend-driven early-assignment risk, regardless of how extreme
    # every other input is.
    score = assignment_risk_score(
        moneyness=2.0,
        right="put",
        extrinsic_value=0.01,
        expected_dividend_amount=5.0,
        days_to_next_ex_div=0,
        window_days=5,
    )
    assert score == 0.0


def test_assignment_risk_score_zero_when_not_itm():
    score = assignment_risk_score(
        moneyness=0.9,
        right="call",
        extrinsic_value=0.01,
        expected_dividend_amount=5.0,
        days_to_next_ex_div=0,
        window_days=5,
    )
    assert score == 0.0


def test_assignment_risk_score_zero_when_outside_window():
    score = assignment_risk_score(
        moneyness=1.1,
        right="call",
        extrinsic_value=0.01,
        expected_dividend_amount=5.0,
        days_to_next_ex_div=10,
        window_days=5,
    )
    assert score == 0.0


def test_assignment_risk_score_zero_when_ex_div_already_past():
    score = assignment_risk_score(
        moneyness=1.1,
        right="call",
        extrinsic_value=0.01,
        expected_dividend_amount=5.0,
        days_to_next_ex_div=-1,
        window_days=5,
    )
    assert score == 0.0


def test_assignment_risk_score_zero_when_inputs_missing():
    assert assignment_risk_score(1.1, "call", None, 5.0, 1, 5) == 0.0
    assert assignment_risk_score(1.1, "call", 0.1, None, 1, 5) == 0.0
    assert assignment_risk_score(None, "call", 0.1, 5.0, 1, 5) == 0.0


def test_assignment_risk_score_ceiling_when_exercise_optimal_and_imminent():
    # extrinsic (0.2) < dividend (1.0) -> optimal; days_to_next_ex_div=0 ->
    # time_factor=1.0 -> full ceiling score.
    score = assignment_risk_score(
        moneyness=1.2,
        right="call",
        extrinsic_value=0.2,
        expected_dividend_amount=1.0,
        days_to_next_ex_div=0,
        window_days=5,
    )
    assert score == 1.0


def test_assignment_risk_score_decays_as_cushion_widens():
    small_cushion = assignment_risk_score(1.2, "call", 1.01, 1.0, 0, 5)
    large_cushion = assignment_risk_score(1.2, "call", 5.0, 1.0, 0, 5)
    assert 0.0 < large_cushion < small_cushion < 1.0


def test_assignment_risk_score_decays_with_time_distance():
    near = assignment_risk_score(1.2, "call", 1.5, 1.0, 0, 10)
    far = assignment_risk_score(1.2, "call", 1.5, 1.0, 9, 10)
    assert 0.0 <= far < near


def test_assignment_risk_score_bounded_zero_to_one():
    for extrinsic in (0.0001, 0.5, 1.0, 2.0, 10.0):
        for days in range(0, 6):
            score = assignment_risk_score(1.3, "call", extrinsic, 1.0, days, 5)
            assert 0.0 <= score <= 1.0


def test_assignment_risk_score_zero_window_days_never_raises():
    assert assignment_risk_score(1.2, "call", 0.1, 1.0, 0, 0) == 0.0


# ---------------------------------------------------------------------------
# assignment_risk_flag
# ---------------------------------------------------------------------------


def test_assignment_risk_flag_boundary():
    assert assignment_risk_flag(0.6, 0.6) is True
    assert assignment_risk_flag(0.59, 0.6) is False
    assert assignment_risk_flag(1.0, 0.6) is True
    assert assignment_risk_flag(0.0, 0.6) is False
