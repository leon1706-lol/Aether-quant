"""V4.6 - Forex/FX position sizing (development/Problems.md #60, Roadmap
"Assets"), mirrors tests/test_futures_risk.py's exact test shape."""

import json

from risk.forex_risk import build_forex_position_sizing, load_forex_pair_specs


def _eurusd_spec() -> dict:
    return {"pip_size": 0.0001, "lot_size": 100000, "leverage_max": 50, "margin_pct": 0.02}


# ---------------------------------------------------------------------------
# build_forex_position_sizing
# ---------------------------------------------------------------------------


def test_build_forex_position_sizing_full_confidence_targets_leverage_utilization():
    decision = build_forex_position_sizing(
        base_target_weight=0.1,
        confidence=1.0,
        price=1.10,
        pair_spec=_eurusd_spec(),
        portfolio_value=1_000_000,
        target_leverage_utilization=0.20,
        max_leverage_utilization=0.40,
    )
    assert decision.lot_count > 0
    assert decision.margin_utilization <= decision.max_leverage_utilization
    assert abs(decision.margin_utilization - 0.20) < 0.02
    assert decision.sizing_reason == "leverage_utilization_scaled_sizing"


def test_build_forex_position_sizing_scales_down_with_confidence():
    full = build_forex_position_sizing(0.1, 1.0, 1.10, _eurusd_spec(), 1_000_000)
    half = build_forex_position_sizing(0.1, 0.5, 1.10, _eurusd_spec(), 1_000_000)
    assert half.lot_count < full.lot_count


def test_build_forex_position_sizing_never_exceeds_max_leverage_utilization():
    decision = build_forex_position_sizing(
        base_target_weight=0.1,
        confidence=1.0,
        price=1.10,
        pair_spec=_eurusd_spec(),
        portfolio_value=1_000_000,
        target_leverage_utilization=0.40,
        max_leverage_utilization=0.40,
    )
    assert decision.margin_utilization <= 0.40 + 1e-9


def test_build_forex_position_sizing_short_direction_negative_lot_count():
    decision = build_forex_position_sizing(-0.1, 1.0, 1.10, _eurusd_spec(), 1_000_000)
    assert decision.lot_count < 0
    assert decision.target_weight < 0.0


def test_build_forex_position_sizing_lot_count_is_integer():
    decision = build_forex_position_sizing(0.1, 0.73, 1.10, _eurusd_spec(), 1_000_000)
    assert isinstance(decision.lot_count, int)


def test_build_forex_position_sizing_zero_confidence_gives_zero_lots():
    decision = build_forex_position_sizing(0.1, 0.0, 1.10, _eurusd_spec(), 1_000_000)
    assert decision.lot_count == 0
    assert decision.sizing_reason == "no_active_signal_or_missing_pair_spec"


def test_build_forex_position_sizing_zero_base_weight_gives_zero_lots():
    decision = build_forex_position_sizing(0.0, 1.0, 1.10, _eurusd_spec(), 1_000_000)
    assert decision.lot_count == 0


def test_build_forex_position_sizing_missing_pair_spec_gives_zero_lots():
    decision = build_forex_position_sizing(0.1, 1.0, 1.10, None, 1_000_000)
    assert decision.lot_count == 0
    assert decision.sizing_reason == "no_active_signal_or_missing_pair_spec"


def test_build_forex_position_sizing_missing_pair_spec_never_raises():
    decision = build_forex_position_sizing(0.1, 1.0, 1.10, {}, 1_000_000)
    assert decision.lot_count == 0


def test_build_forex_position_sizing_non_positive_portfolio_value_gives_zero():
    decision = build_forex_position_sizing(0.1, 1.0, 1.10, _eurusd_spec(), 0.0)
    assert decision.lot_count == 0


def test_build_forex_position_sizing_non_positive_price_gives_zero():
    decision = build_forex_position_sizing(0.1, 1.0, 0.0, _eurusd_spec(), 1_000_000)
    assert decision.lot_count == 0


# ---------------------------------------------------------------------------
# load_forex_pair_specs
# ---------------------------------------------------------------------------


def test_load_forex_pair_specs_from_real_reference_file():
    specs = load_forex_pair_specs()
    assert "EURUSD" in specs
    assert specs["EURUSD"]["lot_size"] == 100000
    assert "_comment" not in specs  # underscore-prefixed metadata keys are filtered out


def test_load_forex_pair_specs_missing_file_returns_empty(tmp_path):
    specs = load_forex_pair_specs(tmp_path / "does_not_exist.json")
    assert specs == {}


def test_load_forex_pair_specs_unparseable_file_returns_empty(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("not valid json{{{", encoding="utf-8")
    specs = load_forex_pair_specs(path)
    assert specs == {}


def test_load_forex_pair_specs_filters_underscore_keys(tmp_path):
    path = tmp_path / "specs.json"
    path.write_text(json.dumps({"_comment": "ignore me", "EURUSD": {"lot_size": 100000}}), encoding="utf-8")
    specs = load_forex_pair_specs(path)
    assert specs == {"EURUSD": {"lot_size": 100000}}
