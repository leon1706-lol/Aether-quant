import json
from datetime import date

from risk.futures_risk import (
    build_futures_position_sizing,
    load_futures_contract_specs,
    rollover_due,
)


def _es_spec() -> dict:
    return {"multiplier": 50, "tick_size": 0.25, "initial_margin_usd": 13200, "exchange": "CME"}


# ---------------------------------------------------------------------------
# build_futures_position_sizing
# ---------------------------------------------------------------------------


def test_build_futures_position_sizing_full_confidence_targets_margin_utilization():
    decision = build_futures_position_sizing(
        base_target_weight=0.1,
        confidence=1.0,
        price=5000.0,
        contract_spec=_es_spec(),
        portfolio_value=1_000_000,
        target_margin_utilization=0.20,
        max_margin_utilization=0.40,
    )
    assert decision.contract_count > 0
    assert decision.margin_utilization <= decision.max_margin_utilization
    # At full confidence, margin utilization should land close to the target.
    assert abs(decision.margin_utilization - 0.20) < 0.02
    assert decision.sizing_reason == "margin_utilization_scaled_sizing"


def test_build_futures_position_sizing_scales_down_with_confidence():
    full = build_futures_position_sizing(0.1, 1.0, 5000.0, _es_spec(), 1_000_000)
    half = build_futures_position_sizing(0.1, 0.5, 5000.0, _es_spec(), 1_000_000)
    assert half.contract_count < full.contract_count


def test_build_futures_position_sizing_never_exceeds_max_margin_utilization():
    decision = build_futures_position_sizing(
        base_target_weight=0.1,
        confidence=1.0,
        price=5000.0,
        contract_spec=_es_spec(),
        portfolio_value=1_000_000,
        target_margin_utilization=0.40,
        max_margin_utilization=0.40,
    )
    assert decision.margin_utilization <= 0.40 + 1e-9


def test_build_futures_position_sizing_short_direction_negative_contract_count():
    decision = build_futures_position_sizing(-0.1, 1.0, 5000.0, _es_spec(), 1_000_000)
    assert decision.contract_count < 0
    assert decision.target_weight < 0.0


def test_build_futures_position_sizing_contract_count_is_integer():
    decision = build_futures_position_sizing(0.1, 0.73, 5000.0, _es_spec(), 1_000_000)
    assert isinstance(decision.contract_count, int)


def test_build_futures_position_sizing_zero_confidence_gives_zero_contracts():
    decision = build_futures_position_sizing(0.1, 0.0, 5000.0, _es_spec(), 1_000_000)
    assert decision.contract_count == 0
    assert decision.sizing_reason == "no_active_signal_or_missing_contract_spec"


def test_build_futures_position_sizing_zero_base_weight_gives_zero_contracts():
    decision = build_futures_position_sizing(0.0, 1.0, 5000.0, _es_spec(), 1_000_000)
    assert decision.contract_count == 0


def test_build_futures_position_sizing_missing_contract_spec_gives_zero_contracts():
    decision = build_futures_position_sizing(0.1, 1.0, 5000.0, None, 1_000_000)
    assert decision.contract_count == 0
    assert decision.sizing_reason == "no_active_signal_or_missing_contract_spec"


def test_build_futures_position_sizing_missing_contract_spec_never_raises():
    decision = build_futures_position_sizing(0.1, 1.0, 5000.0, {}, 1_000_000)
    assert decision.contract_count == 0


def test_build_futures_position_sizing_non_positive_portfolio_value_gives_zero():
    decision = build_futures_position_sizing(0.1, 1.0, 5000.0, _es_spec(), 0.0)
    assert decision.contract_count == 0


def test_build_futures_position_sizing_non_positive_price_gives_zero():
    decision = build_futures_position_sizing(0.1, 1.0, 0.0, _es_spec(), 1_000_000)
    assert decision.contract_count == 0


# ---------------------------------------------------------------------------
# load_futures_contract_specs
# ---------------------------------------------------------------------------


def test_load_futures_contract_specs_from_real_reference_file():
    specs = load_futures_contract_specs()
    assert "ES" in specs
    assert specs["ES"]["multiplier"] == 50
    assert "_comment" not in specs  # underscore-prefixed metadata keys are filtered out


def test_load_futures_contract_specs_missing_file_returns_empty(tmp_path):
    specs = load_futures_contract_specs(tmp_path / "does_not_exist.json")
    assert specs == {}


def test_load_futures_contract_specs_unparseable_file_returns_empty(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("not valid json{{{", encoding="utf-8")
    specs = load_futures_contract_specs(path)
    assert specs == {}


def test_load_futures_contract_specs_filters_underscore_keys(tmp_path):
    path = tmp_path / "specs.json"
    path.write_text(json.dumps({"_comment": "ignore me", "ES": {"multiplier": 50}}), encoding="utf-8")
    specs = load_futures_contract_specs(path)
    assert specs == {"ES": {"multiplier": 50}}


# ---------------------------------------------------------------------------
# rollover_due - pure diagnostic date comparison, never a trade trigger
# ---------------------------------------------------------------------------


def test_rollover_due_true_within_window():
    assert rollover_due(date(2026, 7, 10), date(2026, 7, 12), rollover_days_before_expiry=5) is True


def test_rollover_due_false_outside_window():
    assert rollover_due(date(2026, 7, 1), date(2026, 7, 12), rollover_days_before_expiry=5) is False


def test_rollover_due_false_when_expiry_unknown():
    assert rollover_due(date(2026, 7, 10), None) is False


def test_rollover_due_true_on_expiry_day_itself():
    assert rollover_due(date(2026, 7, 12), date(2026, 7, 12), rollover_days_before_expiry=5) is True
