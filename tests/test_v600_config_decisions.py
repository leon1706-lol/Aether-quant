"""V6.0.0: the shipped config carries exactly the values the pre-registered rules picked (Problems.md #176-#183).

A change to any of these is an owner decision (AGENTS.md rule 9) and must come with the research that justifies it."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
V2 = CONFIG["phase_v2"]


def test_r_book_slower_book_and_a_preset_that_matches_it():
    assert V2["portfolio_book"]["rebalance_every_bars"] == 20 and V2["exits"]["max_holding_bars"] == 40
    preset = V2["presets"]["aggressive"]
    assert preset["phase_v2.portfolio_book.rebalance_every_bars"] == 20
    assert preset["phase_v2.portfolio_book.min_rank_confidence_spread"] == V2["portfolio_book"]["min_rank_confidence_spread"] == 0.1
    assert preset["phase6.risk.min_confidence_to_trade"] == CONFIG["phase6"]["risk"]["min_confidence_to_trade"]
    # the gates were frozen by R-CAL branch B: no R-GATE flip in V6
    assert V2["rolling_ic_gate"]["rolling_window_days"] == 120 and V2["rolling_ic_gate"]["min_rolling_mean_ic"] == 0.0


def test_r_crypto_limit_exits_route_aware_fee_and_smaller_graduates():
    limits = V2["limit_orders"]
    # offset 0.0 (a limit at the last close) was priced as maker by the research but filled as taker in Lean (BT1: 111 limit
    # fills at 70.9 bps): the crypto offset is back at the global 1.0, where BT2's limit fills paid 60 bps
    assert limits["exit_asset_classes"] == ["crypto"] and limits["offset_multiplier_by_class"] == {}
    assert limits["unfilled_timeout_bars_by_class"] == {"crypto": 5}
    assert limits["offset_multiplier"] == 1.0 and limits["unfilled_timeout_bars"] == 3  # every other class keeps the globals
    route = V2["costs"]["fee_by_type"]["crypto"]["route_aware"]
    assert route["enabled"] and route["entry_limit"] and route["exit_limit"] and (route["maker_bps"], route["taker_bps"]) == (60.0, 80.0)
    caps = V2["class_weight_caps"]["crypto"]
    assert (caps["per_name_cap"], caps["class_gross_cap"]) == (0.005, 0.025) and caps["exempt"] == ["BTCUSD", "LTCUSD"]
    from execution.cost_model import commission_terms_for_security_type

    per_side = commission_terms_for_security_type(V2["costs"], "crypto")[0]
    assert 60.0 <= per_side < 62.0  # both sides priced as maker fills with a small taker share (entry 0.973, exit 0.9), not the plain 80 bps


def test_r_fx6_the_forex_sleeve_is_off_through_the_clean_switch():
    assert V2["forex_risk"]["enabled"] is False and V2["forex_sleeve"]["enabled"] is False
    assert V2["sleeve_guards"]["forex"]["enabled"] is False
    assert V2["bond_sleeve"]["enabled"] is True and V2["sleeve_guards"]["bond"]["enabled"] is True  # untouched


def test_parity_and_latency_switches():
    features = CONFIG["phase1"]["features"]
    assert features["forex_fill_forward_bars"] == "flat" and features["late_bar_cross_asset"] == "own_tick"
    assert CONFIG["runtime"]["benchmark_ticker"] == "SPY"
    # null in the shipped state; BT1 / BT2 set the whole Lean span (2023-07-01..2026-09-30) and reset it afterwards
    assert CONFIG["runtime"]["lean_window_override"] in (None, {"start": "2023-07-01", "end": "2026-09-30"})
    assert V2["inference_parallelism"]["batch_experts_across_symbols"] is True
    assert V2["inference_parallelism"]["batch_flat_models_across_symbols"] is True
